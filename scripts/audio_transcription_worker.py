#!/usr/bin/env python3
"""Offline faster-whisper + pyannote worker deployed under nobackup.

The process writes only progress metadata to stdout. Transcript text is written
to the requested JSON file and is never logged. Heavy ML imports happen inside
``run`` so alignment helpers remain unit-testable without remote dependencies.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def emit(stage: str, percent: float, detail: str) -> None:
    print(json.dumps({
        'event': 'progress', 'stage': stage, 'percent': percent, 'detail': detail,
    }, ensure_ascii=False), flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _overlap(start: float, end: float, other_start: float, other_end: float) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def assign_words_to_speakers(words: list[dict], diarization: list[dict],
                             nearest_limit_seconds: float = 1.5) -> list[dict]:
    """Assign each word by overlap, then by a bounded nearest-segment fallback."""
    assigned = []
    for word in words:
        start = _finite(word.get('start'))
        end = max(start, _finite(word.get('end'), start))
        midpoint = (start + end) / 2
        candidates = []
        for segment in diarization:
            segment_start = _finite(segment.get('start'))
            segment_end = max(segment_start, _finite(segment.get('end'), segment_start))
            overlap = _overlap(start, end, segment_start, segment_end)
            distance = 0.0 if segment_start <= midpoint <= segment_end else min(
                abs(midpoint - segment_start), abs(midpoint - segment_end))
            candidates.append((overlap, -distance, str(segment.get('speaker') or 'UNKNOWN')))
        method = 'unassigned'
        speaker = 'UNKNOWN'
        if candidates:
            best_overlap, negative_distance, best_speaker = max(candidates)
            if best_overlap > 0:
                speaker = best_speaker
                method = 'overlap'
            elif -negative_distance <= nearest_limit_seconds:
                speaker = best_speaker
                method = 'nearest'
        row = dict(word)
        row.update(start=round(start, 3), end=round(end, 3), speaker=speaker,
                   speaker_assignment=method)
        assigned.append(row)
    return assigned


def normalize_speaker_labels(diarization: list[dict], words: list[dict]) -> tuple[list[dict], list[dict]]:
    ordered = []
    for segment in sorted(diarization, key=lambda row: (_finite(row.get('start')), _finite(row.get('end')))):
        label = str(segment.get('speaker') or 'UNKNOWN')
        if label != 'UNKNOWN' and label not in ordered:
            ordered.append(label)
    mapping = {label: f'SPEAKER_{index:02d}' for index, label in enumerate(ordered)}
    normalized_diarization = [
        {**segment, 'speaker': mapping.get(str(segment.get('speaker')), 'UNKNOWN')}
        for segment in diarization
    ]
    normalized_words = [
        {**word, 'speaker': mapping.get(str(word.get('speaker')), 'UNKNOWN')}
        for word in words
    ]
    return normalized_diarization, normalized_words


def group_words_into_turns(words: list[dict], *, max_gap_seconds: float = 1.5,
                           max_turn_seconds: float = 15.0,
                           max_characters: int = 240) -> list[dict]:
    """Create subtitle-sized turns without changing word timestamps or labels."""
    turns: list[dict] = []
    current: dict | None = None
    for word in sorted(words, key=lambda row: (_finite(row.get('start')), _finite(row.get('end')))):
        text = str(word.get('text') or '')
        if not text.strip():
            continue
        start = _finite(word.get('start'))
        end = max(start, _finite(word.get('end'), start))
        speaker = str(word.get('speaker') or 'UNKNOWN')
        must_split = current is None
        if current is not None:
            gap = start - current['end']
            duration = end - current['start']
            characters = len(current['text']) + len(text)
            must_split = (
                speaker != current['speaker'] or gap > max_gap_seconds
                or duration > max_turn_seconds or characters > max_characters
            )
        if must_split:
            if current is not None:
                current['text'] = current['text'].strip()
                current['turn_id'] = f'turn:{len(turns):06d}'
                turns.append(current)
            current = {
                'start': round(start, 3), 'end': round(end, 3),
                'speaker': speaker, 'text': text, 'words': [word],
            }
        else:
            current['end'] = round(max(current['end'], end), 3)
            current['text'] += text
            current['words'].append(word)
    if current is not None:
        current['text'] = current['text'].strip()
        current['turn_id'] = f'turn:{len(turns):06d}'
        turns.append(current)
    return turns


def _annotation_rows(annotation) -> list[dict]:
    rows = []
    if hasattr(annotation, 'itertracks'):
        iterator = annotation.itertracks(yield_label=True)
        for segment, _track, label in iterator:
            rows.append({
                'start': round(_finite(segment.start), 3),
                'end': round(_finite(segment.end), 3),
                'speaker': str(label),
            })
        return rows
    for item in annotation:
        if len(item) == 2:
            segment, label = item
        else:
            segment, _track, label = item
        rows.append({
            'start': round(_finite(segment.start), 3),
            'end': round(_finite(segment.end), 3),
            'speaker': str(label),
        })
    return rows


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def run(args) -> dict:
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    os.environ.setdefault('PYANNOTE_METRICS_ENABLED', '0')
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if not input_path.is_file():
        raise RuntimeError('input file does not exist')
    if output_path.parent != input_path.parent:
        raise RuntimeError('input and output must share the same private job directory')

    emit('loading_asr', 22, '正在加载本地 faster-whisper-medium 权重')
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    compute_type = 'float16' if args.asr_device == 'cuda' else 'int8'
    model = WhisperModel(
        args.asr_model, device=args.asr_device, compute_type=compute_type,
        local_files_only=True,
    )
    emit('transcribing', 30, '正在生成逐词时间戳')
    segments_iterator, info = model.transcribe(
        str(input_path), language=args.language or None, beam_size=5,
        word_timestamps=True, vad_filter=True,
        vad_parameters={'min_silence_duration_ms': 500},
        condition_on_previous_text=True,
    )
    asr_segments = []
    words = []
    for segment_index, segment in enumerate(segments_iterator):
        segment_words = []
        for word in segment.words or []:
            row = {
                'start': round(_finite(word.start), 3),
                'end': round(_finite(word.end, _finite(word.start)), 3),
                'text': str(word.word or ''),
                'probability': round(_finite(getattr(word, 'probability', 0.0)), 6),
                'asr_segment': segment_index,
            }
            segment_words.append(row)
            words.append(row)
        if not segment_words and str(segment.text or '').strip():
            row = {
                'start': round(_finite(segment.start), 3),
                'end': round(_finite(segment.end, _finite(segment.start)), 3),
                'text': str(segment.text or ''),
                'probability': None,
                'asr_segment': segment_index,
            }
            segment_words.append(row)
            words.append(row)
        asr_segments.append({
            'segment_id': segment_index,
            'start': round(_finite(segment.start), 3),
            'end': round(_finite(segment.end), 3),
            'text': str(segment.text or '').strip(),
            'avg_logprob': round(_finite(getattr(segment, 'avg_logprob', 0.0)), 6),
            'no_speech_prob': round(_finite(getattr(segment, 'no_speech_prob', 0.0)), 6),
        })
    if not words:
        raise RuntimeError('no speech was detected')
    del model
    gc.collect()

    emit('loading_diarization', 56, '正在加载本地 Community-1 说话人区分权重')
    import torch
    from pyannote.audio import Pipeline

    if args.diarization_device == 'cuda' and torch.cuda.is_available():
        torch.cuda.empty_cache()
    # Decode once into a mono 16 kHz waveform.  This avoids torchcodec/ffmpeg
    # system dependencies and gives pyannote its documented in-memory input.
    waveform_array = decode_audio(str(input_path), sampling_rate=16000)
    waveform = torch.from_numpy(waveform_array).float().unsqueeze(0)
    pipeline = Pipeline.from_pretrained(args.diarization_model)
    if args.diarization_device == 'cuda':
        pipeline.to(torch.device('cuda'))
    kwargs = {}
    if args.num_speakers is not None:
        kwargs['num_speakers'] = args.num_speakers
    else:
        if args.min_speakers is not None:
            kwargs['min_speakers'] = args.min_speakers
        if args.max_speakers is not None:
            kwargs['max_speakers'] = args.max_speakers
    emit('diarizing', 64, '正在检测说话人切换和聚类')
    diarization_output = pipeline(
        {'waveform': waveform, 'sample_rate': 16000}, **kwargs)
    annotation = getattr(diarization_output, 'exclusive_speaker_diarization', None)
    if annotation is None:
        annotation = getattr(diarization_output, 'speaker_diarization', diarization_output)
    diarization = _annotation_rows(annotation)
    if not diarization:
        raise RuntimeError('no speaker activity was detected')

    emit('aligning', 80, '正在将逐词时间戳与匿名说话人标签对齐')
    assigned_words = assign_words_to_speakers(words, diarization)
    diarization, assigned_words = normalize_speaker_labels(diarization, assigned_words)
    turns = group_words_into_turns(assigned_words)
    speakers = sorted({row['speaker'] for row in diarization if row['speaker'] != 'UNKNOWN'})
    duration = _finite(getattr(info, 'duration', 0.0))
    if not duration:
        duration = max([row['end'] for row in assigned_words] + [0.0])
    result = {
        'schema_version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'input_sha256': sha256_file(input_path),
        'duration_seconds': round(duration, 3),
        'language': str(getattr(info, 'language', '') or args.language or ''),
        'language_probability': round(_finite(getattr(info, 'language_probability', 0.0)), 6),
        'speaker_count': len(speakers),
        'speakers': speakers,
        'models': {
            'asr': 'Systran/faster-whisper-medium',
            'diarization': 'pyannote/speaker-diarization-community-1',
        },
        'package_versions': {
            'faster-whisper': _package_version('faster-whisper'),
            'ctranslate2': _package_version('ctranslate2'),
            'pyannote-audio': _package_version('pyannote-audio'),
            'torch': _package_version('torch'),
        },
        'parameters': {
            'asr_device': args.asr_device,
            'diarization_device': args.diarization_device,
            'compute_type': compute_type,
            'beam_size': 5,
            'vad_filter': True,
            'word_timestamps': True,
            'num_speakers': args.num_speakers,
            'min_speakers': args.min_speakers,
            'max_speakers': args.max_speakers,
            'diarization_mode': 'exclusive_if_available',
        },
        'asr_segments': asr_segments,
        'diarization_segments': diarization,
        'turns': turns,
        'audit': {
            'word_count': len(assigned_words),
            'turn_count': len(turns),
            'unassigned_word_count': sum(
                1 for word in assigned_words if word.get('speaker') == 'UNKNOWN'),
            'nearest_fallback_word_count': sum(
                1 for word in assigned_words if word.get('speaker_assignment') == 'nearest'),
            'speaker_labels_anonymous': True,
            'speaker_identity_inference': False,
            'timestamps_rounded_milliseconds': True,
        },
    }
    emit('writing_result', 84, '正在写入经过校验的结构化结果')
    _atomic_json(output_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--asr-model', required=True)
    parser.add_argument('--diarization-model', required=True)
    parser.add_argument('--asr-device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--diarization-device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--language')
    parser.add_argument('--num-speakers', type=int)
    parser.add_argument('--min-speakers', type=int)
    parser.add_argument('--max-speakers', type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        run(args)
    except Exception as exc:
        # Error type/message only: never echo transcript content, token, or raw
        # model response. The local service exposes a generic user-safe error.
        print(json.dumps({
            'event': 'worker_error', 'error_type': type(exc).__name__,
            'message': str(exc)[:300],
        }, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1
    emit('completed_remote', 85, '远端转录与说话人区分完成')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
