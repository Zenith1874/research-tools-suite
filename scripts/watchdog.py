#!/usr/bin/env python3
"""服务器看门狗：定时探测 /api/health，连续失败 N 次就杀掉并重启 server.py。

默认不随服务启动 —— 需要时手动运行 scripts/watchdog.bat，
或挂成 Windows 计划任务(开机/登录时启动，详见文件末尾说明)。

用法:
    python scripts/watchdog.py                 # 默认每 30s 探一次，连失 3 次重启
    python scripts/watchdog.py --interval 20 --fails 2 --port 5001
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'server.py')
LOGDIR = os.path.join(ROOT, 'logs')
os.makedirs(LOGDIR, exist_ok=True)
LOGFILE = os.path.join(LOGDIR, 'watchdog.log')


def log(msg):
    line = f'{datetime.now().isoformat()}  {msg}'
    print(line, flush=True)
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


def kill_server():
    """杀掉所有命令行含 server.py 的 python 进程(Windows / PowerShell)。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*server.py*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        subprocess.run(['powershell', '-NoProfile', '-Command', ps], cwd=ROOT, timeout=30,
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
    log('⚠️  连续探测失败 → 重启 server.py')
    kill_server()
    time.sleep(3)
    start_server()
    time.sleep(8)
    log('✅ 重启后健康' if healthy(port) else '❌ 重启后仍不健康(下一轮继续监控)')


# ── 论文翻译 SSH 隧道维护:模型状态文件在(远端模型应在跑)而本地隧道不通时自动重建 ──
TUNNEL_STATE = os.path.join(ROOT, 'data', 'translation_runtime.json')
TUNNEL_LOCAL_PORT = int(os.environ.get('TRANSLATION_LOCAL_PORT', '18001'))
TUNNEL_REMOTE_PORT = int(os.environ.get('TRANSLATION_REMOTE_PORT', '8000'))
_last_tunnel_attempt = 0.0


def tunnel_healthy(timeout=4):
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{TUNNEL_LOCAL_PORT}/v1/models', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_tunnel():
    """manage_translation_vllm start 会写状态文件、stop 会删;
    文件在 → 期望模型在线 → 隧道断了(如重启电脑后)就静默重建。60s 限频。"""
    global _last_tunnel_attempt
    if not os.path.exists(TUNNEL_STATE) or tunnel_healthy():
        return
    now = time.time()
    if now - _last_tunnel_attempt < 60:
        return
    _last_tunnel_attempt = now
    try:
        with open(TUNNEL_STATE, encoding='utf-8') as f:
            host = (json.load(f).get('host') or '').strip()
    except Exception:
        return
    if not host:
        return
    log(f'翻译隧道不通 → 重建 ssh -L {TUNNEL_LOCAL_PORT}→{host}:{TUNNEL_REMOTE_PORT}')
    try:
        subprocess.Popen(
            ['ssh', '-N', '-L', f'{TUNNEL_LOCAL_PORT}:127.0.0.1:{TUNNEL_REMOTE_PORT}',
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
    ap.add_argument('--port', type=int, default=5001)
    ap.add_argument('--start-if-down', action='store_true',
                    help='启动时若服务没在跑，直接拉起一个')
    args = ap.parse_args()

    log(f'看门狗启动：每 {args.interval}s 探测 /api/health，连失 {args.fails} 次重启(port={args.port})')
    if args.start_if_down and not healthy(args.port):
        log('启动时检测到服务未运行 → 先拉起')
        start_server()
        time.sleep(8)
    ensure_tunnel()   # 重启电脑后模型还在远端跑,但本地隧道会掉,登录即恢复

    consecutive = 0
    ticks = 0
    while True:
        if healthy(args.port):
            if consecutive:
                log('恢复健康')
            consecutive = 0
        else:
            consecutive += 1
            log(f'health 失败 {consecutive}/{args.fails}')
            if consecutive >= args.fails:
                restart(args.port)
                consecutive = 0
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
