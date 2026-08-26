# -*- coding: utf-8 -*-
"""Privacy, alignment, checkpoint, and export guards for audio research jobs."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.audio_transcription_worker import (
    assign_words_to_speakers,
    group_words_into_turns,
    normalize_speaker_labels,
)
from services.audio_transcription_service import (
    AudioTranscriptionError,
    AudioTranscriptionManager,
    DEFAULT_AUDIO_HOSTS,
    RemoteAudioRunner,
    normalize_audio_options,
    render_plain_text,
    render_srt,
    render_vtt,
)


class FakeRunner:
    calls = 0

    def config(self):
        return {'available': True, 'hosts': ['test-host']}

    def transcribe(self, *, job_id, input_path, job_dir, options, progress):
        self.calls += 1
        progress('transcribing', 40, 'test transcription')
        digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
        words = [
            {'start': 0.1, 'end': 0.5, 'text': ' Hello', 'speaker': 'SPEAKER_00'},
            {'start': 0.6, 'end': 1.0, 'text': ' world.', 'speaker': 'SPEAKER_00'},
            {'start': 1.2, 'end': 1.7, 'text': ' Evidence.', 'speaker': 'SPEAKER_01'},
        ]
        return {
            'schema_version': 1,
            'input_sha256': digest,
            'duration_seconds': 1.7,
            'language': 'en',
            'speaker_count': 2,
            'speakers': ['SPEAKER_00', 'SPEAKER_01'],
            'turns': [
                {'turn_id': 'turn:000000', 'start': 0.1, 'end': 1.0,
                 'speaker': 'SPEAKER_00', 'text': 'Hello world.', 'words': words[:2]},
                {'turn_id': 'turn:000001', 'start': 1.2, 'end': 1.7,
                 'speaker': 'SPEAKER_01', 'text': 'Evidence.', 'words': words[2:]},
            ],
            'audit': {'word_count': 3, 'turn_count': 2, 'speaker_labels_anonymous': True},
        }, {
            'host': 'test-host', 'gpu_index': 0, 'remote_cleanup_verified': True,
            'worker_diagnostics': ['must not be public'],
        }


class FakeTranslator:
    model = 'test/private-qwen'

    def health(self):
        return {'available': True, 'configured_model': self.model}

    def translate_units(self, units, options, progress=None, checkpoint=None):
        for index, unit in enumerate(units, 1):
            unit.translations = {'0': '译文：' + unit.segments[0].core_text}
            if checkpoint:
                checkpoint({'unit_ids': [unit.unit_id]})
            if progress:
                progress(index, len(units))


class AudioOptionTests(unittest.TestCase):
    def test_keller_is_the_default_audio_host(self):
        self.assertEqual(DEFAULT_AUDIO_HOSTS, ('keller.cs.nmsu.edu',))
        self.assertEqual(RemoteAudioRunner().hosts, ('keller.cs.nmsu.edu',))

    @patch('services.audio_transcription_service.shutil.which', side_effect=lambda name: name)
    @patch('services.audio_transcription_service.probe')
    def test_explicit_probe_connects_to_keller_and_reports_idle_state(self, probe_host, _which):
        probe_host.return_value = {
            'host': 'keller.cs.nmsu.edu', 'reachable': True,
            'gpus': [{
                'index': 0, 'name': 'test-gpu', 'memory_total_mib': 20475,
                'memory_used_mib': 13, 'utilization_percent': 0,
            }],
        }
        runner = RemoteAudioRunner()
        with patch.object(runner, '_transport') as transport:
            transport.return_value.__enter__.return_value = (['ssh'], ['scp'])
            config = runner.config(probe_hosts=True)
        probe_host.assert_called_once_with('keller.cs.nmsu.edu', ['ssh'])
        self.assertTrue(config['probed'])
        self.assertTrue(config['connected'])
        self.assertTrue(config['idle_available'])
        self.assertEqual(config['host_status'][0]['host'], 'keller.cs.nmsu.edu')

    def test_exact_speaker_count_disables_range(self):
        options = normalize_audio_options({
            'num_speakers': '3', 'min_speakers': '1', 'max_speakers': '7',
        })
        self.assertEqual(options['num_speakers'], 3)
        self.assertIsNone(options['min_speakers'])
        self.assertIsNone(options['max_speakers'])

    def test_invalid_speaker_range_is_rejected(self):
        with self.assertRaises(AudioTranscriptionError):
            normalize_audio_options({'min_speakers': 5, 'max_speakers': 2})
        with self.assertRaises(AudioTranscriptionError):
            normalize_audio_options({'num_speakers': 21})


class AlignmentTests(unittest.TestCase):
    def test_overlap_then_nearest_assignment_and_anonymous_labels(self):
        diarization = [
            {'start': 0.0, 'end': 1.0, 'speaker': 'raw-A'},
            {'start': 1.2, 'end': 2.0, 'speaker': 'raw-B'},
        ]
        words = [
            {'start': 0.2, 'end': 0.6, 'text': ' one'},
            {'start': 1.05, 'end': 1.1, 'text': ' two'},
        ]
        assigned = assign_words_to_speakers(words, diarization)
        self.assertEqual(assigned[0]['speaker_assignment'], 'overlap')
        self.assertEqual(assigned[1]['speaker_assignment'], 'nearest')
        diarization, assigned = normalize_speaker_labels(diarization, assigned)
        self.assertEqual([row['speaker'] for row in diarization], ['SPEAKER_00', 'SPEAKER_01'])
        self.assertNotIn('raw-A', json.dumps(assigned))

    def test_turns_split_at_speaker_change_and_keep_word_times(self):
        words = [
            {'start': 0.1, 'end': 0.4, 'text': ' Hello', 'speaker': 'SPEAKER_00'},
            {'start': 0.5, 'end': 0.8, 'text': ' there.', 'speaker': 'SPEAKER_00'},
            {'start': 0.9, 'end': 1.2, 'text': ' Yes.', 'speaker': 'SPEAKER_01'},
        ]
        turns = group_words_into_turns(words)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]['text'], 'Hello there.')
        self.assertEqual(turns[0]['words'][0]['start'], 0.1)
        self.assertEqual(turns[1]['speaker'], 'SPEAKER_01')


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            'language': 'en', 'duration_seconds': 2.0, 'speaker_count': 1,
            'turns': [{
                'start': 0.125, 'end': 1.75, 'speaker': 'SPEAKER_00',
                'text': 'Original.', 'translated_text': '译文。',
            }],
        }

    def test_srt_and_vtt_share_exact_timeline(self):
        srt = render_srt(self.result, bilingual=True)
        vtt = render_vtt(self.result, bilingual=True)
        self.assertIn('00:00:00,125 --> 00:00:01,750', srt)
        self.assertIn('00:00:00.125 --> 00:00:01.750', vtt)
        self.assertIn('Original.\n译文。', srt)

    def test_plain_text_keeps_anonymous_speaker(self):
        text = render_plain_text(self.result, bilingual=True)
        self.assertIn('SPEAKER_00', text)
        self.assertIn('Original.', text)
        self.assertIn('译文。', text)


class AudioManagerTests(unittest.TestCase):
    def test_result_view_tracks_progress_then_exposes_compact_turns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AudioTranscriptionManager(
                Path(temp_dir) / 'jobs', runner_factory=FakeRunner,
                translator_factory=FakeTranslator,
            )
            created = manager.create_job('x.wav', b'audio', {'translate': True}, start=False)
            pending = manager.view_result(created['job_id'])
            self.assertEqual(pending['job']['status'], 'queued')
            self.assertIsNone(pending['transcript'])

            manager.run_job_sync(created['job_id'])
            completed = manager.view_result(created['job_id'])
            self.assertEqual(completed['job']['status'], 'completed')
            self.assertEqual(len(completed['transcript']['turns']), 2)
            self.assertEqual(completed['transcript']['turns'][0]['translated_text'],
                             '译文：Hello world.')
            self.assertNotIn('words', completed['transcript']['turns'][0])
            self.assertNotIn('diarization_segments', completed['transcript'])
            self.assertNotIn('input_sha256', completed['transcript'])

    def test_streamed_job_generates_auditable_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = FakeRunner()
            translator = FakeTranslator()
            manager = AudioTranscriptionManager(
                Path(temp_dir) / 'jobs', max_upload_bytes=1024,
                runner_factory=lambda: runner,
                translator_factory=lambda: translator,
            )
            content = b'fake-private-audio'
            created = manager.create_job_from_stream(
                'interview.mp3', io.BytesIO(content), len(content),
                {'translate': True, 'num_speakers': 2}, start=False,
            )
            job_id = created['job_id']
            manager.run_job_sync(job_id)
            completed = manager.get_job(job_id)
            self.assertEqual(completed['status'], 'completed')
            self.assertEqual(completed['speaker_count'], 2)
            self.assertTrue(completed['audit']['input_sha256_verified_by_worker'])
            self.assertTrue(completed['audit']['remote_cleanup_verified'])
            self.assertNotIn('worker_diagnostics', completed['runtime'])
            bundle, _name, content_type = manager.output_path(job_id, 'bundle')
            self.assertEqual(content_type, 'application/zip')
            with zipfile.ZipFile(bundle) as archive:
                names = archive.namelist()
                self.assertTrue(any(name.endswith('_transcript.json') for name in names))
                self.assertTrue(any(name.endswith('_bilingual.srt') for name in names))
            transcript = json.loads((Path(temp_dir) / 'jobs' / job_id / 'transcript.json').read_text(encoding='utf-8'))
            self.assertEqual(transcript['turns'][0]['translated_text'], '译文：Hello world.')

    def test_short_upload_is_rejected_and_partial_job_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'jobs'
            manager = AudioTranscriptionManager(
                root, max_upload_bytes=1024,
                runner_factory=FakeRunner, translator_factory=FakeTranslator,
            )
            with self.assertRaises(AudioTranscriptionError):
                manager.create_job_from_stream(
                    'interview.wav', io.BytesIO(b'short'), 20,
                    {'translate': False}, start=False,
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_output_path_rejects_unknown_kind(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AudioTranscriptionManager(
                Path(temp_dir) / 'jobs', runner_factory=FakeRunner,
                translator_factory=FakeTranslator,
            )
            created = manager.create_job('x.wav', b'audio', {'translate': False}, start=False)
            manager.run_job_sync(created['job_id'])
            with self.assertRaises(AudioTranscriptionError):
                manager.output_path(created['job_id'], '../secret')

    def test_completed_transcript_can_add_translation_without_rerunning_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = FakeRunner()
            runner.calls = 0
            manager = AudioTranscriptionManager(
                Path(temp_dir) / 'jobs', runner_factory=lambda: runner,
                translator_factory=FakeTranslator,
            )
            created = manager.create_job('x.wav', b'audio', {'translate': False}, start=False)
            manager.run_job_sync(created['job_id'])
            self.assertEqual(runner.calls, 1)
            manager.translate_job(
                created['job_id'], {'target_language': 'Simplified Chinese'}, start=False)
            manager.run_job_sync(created['job_id'])
            completed = manager.get_job(created['job_id'])
            self.assertEqual(completed['status'], 'completed')
            self.assertEqual(runner.calls, 1)
            self.assertTrue(completed['audit']['resumed_transcript'])
            self.assertIn('bilingual_srt', completed['outputs'])


if __name__ == '__main__':
    unittest.main()
