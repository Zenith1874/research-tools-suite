# -*- coding: utf-8 -*-
"""Private, auditable audio transcription, diarization, and translation jobs.

Audio is staged to a selected campus host over SSH, processed by locally cached
models, copied back after a SHA-256 check, and then removed from the exact
remote job directory.  Speaker labels are anonymous; this module does not infer
identity, gender, age, emotion, or other personal attributes from a voice.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 无窗父进程 spawn 控制台程序不弹窗
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, Callable, Iterable

from scripts.check_translation_hosts import (
    _discover_windows_ssh,
    _ssh_base,
    choose_recommendation,
    probe,
)
from services.paper_translation_service import (
    AcademicTranslationClient,
    Segment,
    TranslationUnit,
    parse_glossary,
)


AUDIO_DEFAULT_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
DEFAULT_AUDIO_HOSTS = ('keller.cs.nmsu.edu',)
AUDIO_SUPPORTED_EXTENSIONS = {
    '.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg', '.opus',
    '.mp4', '.mov', '.mkv', '.webm',
}
_JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')
_OUTPUT_KIND_RE = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
_LANGUAGE_CODES = {
    'auto': None,
    'auto detect': None,
    '自动检测': None,
    'english': 'en',
    '英文': 'en',
    'simplified chinese': 'zh',
    'traditional chinese': 'zh',
    'chinese': 'zh',
    '简体中文': 'zh',
    '繁体中文': 'zh',
    '中文': 'zh',
    'spanish': 'es',
    '西班牙语': 'es',
    'french': 'fr',
    '法语': 'fr',
    'german': 'de',
    '德语': 'de',
    'japanese': 'ja',
    '日语': 'ja',
    'korean': 'ko',
    '韩语': 'ko',
}


class AudioTranscriptionError(RuntimeError):
    """A user-safe error that must never include transcript text or secrets."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(value, encoding='utf-8', newline='\n')
    os.replace(temporary, path)


def _safe_filename(value: str) -> str:
    name = os.path.basename((value or '').replace('\\', '/')).strip()
    name = ''.join(character for character in name if character >= ' ' and character != '\x7f')
    if not name or name in {'.', '..'} or len(name) > 180:
        raise AudioTranscriptionError('文件名无效或过长')
    return name


def decode_audio_options_header(value: str | None) -> dict:
    if not value:
        return {}
    try:
        padding = '=' * (-len(value) % 4)
        raw = base64.urlsafe_b64decode((value + padding).encode('ascii'))
        payload = json.loads(raw.decode('utf-8'))
    except Exception as exc:
        raise AudioTranscriptionError('语音任务选项格式无效') from exc
    if not isinstance(payload, dict):
        raise AudioTranscriptionError('语音任务选项必须是对象')
    return payload


def _optional_speaker_count(value, field_name: str) -> int | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise AudioTranscriptionError(f'{field_name}必须是整数') from exc
    if not 1 <= count <= 20:
        raise AudioTranscriptionError(f'{field_name}必须在 1 到 20 之间')
    return count


def normalize_audio_options(options: dict | None) -> dict:
    options = options if isinstance(options, dict) else {}
    source_language = str(options.get('source_language') or 'Auto detect').strip()[:60]
    source_code = _LANGUAGE_CODES.get(source_language.casefold())
    if source_language.casefold() not in _LANGUAGE_CODES:
        source_code = str(options.get('source_language_code') or '').strip().casefold() or None
        if source_code and not re.fullmatch(r'[a-z]{2,3}', source_code):
            raise AudioTranscriptionError('源语言代码无效')
    target_language = str(options.get('target_language') or 'Simplified Chinese').strip()[:60]
    translate = bool(options.get('translate', True))
    num_speakers = _optional_speaker_count(options.get('num_speakers'), '说话人数')
    min_speakers = _optional_speaker_count(options.get('min_speakers'), '最少说话人数')
    max_speakers = _optional_speaker_count(options.get('max_speakers'), '最多说话人数')
    if num_speakers is not None:
        min_speakers = max_speakers = None
    elif min_speakers is not None and max_speakers is not None and min_speakers > max_speakers:
        raise AudioTranscriptionError('最少说话人数不能大于最多说话人数')
    domain = str(options.get('domain') or (
        'Research interviews, meetings, Information Systems, Management, OB/HR, '
        'and computational social science'
    )).strip()[:300]
    return {
        'source_language': source_language,
        'source_language_code': source_code,
        'translate': translate,
        'target_language': target_language,
        'domain': domain,
        'glossary': parse_glossary(options.get('glossary')),
        'num_speakers': num_speakers,
        'min_speakers': min_speakers,
        'max_speakers': max_speakers,
        'speaker_labels': 'anonymous',
        'remote_retention': 'delete_after_verified_copy',
    }


def _language_name(code: str | None) -> str:
    return {
        'en': 'English', 'zh': 'Chinese', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'ja': 'Japanese', 'ko': 'Korean',
    }.get((code or '').casefold(), code or 'Auto detect')


def _same_language(source_code: str | None, target: str) -> bool:
    target_code = _LANGUAGE_CODES.get((target or '').casefold())
    return bool(source_code and target_code and source_code == target_code)


def _format_timestamp(seconds: float, srt: bool = False) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    separator = ',' if srt else '.'
    return f'{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}'


def _turn_text(turn: dict, translated: bool = False) -> str:
    if translated:
        return str(turn.get('translated_text') or '').strip()
    return str(turn.get('text') or '').strip()


def render_plain_text(result: dict, translated: bool = False, bilingual: bool = False) -> str:
    title = 'Bilingual transcript' if bilingual else ('Translated transcript' if translated else 'Transcript')
    lines = [
        title,
        f"Detected language: {result.get('language') or 'unknown'}",
        f"Duration seconds: {result.get('duration_seconds') or 0}",
        f"Speakers: {result.get('speaker_count') or 0}",
        '',
    ]
    for turn in result.get('turns') or []:
        start = _format_timestamp(turn.get('start', 0))
        end = _format_timestamp(turn.get('end', 0))
        speaker = turn.get('speaker') or 'UNKNOWN'
        source = _turn_text(turn)
        target = _turn_text(turn, translated=True)
        if bilingual:
            lines.extend([f'[{start} --> {end}] {speaker}', source, target, ''])
        else:
            lines.extend([f'[{start} --> {end}] {speaker}: {target if translated else source}', ''])
    return '\n'.join(lines).rstrip() + '\n'


def render_srt(result: dict, translated: bool = False, bilingual: bool = False) -> str:
    blocks = []
    for index, turn in enumerate(result.get('turns') or [], 1):
        start = _format_timestamp(turn.get('start', 0), srt=True)
        end = _format_timestamp(turn.get('end', 0), srt=True)
        speaker = turn.get('speaker') or 'UNKNOWN'
        source = _turn_text(turn)
        target = _turn_text(turn, translated=True)
        if bilingual:
            body = f'{speaker}: {source}\n{target}'
        else:
            body = f'{speaker}: {target if translated else source}'
        blocks.append(f'{index}\n{start} --> {end}\n{body}')
    return '\n\n'.join(blocks) + ('\n' if blocks else '')


def render_vtt(result: dict, translated: bool = False, bilingual: bool = False) -> str:
    blocks = ['WEBVTT']
    for turn in result.get('turns') or []:
        start = _format_timestamp(turn.get('start', 0))
        end = _format_timestamp(turn.get('end', 0))
        speaker = turn.get('speaker') or 'UNKNOWN'
        source = _turn_text(turn)
        target = _turn_text(turn, translated=True)
        if bilingual:
            body = f'<v {speaker}>{source}\n{target}'
        else:
            body = f'<v {speaker}>{target if translated else source}'
        blocks.append(f'{start} --> {end}\n{body}')
    return '\n\n'.join(blocks) + '\n'


def _translation_hash(turn: dict) -> str:
    payload = {
        'speaker': turn.get('speaker'),
        'start': round(float(turn.get('start', 0)), 3),
        'end': round(float(turn.get('end', 0)), 3),
        'text': str(turn.get('text') or ''),
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


class RemoteAudioRunner:
    """Select an idle GPU and run the deployed offline worker over SSH/SCP."""

    def __init__(self, *, hosts: Iterable[str] | None = None, remote_root: str | None = None,
                 python_path: str | None = None, max_wait_seconds: int | None = None,
                 poll_seconds: int | None = None, timeout_seconds: int | None = None):
        configured_hosts = os.environ.get('AUDIO_TRANSCRIPTION_HOSTS', '')
        self.hosts = tuple(hosts or (
            [item.strip() for item in configured_hosts.split(',') if item.strip()]
            or DEFAULT_AUDIO_HOSTS
        ))
        self.remote_root = remote_root or os.environ.get(
            'AUDIO_TRANSCRIPTION_REMOTE_ROOT', '/home/simurghnobackup/zcui/audio_transcription')
        self.python_path = python_path or os.environ.get(
            'AUDIO_TRANSCRIPTION_PYTHON', '/home/simurghnobackup/zcui/venvs/reddit_env/bin/python')
        self.worker_path = f'{self.remote_root}/bin/audio_transcription_worker.py'
        self.vendor_path = os.environ.get(
            'AUDIO_TRANSCRIPTION_VENDOR', f'{self.remote_root}/vendor-20260721')
        self.asr_model_path = os.environ.get(
            'AUDIO_ASR_MODEL_PATH',
            '/home/simurghnobackup/zcui/.cache/huggingface/hub/'
            'models--Systran--faster-whisper-medium/snapshots/'
            '08e178d48790749d25932bbc082711ddcfdfbc4f')
        self.diarization_model_path = os.environ.get(
            'AUDIO_DIARIZATION_MODEL_PATH',
            '/home/simurghnobackup/zcui/.cache/huggingface/hub/'
            'models--pyannote--speaker-diarization-community-1/snapshots/'
            '3533c8cf8e369892e6b79ff1bf80f7b0286a54ee')
        self.max_wait_seconds = int(max_wait_seconds if max_wait_seconds is not None else
                                    os.environ.get('AUDIO_GPU_WAIT_SECONDS', 900))
        self.poll_seconds = int(poll_seconds if poll_seconds is not None else
                                os.environ.get('AUDIO_GPU_POLL_SECONDS', 30))
        self.timeout_seconds = int(timeout_seconds if timeout_seconds is not None else
                                   os.environ.get('AUDIO_JOB_TIMEOUT_SECONDS', 12 * 60 * 60))
        self.max_used_mib = int(os.environ.get('AUDIO_GPU_MAX_USED_MIB', 1024))
        self.max_utilization = int(os.environ.get('AUDIO_GPU_MAX_UTILIZATION', 10))
        self.ssh_timeout = int(os.environ.get('AUDIO_SSH_TIMEOUT_SECONDS', 10))

    def config(self) -> dict:
        transport_available = bool(shutil.which('ssh') and shutil.which('scp'))
        host_status = []
        recommendation = None
        if transport_available:
            try:
                with self._transport() as (ssh_command, _scp_command):
                    host_status = [probe(host, ssh_command) for host in self.hosts]
                recommendation = choose_recommendation(
                    host_status, self.max_used_mib, self.max_utilization)
            except Exception:
                host_status = [
                    {'host': host, 'reachable': False, 'error': ['SSH connection check failed']}
                    for host in self.hosts
                ]
        return {
            'available': transport_available,
            'connected': any(row.get('reachable') for row in host_status),
            'idle_available': recommendation is not None,
            'hosts': list(self.hosts),
            'host_status': host_status,
            'selection': 'least_used_idle_gpu',
            'idle_thresholds': {
                'memory_used_mib': self.max_used_mib,
                'utilization_percent': self.max_utilization,
            },
            'wait_seconds': self.max_wait_seconds,
            'remote_retention': 'deleted_after_verified_result_copy',
            'asr_model': 'Systran/faster-whisper-medium (local snapshot)',
            'diarization_model': 'pyannote/speaker-diarization-community-1 (local snapshot)',
        }

    @contextmanager
    def _transport(self):
        if not shutil.which('ssh') or not shutil.which('scp'):
            raise AudioTranscriptionError('本机未找到 ssh/scp，无法连接校内模型主机')
        args = SimpleNamespace(
            timeout=self.ssh_timeout, ssh_config=None, identity=None, known_hosts=None,
        )
        native_identity = Path.home() / '.ssh' / 'id_ed25519'
        if not native_identity.is_file():
            discovered = _discover_windows_ssh()
            args.identity = discovered.get('identity')
            args.ssh_config = discovered.get('ssh_config')
            args.known_hosts = discovered.get('known_hosts')
        secure_temp_root = '/tmp' if os.name == 'posix' and Path('/tmp').is_dir() else None
        with tempfile.TemporaryDirectory(prefix='audio-transcription-ssh-', dir=secure_temp_root) as temp_dir:
            temporary_identity = None
            if args.identity:
                temporary_identity = str(Path(temp_dir) / 'identity')
                shutil.copyfile(Path(args.identity), temporary_identity)
                os.chmod(temporary_identity, 0o600)
            ssh_command = _ssh_base(args, temporary_identity)
            ssh_command[0] = shutil.which('ssh') or 'ssh'
            scp_command = [shutil.which('scp') or 'scp', *ssh_command[1:]]
            yield ssh_command, scp_command

    def _select_gpu(self, ssh_command: list[str], progress: Callable) -> tuple[str, int, list[dict]]:
        deadline = time.monotonic() + max(0, self.max_wait_seconds)
        last_rows: list[dict] = []
        while True:
            last_rows = [probe(host, ssh_command) for host in self.hosts]
            recommendation = choose_recommendation(
                last_rows, self.max_used_mib, self.max_utilization)
            if recommendation:
                return recommendation['host'], recommendation['gpu_index'], last_rows
            remaining = max(0, round(deadline - time.monotonic()))
            host_names = '、'.join(host.split('.', 1)[0] for host in self.hosts)
            progress('waiting_for_gpu', 5, f'{host_names} 暂时没有空闲 GPU；最多再等待 {remaining} 秒')
            if time.monotonic() >= deadline:
                raise AudioTranscriptionError(f'等待超时：{host_names} 当前没有符合阈值的空闲 GPU')
            time.sleep(min(self.poll_seconds, max(1, remaining)))

    @staticmethod
    def _run_checked(command: list[str], *, timeout: int, safe_error: str) -> subprocess.CompletedProcess:
        try:
            completed = subprocess.run(
                command, text=True, encoding='utf-8', errors='replace',
                capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioTranscriptionError(f'{safe_error}：操作超时') from exc
        if completed.returncode:
            raise AudioTranscriptionError(safe_error)
        return completed

    def transcribe(self, *, job_id: str, input_path: Path, job_dir: Path, options: dict,
                   progress: Callable[[str, float, str], None]) -> tuple[dict, dict]:
        if not _JOB_ID_RE.fullmatch(job_id):
            raise AudioTranscriptionError('任务编号无效')
        remote_job_dir = f'{self.remote_root}/jobs/{job_id}'
        remote_input = f'{remote_job_dir}/source{input_path.suffix.casefold()}'
        remote_output = f'{remote_job_dir}/result.json'
        local_part = job_dir / 'remote_result.json.part'
        created_remote = False
        cleanup_verified = False
        runtime: dict = {}
        with self._transport() as (ssh_command, scp_command):
            host, gpu_index, rows = self._select_gpu(ssh_command, progress)
            runtime = {
                'host': host,
                'gpu_index': gpu_index,
                'selected_at': _utc_now(),
                'probe': next((row for row in rows if row.get('host') == host), {}),
            }
            mkdir_command = (
                f'install -d -m 700 {shlex.quote(self.remote_root + "/jobs")} '
                f'{shlex.quote(remote_job_dir)}'
            )
            self._run_checked(
                ssh_command + [host, mkdir_command], timeout=30,
                safe_error='无法创建远端私有任务目录')
            created_remote = True
            try:
                progress('uploading', 10, f'正在通过 SSH 加密传输到 {host}')
                self._run_checked(
                    scp_command + [str(input_path), f'{host}:{remote_input}'],
                    timeout=max(300, self.timeout_seconds // 4),
                    safe_error='音频加密传输失败')
                arguments = [
                    self.python_path, self.worker_path,
                    '--input', remote_input,
                    '--output', remote_output,
                    '--asr-model', self.asr_model_path,
                    '--diarization-model', self.diarization_model_path,
                    '--asr-device', 'cpu',
                    '--diarization-device', 'cuda',
                ]
                if options.get('source_language_code'):
                    arguments += ['--language', options['source_language_code']]
                for option_name in ('num_speakers', 'min_speakers', 'max_speakers'):
                    if options.get(option_name) is not None:
                        arguments += ['--' + option_name.replace('_', '-'), str(options[option_name])]
                worker_command = ' '.join(shlex.quote(item) for item in arguments)
                remote_command = (
                    f'export PYTHONPATH={shlex.quote(self.vendor_path)}; '
                    'export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYANNOTE_METRICS_ENABLED=0; '
                    f'export CUDA_VISIBLE_DEVICES={int(gpu_index)}; '
                    f'timeout --signal=TERM {int(self.timeout_seconds)} {worker_command}'
                )
                progress('transcribing', 20, f'{host} GPU {gpu_index} 正在进行逐词转录')
                process = subprocess.Popen(
                    ssh_command + [host, remote_command], text=True,
                    encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, bufsize=1, creationflags=_NO_WINDOW,
                )
                diagnostic_lines: list[str] = []
                assert process.stdout is not None
                for raw_line in process.stdout:
                    line = raw_line.strip()
                    try:
                        event = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        if line:
                            diagnostic_lines.append(line[-400:])
                            diagnostic_lines = diagnostic_lines[-20:]
                        continue
                    if isinstance(event, dict) and event.get('event') == 'progress':
                        progress(
                            str(event.get('stage') or 'processing'),
                            float(event.get('percent') or 20),
                            str(event.get('detail') or '远端模型正在处理'),
                        )
                return_code = process.wait()
                if return_code:
                    _atomic_text(
                        job_dir / 'remote_diagnostics.log',
                        '\n'.join(diagnostic_lines).rstrip() + '\n')
                    raise AudioTranscriptionError(
                        '远端语音模型运行失败；详细诊断已保留在本机任务审计记录中')
                progress('downloading', 86, '正在复制并校验结构化转录结果')
                self._run_checked(
                    scp_command + [f'{host}:{remote_output}', str(local_part)],
                    timeout=300, safe_error='转录结果复制失败')
                try:
                    result = json.loads(local_part.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError) as exc:
                    raise AudioTranscriptionError('远端转录结果不是有效 JSON') from exc
                if not isinstance(result, dict) or result.get('input_sha256') != _sha256_file(input_path):
                    raise AudioTranscriptionError('远端结果与本机输入的 SHA-256 不一致')
                runtime['worker_diagnostics'] = diagnostic_lines
                return result, runtime
            finally:
                if local_part.exists():
                    local_part.unlink()
                if created_remote:
                    cleanup_command = (
                        f'rm -rf -- {shlex.quote(remote_job_dir)} && '
                        f'test ! -e {shlex.quote(remote_job_dir)}')
                    try:
                        completed = subprocess.run(
                            ssh_command + [host, cleanup_command], text=True,
                            encoding='utf-8', errors='replace',
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
                            creationflags=_NO_WINDOW,
                        )
                        cleanup_verified = completed.returncode == 0
                    except Exception:
                        cleanup_verified = False
                    runtime['remote_cleanup_verified'] = cleanup_verified


class AudioTranscriptionManager:
    """Persistent job manager with private per-job inputs, checkpoints, and exports."""

    def __init__(self, root: str | Path, *, max_upload_bytes: int = AUDIO_DEFAULT_MAX_UPLOAD_BYTES,
                 runner_factory: Callable[[], RemoteAudioRunner] | None = None,
                 translator_factory: Callable[[], AcademicTranslationClient] | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self.max_upload_bytes = int(max_upload_bytes)
        self._runner_factory = runner_factory or (lambda: RemoteAudioRunner())
        self._translator_factory = translator_factory or (lambda: AcademicTranslationClient())
        self._lock = threading.RLock()
        self._pipeline_lock = threading.Lock()
        self._active: set[str] = set()
        self._mark_stale_jobs_interrupted()

    def _mark_stale_jobs_interrupted(self) -> None:
        for path in self.root.glob('*/manifest.json'):
            try:
                manifest = json.loads(path.read_text(encoding='utf-8'))
                if manifest.get('status') not in {'running'}:
                    continue
                manifest.update(
                    status='interrupted', stage='interrupted', updated_at=_utc_now(),
                    error='服务重启导致任务中断；可点击重试并复用已完成的检查点。',
                )
                _atomic_json(path, manifest)
            except Exception:
                continue

    def config(self) -> dict:
        runner = self._runner_factory()
        translator = self._translator_factory()
        return {
            'privacy_mode': 'encrypted_ssh_ephemeral_remote_audio',
            'supported_extensions': sorted(AUDIO_SUPPORTED_EXTENSIONS),
            'max_upload_bytes': self.max_upload_bytes,
            'speaker_labels': 'anonymous_only',
            'identity_inference': False,
            'exports': ['json', 'txt', 'srt', 'vtt', 'zip'],
            'transcription_service': runner.config(),
            'translation_service': translator.health(),
            'job_storage': 'data/audio_jobs (gitignored, local only)',
            'raw_audio_policy': 'local original + encrypted remote staging deleted after verified copy',
        }

    def create_job(self, filename: str, content: bytes, options: dict | None,
                   start: bool = True) -> dict:
        from io import BytesIO
        return self.create_job_from_stream(
            filename, BytesIO(content), len(content), options, start=start)

    def create_job_from_stream(self, filename: str, stream: BinaryIO, content_length: int,
                               options: dict | None, start: bool = True) -> dict:
        filename = _safe_filename(filename)
        extension = Path(filename).suffix.casefold()
        if extension not in AUDIO_SUPPORTED_EXTENSIONS:
            raise AudioTranscriptionError('当前不支持该音频或视频格式')
        if content_length <= 0:
            raise AudioTranscriptionError('上传文件为空')
        if content_length > self.max_upload_bytes:
            raise AudioTranscriptionError('上传文件超过语音模块大小限制')
        normalized_options = normalize_audio_options(options)
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(mode=0o700)
        input_name = f'source{extension}'
        input_path = job_dir / input_name
        temporary = input_path.with_suffix(input_path.suffix + '.part')
        digest = hashlib.sha256()
        written = 0
        try:
            with temporary.open('xb') as handle:
                while written < content_length:
                    block = stream.read(min(1024 * 1024, content_length - written))
                    if not block:
                        break
                    written += len(block)
                    digest.update(block)
                    handle.write(block)
            if written != content_length:
                raise AudioTranscriptionError('上传连接提前结束，文件未完整保存')
            os.replace(temporary, input_path)
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        manifest = {
            'schema_version': 1,
            'job_id': job_id,
            'status': 'queued',
            'stage': 'queued',
            'stage_detail': '等待语音处理资源',
            'created_at': _utc_now(),
            'updated_at': _utc_now(),
            'original_filename': filename,
            'input_filename': input_name,
            'input_bytes': written,
            'input_sha256': digest.hexdigest(),
            'options': normalized_options,
            'models': {
                'asr': 'Systran/faster-whisper-medium',
                'diarization': 'pyannote/speaker-diarization-community-1',
                'translation': self._translator_factory().model if normalized_options['translate'] else None,
            },
            'progress': {'percent': 0, 'stage': 'queued'},
            'warnings': [
                '说话人标签是匿名聚类结果，不代表真实身份；重叠语音、噪声和短发言可能导致误分。',
                '音频经 SSH 加密暂存到自动选择的校内主机，结果校验复制回本机后删除远端任务目录。',
            ],
            'security': {
                'speaker_identity_inference': False,
                'voice_attribute_inference': False,
                'remote_transfer': 'ssh',
                'remote_retention': 'delete_after_verified_copy',
            },
            'runtime': {},
            'outputs': {},
            'audit': {},
            'error': None,
        }
        self._write_manifest(job_id, manifest)
        if start:
            self._start(job_id)
        return self._public_manifest(manifest)

    def retry_job(self, job_id: str) -> dict:
        manifest = self._read_manifest(job_id)
        if manifest.get('status') not in {'failed', 'interrupted'}:
            raise AudioTranscriptionError('只有失败或中断的任务可以重试')
        manifest.update(
            status='queued', stage='queued', stage_detail='等待重试',
            updated_at=_utc_now(), error=None,
        )
        self._write_manifest(job_id, manifest)
        self._start(job_id)
        return self._public_manifest(manifest)

    def translate_job(self, job_id: str, options: dict | None = None,
                      start: bool = True) -> dict:
        """Add translation to a completed transcript without rerunning audio models."""
        manifest = self._read_manifest(job_id)
        if manifest.get('status') != 'completed':
            raise AudioTranscriptionError('只有已完成的纯转录任务可以追加翻译')
        if (manifest.get('options') or {}).get('translate'):
            raise AudioTranscriptionError('该任务已包含翻译输出')
        job_dir = self._job_dir(job_id)
        if self._load_cached_transcript(job_dir, manifest.get('input_sha256') or '') is None:
            raise AudioTranscriptionError('转录检查点缺失或输入 SHA-256 不一致')
        merged_options = dict(manifest.get('options') or {})
        if isinstance(options, dict):
            merged_options.update(options)
        merged_options['translate'] = True
        manifest['options'] = normalize_audio_options(merged_options)
        manifest.setdefault('models', {})['translation'] = self._translator_factory().model
        manifest.update(
            status='queued', stage='queued', stage_detail='等待追加逐轮翻译',
            updated_at=_utc_now(), error=None,
        )
        manifest['progress'] = {'stage': 'queued', 'percent': 87}
        self._write_manifest(job_id, manifest)
        if start:
            self._start(job_id)
        return self._public_manifest(manifest)

    def list_jobs(self) -> list[dict]:
        rows = []
        for path in self.root.glob('*/manifest.json'):
            try:
                rows.append(self._public_manifest(json.loads(path.read_text(encoding='utf-8'))))
            except Exception:
                continue
        return sorted(rows, key=lambda item: item.get('created_at', ''), reverse=True)[:30]

    def get_job(self, job_id: str) -> dict:
        return self._public_manifest(self._read_manifest(job_id))

    def view_result(self, job_id: str) -> dict:
        """Return a compact, browser-safe transcript view for one local job.

        Running and failed jobs still return their public manifest so the view
        page can show progress or an actionable error.  Completed jobs expose
        turn-level text and timing, while word probabilities, raw diarization
        segments, local paths, and private diagnostics remain in the auditable
        JSON download rather than the browser payload.
        """
        manifest = self._read_manifest(job_id)
        response = {'job': self._public_manifest(manifest), 'transcript': None}
        if manifest.get('status') != 'completed':
            return response
        transcript_path = self._job_dir(job_id) / 'transcript.json'
        try:
            payload = json.loads(transcript_path.read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise AudioTranscriptionError('转录查看文件缺失或损坏；请使用检查点重试任务') from exc
        if not isinstance(payload, dict) or payload.get('input_sha256') != manifest.get('input_sha256'):
            raise AudioTranscriptionError('转录查看文件与原始音频校验值不一致')
        turns = []
        for index, turn in enumerate(payload.get('turns') or []):
            if not isinstance(turn, dict):
                continue
            row = {
                'turn_id': str(turn.get('turn_id') or f'turn:{index:06d}'),
                'start': float(turn.get('start') or 0),
                'end': float(turn.get('end') or turn.get('start') or 0),
                'speaker': str(turn.get('speaker') or 'UNKNOWN'),
                'text': str(turn.get('text') or ''),
            }
            if 'translated_text' in turn:
                row['translated_text'] = str(turn.get('translated_text') or '')
            turns.append(row)
        response['transcript'] = {
            key: payload.get(key) for key in (
                'schema_version', 'language', 'language_probability',
                'duration_seconds', 'speaker_count', 'speakers', 'created_at',
                'models', 'package_versions', 'parameters', 'audit',
            )
        }
        response['transcript']['turns'] = turns
        return response

    def output_path(self, job_id: str, kind: str = 'bundle') -> tuple[Path, str, str]:
        if not _OUTPUT_KIND_RE.fullmatch(kind or ''):
            raise AudioTranscriptionError('输出格式无效')
        manifest = self._read_manifest(job_id)
        if manifest.get('status') != 'completed':
            raise AudioTranscriptionError('任务尚未完成，不能下载')
        output = (manifest.get('outputs') or {}).get(kind)
        if not isinstance(output, dict):
            raise AudioTranscriptionError('该输出格式不存在')
        path = self._job_dir(job_id) / str(output.get('filename') or '')
        if path.parent != self._job_dir(job_id) or not path.is_file():
            raise AudioTranscriptionError('输出文件不存在')
        mime = output.get('content_type') or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        return path, str(output.get('download_name') or path.name), mime

    def delete_job(self, job_id: str) -> None:
        job_dir = self._job_dir(job_id)
        with self._lock:
            if job_id in self._active:
                raise AudioTranscriptionError('运行中的任务不能删除')
        if not job_dir.is_dir():
            raise AudioTranscriptionError('任务不存在')
        shutil.rmtree(job_dir)

    def run_job_sync(self, job_id: str) -> None:
        self._run(job_id)

    def _start(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                raise AudioTranscriptionError('任务已在运行')
            self._active.add(job_id)
        threading.Thread(
            target=self._run, args=(job_id,), daemon=True,
            name=f'audio-transcription-{job_id[:8]}',
        ).start()

    def _set_progress(self, job_id: str, stage: str, percent: float, detail: str) -> None:
        manifest = self._read_manifest(job_id)
        manifest.update(stage=stage, stage_detail=detail, updated_at=_utc_now())
        manifest['progress'] = {'stage': stage, 'percent': max(0, min(100, round(percent, 1)))}
        self._write_manifest(job_id, manifest)

    def _load_cached_transcript(self, job_dir: Path, input_sha256: str) -> dict | None:
        path = job_dir / 'transcript.json'
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) and payload.get('input_sha256') == input_sha256 else None

    @staticmethod
    def _load_translation_checkpoint(path: Path) -> dict[str, str]:
        restored: dict[str, str] = {}
        if not path.is_file():
            return restored
        try:
            rows = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return restored
        for row in rows:
            try:
                record = json.loads(row)
                source_hash = record.get('source_sha256')
                translated = record.get('translated_text')
                if isinstance(source_hash, str) and isinstance(translated, str) and translated.strip():
                    restored[source_hash] = translated
            except Exception:
                continue
        return restored

    def _translate(self, job_id: str, job_dir: Path, result: dict, options: dict) -> int:
        detected_code = str(result.get('language') or '').casefold() or None
        if _same_language(detected_code, options['target_language']):
            for turn in result.get('turns') or []:
                turn['translated_text'] = str(turn.get('text') or '')
            return len(result.get('turns') or [])
        checkpoint_path = job_dir / 'audio_translations.jsonl'
        restored = self._load_translation_checkpoint(checkpoint_path)
        units: list[TranslationUnit] = []
        turn_by_unit: dict[str, dict] = {}
        for index, turn in enumerate(result.get('turns') or []):
            source_hash = _translation_hash(turn)
            cached = restored.get(source_hash)
            if cached:
                turn['translated_text'] = cached
                continue
            text = str(turn.get('text') or '').strip()
            if not text:
                turn['translated_text'] = ''
                continue
            unit_id = f'turn:{index:06d}'
            unit = TranslationUnit(
                unit_id=unit_id, part_name='audio', paragraph_start=index,
                paragraph_end=index + 1, paragraph_xml=text,
                segments=[Segment(segment_id='0', text=text)],
            )
            units.append(unit)
            turn_by_unit[unit_id] = turn
        completed_before = len(result.get('turns') or []) - len(units)
        if not units:
            return completed_before
        client = self._translator_factory()
        health = client.health()
        if not health.get('available'):
            raise AudioTranscriptionError(
                '转录与说话人区分已完成，但论文翻译模型未连接；启动模型后点击重试即可复用转录结果')
        translation_options = {
            'source_language': _language_name(detected_code),
            'target_language': options['target_language'],
            'domain': options['domain'],
            'glossary': options.get('glossary') or [],
        }

        def checkpoint(record: dict) -> None:
            with checkpoint_path.open('a', encoding='utf-8') as handle:
                for unit_id in record.get('unit_ids') or []:
                    unit = next(item for item in units if item.unit_id == unit_id)
                    turn = turn_by_unit[unit_id]
                    translated = unit.translations.get('0')
                    if not translated:
                        continue
                    handle.write(json.dumps({
                        'unit_id': unit_id,
                        'source_sha256': _translation_hash(turn),
                        'translated_text': translated,
                        'completed_at': _utc_now(),
                    }, ensure_ascii=False) + '\n')

        client.translate_units(
            units, translation_options,
            progress=lambda done, total: self._set_progress(
                job_id, 'translating', 88 + (done / max(1, total)) * 9,
                f'正在翻译说话人轮次 {completed_before + done} / {completed_before + total}'),
            checkpoint=checkpoint,
        )
        for unit in units:
            turn_by_unit[unit.unit_id]['translated_text'] = unit.translations['0']
        return completed_before

    def _write_exports(self, job_dir: Path, original_filename: str, result: dict,
                       translated: bool) -> dict[str, dict]:
        stem = re.sub(r'[^A-Za-z0-9._-]+', '_', Path(original_filename).stem).strip('._') or 'audio'
        files: dict[str, tuple[str, str, str]] = {
            'json': ('transcript.json', f'{stem}_transcript.json', 'application/json'),
            'txt': ('transcript.txt', f'{stem}_transcript.txt', 'text/plain; charset=utf-8'),
            'srt': ('transcript.srt', f'{stem}_transcript.srt', 'application/x-subrip'),
            'vtt': ('transcript.vtt', f'{stem}_transcript.vtt', 'text/vtt; charset=utf-8'),
        }
        _atomic_json(job_dir / 'transcript.json', result)
        _atomic_text(job_dir / 'transcript.txt', render_plain_text(result))
        _atomic_text(job_dir / 'transcript.srt', render_srt(result))
        _atomic_text(job_dir / 'transcript.vtt', render_vtt(result))
        if translated:
            translated_files = {
                'translated_txt': ('translated.txt', f'{stem}_translated.txt', 'text/plain; charset=utf-8'),
                'translated_srt': ('translated.srt', f'{stem}_translated.srt', 'application/x-subrip'),
                'translated_vtt': ('translated.vtt', f'{stem}_translated.vtt', 'text/vtt; charset=utf-8'),
                'bilingual_txt': ('bilingual.txt', f'{stem}_bilingual.txt', 'text/plain; charset=utf-8'),
                'bilingual_srt': ('bilingual.srt', f'{stem}_bilingual.srt', 'application/x-subrip'),
                'bilingual_vtt': ('bilingual.vtt', f'{stem}_bilingual.vtt', 'text/vtt; charset=utf-8'),
            }
            files.update(translated_files)
            _atomic_text(job_dir / 'translated.txt', render_plain_text(result, translated=True))
            _atomic_text(job_dir / 'translated.srt', render_srt(result, translated=True))
            _atomic_text(job_dir / 'translated.vtt', render_vtt(result, translated=True))
            _atomic_text(job_dir / 'bilingual.txt', render_plain_text(result, bilingual=True))
            _atomic_text(job_dir / 'bilingual.srt', render_srt(result, bilingual=True))
            _atomic_text(job_dir / 'bilingual.vtt', render_vtt(result, bilingual=True))
        bundle_filename = 'audio_transcription_bundle.zip'
        bundle_download = f'{stem}_transcription_bundle.zip'
        bundle_temp = job_dir / (bundle_filename + '.tmp')
        with zipfile.ZipFile(bundle_temp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, download_name, _content_type in files.values():
                archive.write(job_dir / filename, arcname=download_name)
        os.replace(bundle_temp, job_dir / bundle_filename)
        files['bundle'] = (bundle_filename, bundle_download, 'application/zip')
        return {
            kind: {
                'filename': filename,
                'download_name': download_name,
                'content_type': content_type,
                'bytes': (job_dir / filename).stat().st_size,
                'sha256': _sha256_file(job_dir / filename),
            }
            for kind, (filename, download_name, content_type) in files.items()
        }

    def _run(self, job_id: str) -> None:
        try:
            with self._lock:
                self._active.add(job_id)
            with self._pipeline_lock:
                manifest = self._read_manifest(job_id)
                manifest.update(
                    status='running', stage='starting', stage_detail='准备私有任务目录',
                    started_at=_utc_now(), updated_at=_utc_now(), error=None,
                )
                manifest['progress'] = {'stage': 'starting', 'percent': 1}
                self._write_manifest(job_id, manifest)
                job_dir = self._job_dir(job_id)
                input_path = job_dir / manifest['input_filename']
                options = manifest['options']
                result = self._load_cached_transcript(job_dir, manifest['input_sha256'])
                resumed_transcript = result is not None
                runtime = manifest.get('runtime') or {}
                if result is None:
                    runner = self._runner_factory()
                    result, runtime = runner.transcribe(
                        job_id=job_id, input_path=input_path, job_dir=job_dir,
                        options=options,
                        progress=lambda stage, percent, detail: self._set_progress(
                            job_id, stage, percent, detail),
                    )
                    _atomic_json(job_dir / 'transcript.json', result)
                else:
                    self._set_progress(job_id, 'resuming', 87, '已复用通过 SHA-256 校验的转录结果')
                translated = False
                resumed_translations = 0
                if options.get('translate'):
                    self._set_progress(job_id, 'translating', 88, '正在准备保持时间轴一致的逐轮翻译')
                    resumed_translations = self._translate(job_id, job_dir, result, options)
                    translated = True
                self._set_progress(job_id, 'exporting', 98, '正在生成 TXT、JSON、SRT、VTT 与 ZIP')
                outputs = self._write_exports(
                    job_dir, manifest['original_filename'], result, translated)
                final = self._read_manifest(job_id)
                remote_cleanup_verified = bool(runtime.get('remote_cleanup_verified'))
                warnings = list(final.get('warnings') or [])
                if not resumed_transcript and not remote_cleanup_verified:
                    warnings.append('未能确认远端临时目录已删除；请检查远端任务目录。')
                final.update(
                    status='completed', stage='completed', stage_detail='全部输出已完成',
                    completed_at=_utc_now(), updated_at=_utc_now(), error=None,
                    runtime=runtime, outputs=outputs, warnings=warnings,
                    detected_language=result.get('language'),
                    duration_seconds=result.get('duration_seconds'),
                    speaker_count=result.get('speaker_count'),
                    audit={
                        'input_sha256_verified_by_worker': result.get('input_sha256') == manifest['input_sha256'],
                        'remote_cleanup_verified': remote_cleanup_verified or resumed_transcript,
                        'resumed_transcript': resumed_transcript,
                        'resumed_translation_turns': resumed_translations,
                        'word_count': (result.get('audit') or {}).get('word_count'),
                        'turn_count': len(result.get('turns') or []),
                        'timestamps_preserved_across_exports': True,
                        'speaker_identity_inference': False,
                    },
                )
                final['progress'] = {'stage': 'completed', 'percent': 100}
                self._write_manifest(job_id, final)
        except Exception as exc:
            try:
                diagnostic_path = self._job_dir(job_id) / 'diagnostic.log'
                _atomic_text(diagnostic_path, traceback.format_exc())
                manifest = self._read_manifest(job_id)
                manifest.update(
                    status='failed', stage='failed', stage_detail='任务失败',
                    failed_at=_utc_now(), updated_at=_utc_now(),
                    error=str(exc) if isinstance(exc, AudioTranscriptionError)
                    else '语音任务发生内部错误；原文件与已有检查点均已保留',
                )
                self._write_manifest(job_id, manifest)
            except Exception:
                pass
        finally:
            with self._lock:
                self._active.discard(job_id)

    def _job_dir(self, job_id: str) -> Path:
        if not _JOB_ID_RE.fullmatch(job_id or ''):
            raise AudioTranscriptionError('任务编号无效')
        path = (self.root / job_id).resolve()
        if path.parent != self.root:
            raise AudioTranscriptionError('任务路径无效')
        return path

    def _read_manifest(self, job_id: str) -> dict:
        try:
            return json.loads((self._job_dir(job_id) / 'manifest.json').read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise AudioTranscriptionError('任务不存在') from exc

    def _write_manifest(self, job_id: str, manifest: dict) -> None:
        path = self._job_dir(job_id) / 'manifest.json'
        with self._lock:
            _atomic_json(path, manifest)

    @staticmethod
    def _public_manifest(manifest: dict) -> dict:
        allowed = {
            'schema_version', 'job_id', 'status', 'stage', 'stage_detail',
            'created_at', 'updated_at', 'started_at', 'completed_at', 'failed_at',
            'original_filename', 'input_bytes', 'input_sha256', 'options', 'models',
            'progress', 'warnings', 'security', 'runtime', 'outputs', 'audit', 'error',
            'detected_language', 'duration_seconds', 'speaker_count',
        }
        public = {key: value for key, value in manifest.items() if key in allowed}
        runtime = public.get('runtime')
        if isinstance(runtime, dict):
            public['runtime'] = {
                key: runtime[key] for key in ('host', 'gpu_index', 'selected_at', 'remote_cleanup_verified')
                if key in runtime
            }
        return public
