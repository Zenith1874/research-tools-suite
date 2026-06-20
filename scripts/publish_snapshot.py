#!/usr/bin/env python3
"""
生成数据库一致性快照 → 压缩 → 上传到 GitHub Release "data-latest"（滚动更新，覆盖旧资产）。

用法：
  python scripts/publish_snapshot.py
依赖：gh CLI 已登录（凭据在用户 keyring，计划任务也能用）。
"""
import os, sys, gzip, shutil, subprocess, sqlite3
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'pboc_data.db')
SNAP = os.path.join(ROOT, 'data_snapshot.db')
GZ = SNAP + '.gz'
REPO = 'Zenith1874/research-tools-suite'
TAG = 'data-latest'
GH_CANDIDATES = [
    r'C:\Program Files\GitHub CLI\gh.exe',
    'gh',
]


def gh():
    for c in GH_CANDIDATES:
        if c == 'gh' or os.path.exists(c):
            return c
    return 'gh'


def main():
    for p in (SNAP, GZ):
        if os.path.exists(p):
            os.remove(p)
    print('生成一致性快照 (VACUUM INTO)…', flush=True)
    conn = sqlite3.connect(DB)
    conn.execute(f"VACUUM INTO '{SNAP}'")
    conn.close()
    print('压缩…', flush=True)
    with open(SNAP, 'rb') as fi, gzip.open(GZ, 'wb', compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)
    size_mb = os.path.getsize(GZ) // 1048576
    print(f'压缩后 {size_mb} MB', flush=True)

    g = gh()
    # release 存在则覆盖资产，否则新建
    exists = subprocess.run([g, 'release', 'view', TAG, '-R', REPO],
                            capture_output=True, text=True).returncode == 0
    notes = f'滚动数据快照（{date.today()}）。解压后改名 pboc_data.db 放到项目根目录。'
    if not exists:
        print('创建 release…', flush=True)
        subprocess.run([g, 'release', 'create', TAG, '-R', REPO,
                        '--title', '数据快照（滚动更新）', '--notes', notes,
                        f'{GZ}#pboc_data_snapshot.db.gz'], check=True)
    else:
        print('更新 release 资产…', flush=True)
        subprocess.run([g, 'release', 'upload', TAG, '-R', REPO,
                        f'{GZ}#pboc_data_snapshot.db.gz', '--clobber'], check=True)
        subprocess.run([g, 'release', 'edit', TAG, '-R', REPO, '--notes', notes], check=True)

    for p in (SNAP, GZ):
        if os.path.exists(p):
            os.remove(p)
    print(f'完成：已发布到 https://github.com/{REPO}/releases/tag/{TAG}')


if __name__ == '__main__':
    main()
