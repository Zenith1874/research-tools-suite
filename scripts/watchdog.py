#!/usr/bin/env python3
"""服务器看门狗：定时探测 /api/health，连续失败 N 次就杀掉并重启 server.py。

默认只监控本机服务，不会自动连接校内 SSH 主机。论文翻译隧道需要时由用户
显式运行 scripts/start_translation_tunnel.sh；只有明确传入 --auto-tunnel 才会
启用看门狗的自动隧道恢复。

默认不随服务启动 —— 需要时手动运行 scripts/watchdog.bat，
或挂成 Windows 计划任务(开机/登录时启动，详见文件末尾说明)。

用法:
    python scripts/watchdog.py                 # 默认每 30s 探一次，连失 3 次重启
    python scripts/watchdog.py --interval 20 --fails 2 --port 5001
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'server.py')
LOGDIR = os.path.join(ROOT, 'logs')
os.makedirs(LOGDIR, exist_ok=True)
LOGFILE = os.path.join(LOGDIR, 'watchdog.log')
TRANSLATION_JOBS = os.path.join(ROOT, 'data', 'translation_jobs')


def system_tool(name, relative_windows_path=None):
    """Resolve a required executable even when pythonw inherits a sparse PATH."""
    discovered = shutil.which(name)
    if discovered:
        return discovered
    if os.name == 'nt' and relative_windows_path:
        windows_root = os.environ.get('WINDIR') or os.environ.get('SystemRoot')
        if windows_root:
            candidate = os.path.join(windows_root, *relative_windows_path)
            if os.path.isfile(candidate):
                return candidate
    return name


def acquire_single_instance_lock(port, lock_port=None):
    """Hold a localhost socket so two watchdogs cannot restart each other.

    The returned socket must stay open for the lifetime of the watchdog.  A
    caller receiving ``None`` should exit because another instance owns the
    lock already.
    """
    if lock_port is None:
        lock_port = 45000 + (int(port) % 10000)
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        guard.bind(('127.0.0.1', lock_port))
        guard.listen(1)
    except OSError:
        guard.close()
        return None
    return guard


def port_accepting_connections(port, timeout=1):
    """Cheap liveness evidence independent of the HTTP request handler."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


def log(msg):
    line = f'{datetime.now().isoformat()}  {msg}'
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
        print(line.encode(encoding, errors='replace').decode(encoding), flush=True)
    try:
        with open(LOGFILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def healthy(port, timeout=6):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def fresh_running_translation_job(jobs_root=None, max_age_seconds=600, now=None):
    """Return a recently progressing translation job, if one exists.

    Model requests can briefly make the health endpoint time out.  A fresh
    on-disk manifest is independent evidence that the worker is alive, so the
    watchdog should not turn useful work into an interruption.  The finite
    window still permits recovery after a genuine process death.
    """
    root = jobs_root or TRANSLATION_JOBS
    current = now or datetime.now(timezone.utc)
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in names:
        manifest_path = os.path.join(root, name, 'manifest.json')
        try:
            with open(manifest_path, encoding='utf-8') as handle:
                manifest = json.load(handle)
            if manifest.get('status') != 'running':
                continue
            timestamp = manifest.get('updated_at') or manifest.get('started_at')
            updated = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = (current - updated.astimezone(timezone.utc)).total_seconds()
            if 0 <= age <= max_age_seconds:
                return {
                    'job_id': manifest.get('job_id') or name,
                    'age_seconds': round(age),
                    'progress': manifest.get('progress') or {},
                }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def kill_server():
    """杀掉所有命令行含 server.py 的 python 进程(Windows / PowerShell)。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*server.py*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        powershell = system_tool(
            'powershell.exe', ('System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'))
        subprocess.run([powershell, '-NoProfile', '-Command', ps], cwd=ROOT, timeout=30,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as e:
        log(f'kill_server 出错: {e}')


MAX_LOG_BYTES = 5 * 1024 * 1024   # 单个日志超过 5MB 就轮转成 .1(覆盖旧 .1)


def rotate_log(path):
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            bak = path + '.1'
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(path, bak)
            log(f'日志已轮转: {os.path.basename(path)} -> .1')
    except Exception as e:
        log(f'rotate_log({path}) 出错: {e}')


def start_server():
    """后台启动 server.py，脱离看门狗进程，stdout/stderr 续写到日志(启动前轮转)。"""
    try:
        for name in ('server.stdout.log', 'server.stderr.log'):
            rotate_log(os.path.join(ROOT, name))
        rotate_log(LOGFILE)
        subprocess.Popen(
            [sys.executable, SERVER], cwd=ROOT,
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            | getattr(subprocess, 'DETACHED_PROCESS', 0),
            stdout=open(os.path.join(ROOT, 'server.stdout.log'), 'a', encoding='utf-8'),
            stderr=open(os.path.join(ROOT, 'server.stderr.log'), 'a', encoding='utf-8'),
        )
    except Exception as e:
        log(f'start_server 出错: {e}')


def restart(port):
    active = fresh_running_translation_job()
    if active:
        progress = active.get('progress') or {}
        log('翻译任务仍在推进，延后重启 server.py：'
            f"job={active['job_id']} age={active['age_seconds']}s "
            f"progress={progress.get('translated_units', 0)}/"
            f"{progress.get('total_units', 0)}")
        return
    log('⚠️  连续探测失败 → 重启 server.py')
    kill_server()
    time.sleep(3)
    start_server()
    time.sleep(8)
    log('✅ 重启后健康' if healthy(port) else '❌ 重启后仍不健康(下一轮继续监控)')


# ── 论文翻译 SSH 隧道维护（仅在显式 --auto-tunnel 时启用） ──
TUNNEL_STATE = os.path.join(ROOT, 'data', 'translation_runtime.json')
TUNNEL_LOCAL_PORT = int(os.environ.get('TRANSLATION_LOCAL_PORT', '18001'))
TUNNEL_REMOTE_PORT = int(os.environ.get('TRANSLATION_REMOTE_PORT', '8000'))
TUNNEL_RETRY_INITIAL_SECONDS = 60
TUNNEL_RETRY_MAX_SECONDS = 3600
_last_tunnel_attempt = 0.0
_tunnel_retry_count = 0


def tunnel_healthy(timeout=4):
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{TUNNEL_LOCAL_PORT}/v1/models', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_tunnel():
    """Optionally restore a tunnel, with an increasing cooldown after failures.

    This function is deliberately not called by default. A stale runtime state
    file is not proof that the remote model is still running or that repeated
    SSH logins are welcome. Normal operation uses the explicit, foreground
    ``scripts/start_translation_tunnel.sh`` command instead.
    """
    global _last_tunnel_attempt, _tunnel_retry_count
    if not os.path.exists(TUNNEL_STATE):
        _last_tunnel_attempt = 0.0
        _tunnel_retry_count = 0
        return
    if tunnel_healthy():
        _last_tunnel_attempt = 0.0
        _tunnel_retry_count = 0
        return
    now = time.time()
    cooldown = min(
        TUNNEL_RETRY_MAX_SECONDS,
        TUNNEL_RETRY_INITIAL_SECONDS * (2 ** min(_tunnel_retry_count, 6)),
    )
    if _last_tunnel_attempt and now - _last_tunnel_attempt < cooldown:
        return
    _last_tunnel_attempt = now
    _tunnel_retry_count += 1
    try:
        with open(TUNNEL_STATE, encoding='utf-8') as f:
            host = (json.load(f).get('host') or '').strip()
    except Exception:
        return
    if not host:
        return
    log(f'翻译隧道不通 → 重建 ssh -L {TUNNEL_LOCAL_PORT}→{host}:{TUNNEL_REMOTE_PORT}')
    try:
        ssh = system_tool('ssh.exe', ('System32', 'OpenSSH', 'ssh.exe'))
        subprocess.Popen(
            [ssh, '-N', '-L', f'{TUNNEL_LOCAL_PORT}:127.0.0.1:{TUNNEL_REMOTE_PORT}',
             '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=30',
             '-o', 'ServerAliveCountMax=3', '-o', 'ExitOnForwardFailure=yes', host],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            | getattr(subprocess, 'DETACHED_PROCESS', 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log(f'ensure_tunnel 出错: {e}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=int, default=30, help='探测间隔秒数(默认 30)')
    ap.add_argument('--fails', type=int, default=3, help='连续失败多少次才重启(默认 3)')
    ap.add_argument('--busy-fails', type=int, default=6,
                    help='端口仍监听但 health 超时时，连续失败多少次才重启(默认 6)')
    ap.add_argument('--port', type=int, default=5001)
    ap.add_argument('--start-if-down', action='store_true',
                    help='启动时若服务没在跑，直接拉起一个')
    ap.add_argument('--auto-tunnel', action='store_true',
                    help=('显式允许看门狗自动创建翻译 SSH 隧道；默认关闭，'
                          '通常应手动运行 scripts/start_translation_tunnel.sh'))
    args = ap.parse_args()

    instance_lock = acquire_single_instance_lock(args.port)
    if instance_lock is None:
        log(f'另一个看门狗已在运行，本实例退出(port={args.port})')
        return

    tunnel_mode = ('开启（显式 --auto-tunnel）' if args.auto_tunnel
                   else '关闭（默认，需手动启动隧道）')
    log(f'看门狗启动：每 {args.interval}s 探测 /api/health；'
        f'端口断开连失 {args.fails} 次、端口仍监听连失 {args.busy_fails} 次重启'
        f'(port={args.port})；翻译 SSH 隧道自动重连={tunnel_mode}')
    if args.start_if_down and not healthy(args.port):
        log('启动时检测到服务未运行 → 先拉起')
        start_server()
        time.sleep(8)
    if args.auto_tunnel:
        ensure_tunnel()

    consecutive = 0
    ticks = 0
    while True:
        if healthy(args.port):
            if consecutive:
                log('恢复健康')
            consecutive = 0
        else:
            consecutive += 1
            port_open = port_accepting_connections(args.port)
            failure_limit = args.busy_fails if port_open else args.fails
            detail = '，端口仍监听，按忙碌容忍窗口处理' if port_open else '，端口未监听'
            log(f'health 失败 {consecutive}/{failure_limit}{detail}')
            if consecutive >= failure_limit:
                restart(args.port)
                consecutive = 0
        if args.auto_tunnel:
            ensure_tunnel()
        ticks += 1
        if ticks % 120 == 0:          # 约每 40 分钟检查一次自身日志大小
            rotate_log(LOGFILE)       # server 日志被运行中进程占用，只在重启时轮转
        time.sleep(args.interval)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('看门狗手动停止')


# ── 挂成 Windows 计划任务(登录时自动启动、隐藏窗口) ─────────────────────────────
#   在 PowerShell 里跑一次(按需改路径):
#
#   $py  = "C:\Users\cui10\AppData\Local\Programs\Python\Python312\pythonw.exe"
#   $arg = "D:\claude\scripts\watchdog.py --start-if-down"
#   $act = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory "D:\claude"
#   $trg = New-ScheduledTaskTrigger -AtLogOn
#   Register-ScheduledTask -TaskName "ClaudeServerWatchdog" -Action $act -Trigger $trg -RunLevel Limited
#
#   取消:  Unregister-ScheduledTask -TaskName "ClaudeServerWatchdog" -Confirm:$false
