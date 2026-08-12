#!/usr/bin/env python3
"""Synchronize the public YueDu FM RSS archive into the local private library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.yuedu_fm_service import DEFAULT_FEED_URL, YueduFMError, YueduFMManager


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同步悦读FM标题、文字、封面和音频到 data/yuedu_fm/（支持断点续传）")
    parser.add_argument("--metadata-only", action="store_true",
                        help="同步 RSS、标题、文字和全部封面，不下载 MP3")
    parser.add_argument("--limit", type=int, default=None,
                        help="仅处理前 N 集资源；RSS 目录仍完整保存（用于 smoke test）")
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "yuedu_fm")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit 不能小于 0")

    manager = YueduFMManager(args.data_dir, feed_url=args.feed_url)
    try:
        result = manager.sync(download_audio=not args.metadata_only, limit=args.limit)
    except YueduFMError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
