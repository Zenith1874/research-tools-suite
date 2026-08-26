# -*- coding: utf-8 -*-
"""GPU contact must be on demand only.

Both GPU-backed modules used to reach the shared campus cluster as a side
effect of describing themselves: reading ``/api/*/config`` health-checked the
model, and the translation page polled that endpoint every 15 seconds.  Simply
leaving a tab open therefore kept contacting the cluster around the clock,
which is what got the account throttled and forced the modules to be shut off.

These tests pin the replacement contract:

* ``config()`` is pure description and performs **zero** outbound calls.
* Probing is a separate, explicitly named call the user has to trigger.
* Neither page schedules a probe on a timer.
* Both pages confirm before any action that will reach the cluster.
"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.audio_transcription_service import (
    AudioTranscriptionManager,
    RemoteAudioRunner,
)
from services.paper_translation_service import PaperTranslationManager


STATIC = Path(__file__).resolve().parents[1] / 'static'


class ExplodingClient:
    """Any attempt to reach the model during config() must fail the test."""
    model = 'test/private-model'

    def __init__(self):
        self.health_calls = 0

    def health(self):
        self.health_calls += 1
        return {'available': True, 'configured_model': self.model,
                'served_models': [self.model]}


class TranslationConfigTests(unittest.TestCase):

    def setUp(self):
        self.client = ExplodingClient()
        self.manager = PaperTranslationManager(
            Path(tempfile.mkdtemp()), client_factory=lambda: self.client)

    def tearDown(self):
        self.manager.shutdown(wait=False)

    def test_config_never_contacts_the_model(self):
        payload = self.manager.config()
        self.assertEqual(self.client.health_calls, 0,
                         'config() 不允许联系 GPU：这正是被限流的原因')
        self.assertEqual(payload['connection_policy'], 'on_demand_only')
        self.assertFalse(payload['model_service']['probed'])
        self.assertIsNone(payload['model_service']['available'])

    def test_config_still_reports_everything_the_page_needs(self):
        payload = self.manager.config()
        self.assertEqual(payload['model'], self.client.model)
        self.assertIn('max_upload_bytes', payload)
        self.assertIn('max_concurrent_jobs', payload)

    def test_probe_model_contacts_the_model_exactly_once(self):
        payload = self.manager.probe_model()
        self.assertEqual(self.client.health_calls, 1)
        self.assertTrue(payload['model_service']['probed'])
        self.assertTrue(payload['model_service']['available'])

    def test_repeated_config_reads_stay_free(self):
        for _ in range(20):
            self.manager.config()
        self.assertEqual(self.client.health_calls, 0)


class AudioConfigTests(unittest.TestCase):

    @patch('services.audio_transcription_service.shutil.which',
           side_effect=lambda name: name)
    @patch('services.audio_transcription_service.probe')
    def test_runner_config_opens_no_ssh(self, probe_host, _which):
        runner = RemoteAudioRunner()
        with patch.object(runner, '_transport') as transport:
            payload = runner.config()
        probe_host.assert_not_called()
        transport.assert_not_called()
        self.assertFalse(payload['probed'])
        self.assertIsNone(payload['connected'])
        self.assertEqual(payload['connection_policy'], 'on_demand_only')
        self.assertEqual(payload['host_status'], [])

    @patch('services.audio_transcription_service.shutil.which',
           side_effect=lambda name: name)
    @patch('services.audio_transcription_service.probe')
    def test_manager_config_probes_neither_cluster_nor_translator(
            self, probe_host, _which):
        translator = ExplodingClient()
        runner = RemoteAudioRunner()
        manager = AudioTranscriptionManager(
            Path(tempfile.mkdtemp()),
            runner_factory=lambda: runner,
            translator_factory=lambda: translator)
        with patch.object(runner, '_transport') as transport:
            payload = manager.config()
        probe_host.assert_not_called()
        transport.assert_not_called()
        self.assertEqual(translator.health_calls, 0,
                         'config() 不允许联系翻译模型')
        self.assertEqual(payload['connection_policy'], 'on_demand_only')
        self.assertFalse(payload['translation_service']['probed'])

    @patch('services.audio_transcription_service.shutil.which',
           side_effect=lambda name: name)
    @patch('services.audio_transcription_service.probe')
    def test_probe_services_reaches_both(self, probe_host, _which):
        probe_host.return_value = {'host': 'keller.cs.nmsu.edu', 'reachable': True,
                                   'gpus': []}
        translator = ExplodingClient()
        runner = RemoteAudioRunner()
        manager = AudioTranscriptionManager(
            Path(tempfile.mkdtemp()),
            runner_factory=lambda: runner,
            translator_factory=lambda: translator)
        with patch.object(runner, '_transport') as transport:
            transport.return_value.__enter__.return_value = (['ssh'], ['scp'])
            payload = manager.probe_services()
        self.assertTrue(probe_host.called)
        self.assertEqual(translator.health_calls, 1)
        self.assertTrue(payload['transcription_service']['probed'])


class PageBehaviourTests(unittest.TestCase):
    """The pages are where the 15-second polling lived; keep it gone."""

    def _script(self, name):
        html = (STATIC / name).read_text(encoding='utf-8')
        return re.search(r'<script>\n(.*)\n</script>', html, re.S).group(1)

    def test_translation_page_has_no_timer_that_reaches_the_cluster(self):
        script = self._script('paper_translation.html')
        for match in re.findall(r'setInterval\((.{0,60})', script):
            self.assertNotIn('loadConfig', match)
            self.assertNotIn('probe', match)
        self.assertNotIn("setInterval(loadConfig", script)

    def test_audio_page_has_no_timer_that_reaches_the_cluster(self):
        script = self._script('audio_transcription.html')
        for match in re.findall(r'setInterval\((.{0,60})', script):
            self.assertNotIn('loadConfig', match)
            self.assertNotIn('probe', match)

    def test_pages_probe_only_through_the_explicit_endpoint(self):
        for name in ('paper_translation.html', 'audio_transcription.html'):
            script = self._script(name)
            self.assertIn('/probe', script, f'{name} 需要显式探活入口')

    def test_probing_and_starting_a_job_both_ask_for_confirmation(self):
        for name, probe_fn in (('paper_translation.html', 'probeModel'),
                               ('audio_transcription.html', 'probeServices')):
            script = self._script(name)
            body = script.split(f'function {probe_fn}(', 1)[1][:400]
            self.assertIn('confirm(', body,
                          f'{name} 的探活必须先确认再连接')
        translation = self._script('paper_translation.html')
        submit_body = translation.split('async function submit(', 1)[1][:400]
        self.assertIn('confirm(', submit_body, '提交翻译前必须确认会占用 GPU')
        audio = self._script('audio_transcription.html')
        self.assertIn('确定现在开始吗', audio, '开始转录前必须确认会占用 GPU')


if __name__ == '__main__':
    unittest.main()
