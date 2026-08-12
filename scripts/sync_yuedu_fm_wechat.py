#!/usr/bin/env python3
"""Import accessible YueDu FM WeChat articles into the private local library."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.yuedu_fm_service import html_to_text


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_SEED_FILE = ROOT / "tmp" / "sina_yuedu_link_targets.json"
SCHEMA_VERSION = 1
CHUNK_BYTES = 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_title(value: str) -> str:
    return re.sub(r"[\W_]+", "", (value or "").casefold())


def js_string(html: str, name: str) -> str:
    match = re.search(rf"var\s+{re.escape(name)}\s*=\s*'((?:\\'|[^'])*)'", html)
    if not match:
        match = re.search(rf'var\s+{re.escape(name)}\s*=\s*"((?:\\"|[^"])*)"', html)
    if not match:
        match = re.search(
            rf'var\s+{re.escape(name)}\s*=\s*htmlDecode\("((?:\\"|[^"])*)"\)', html
        )
    if not match:
        return ""
    return unquote(match.group(1).replace("\\'", "'").replace('\\"', '"'))


def js_number(html: str, name: str) -> int:
    match = re.search(rf"var\s+{re.escape(name)}\s*=\s*\"?(\d+)\"?", html)
    return int(match.group(1)) if match else 0


def stable_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    if parsed.netloc.endswith("mp.weixin.qq.com") and parsed.path.startswith("/s/"):
        return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))
    if parsed.netloc.endswith("mp.weixin.qq.com") and parsed.path == "/s":
        keep = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key in {"__biz", "mid", "idx", "sn", "chksm", "scene"}:
                keep.append((key, value))
        query = "&".join(f"{quote(k)}={quote(v)}" for k, v in keep)
        return urlunsplit(("https", parsed.netloc, parsed.path, query, ""))
    return url


def article_id(url: str) -> str:
    return hashlib.sha256(stable_url(url).encode("utf-8")).hexdigest()[:24]


def seed_urls(seed_file: Path, explicit_urls: list[str]) -> list[str]:
    urls = [stable_url(url) for url in explicit_urls]
    if seed_file.is_file():
        data = json.loads(seed_file.read_text(encoding="utf-8"))
        for row in data.get("links", []):
            target = row.get("target_url", "")
            if row.get("status") == "wechat_article" and target:
                urls.append(stable_url(target))
    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def extract_article(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#js_content")
    title = js_string(html, "msg_title") or (soup.title.get_text(strip=True) if soup.title else "")
    nickname = js_string(html, "nickname") or (
        soup.select_one("#js_name").get_text(strip=True) if soup.select_one("#js_name") else ""
    )
    ct = js_number(html, "ct")
    published_at = datetime.fromtimestamp(ct, timezone.utc).isoformat() if ct else ""
    content_html = str(content) if content else ""
    content_text = html_to_text(content_html)
    audio_nodes = soup.select("mp-common-mpaudio, mpvoice")
    audio = {}
    if audio_nodes:
        node = audio_nodes[0]
        media_id = unquote(node.get("voice_encode_fileid", "") or node.get("voice_id", ""))
        play_ms = int(node.get("play_length") or 0)
        audio = {
            "media_id": media_id,
            "program_title": node.get("name", "") or title,
            "program_author": node.get("author", "") or nickname,
            "duration_seconds": round(play_ms / 1000) if play_ms else 0,
            "source_url": (
                f"https://res.wx.qq.com/voice/getvoice?mediaid={media_id}&voice_type=1"
                if media_id else ""
            ),
        }
    links = []
    images = []
    if content:
        for anchor in content.select("a[href]"):
            href = stable_url(urljoin(url, anchor.get("href", "")))
            if "mp.weixin.qq.com/s" in href and href != stable_url(url):
                links.append(href)
        for img in content.select("img"):
            src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith(("http://", "https://")):
                images.append(src)
    return {
        "article_id": article_id(url),
        "source": "wechat",
        "source_url": stable_url(url),
        "page_title": title,
        "title": audio.get("program_title") or title,
        "account": nickname,
        "published_at": published_at,
        "article_ct": ct,
        "content_html": content_html,
        "content_text": content_text,
        "body_text_chars": len(content_text),
        "audio": audio,
        "image_urls": list(dict.fromkeys(images)),
        "discovered_article_urls": list(dict.fromkeys(links)),
    }


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=(10, 45))
    response.raise_for_status()
    response.encoding = "utf-8"
    text = response.text
    if "请在微信客户端打开链接" in text or "环境异常" in text or "<title>验证</title>" in text:
        raise RuntimeError("微信返回验证页或客户端限定页")
    if "js_content" not in text and "msg_title" not in text:
        raise RuntimeError("页面不含公众号文章正文标记")
    return text


def media_extension(url: str, content_type: str, fallback: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,6}", suffix or ""):
        return suffix
    return mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip()) or fallback


def valid_audio(path: Path) -> bool:
    with path.open("rb") as handle:
        prefix = handle.read(16)
    return prefix.startswith(b"ID3") or prefix.startswith(b"ftyp") or prefix[4:12].startswith(b"ftyp")


def valid_image(path: Path) -> bool:
    with path.open("rb") as handle:
        prefix = handle.read(16)
    return (
        prefix.startswith(b"\xff\xd8\xff")
        or prefix.startswith(b"\x89PNG\r\n\x1a\n")
        or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP")
        or prefix.startswith(b"GIF8")
    )


def download(session: requests.Session, url: str, target: Path, *, kind: str) -> dict:
    if target.is_file() and target.stat().st_size:
        return {
            "downloaded": True,
            "actual_bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "signature_valid": valid_audio(target) if kind == "audio" else valid_image(target),
            "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    response = session.get(url, stream=True, timeout=(15, 120))
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    with part.open("wb") as handle:
        for chunk in response.iter_content(CHUNK_BYTES):
            if chunk:
                handle.write(chunk)
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target.replace(target.with_suffix(target.suffix + f".invalid-{stamp}"))
    os.replace(part, target)
    return {
        "downloaded": True,
        "actual_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "signature_valid": valid_audio(target) if kind == "audio" else valid_image(target),
        "content_type": content_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream",
    }


def to_episode(article: dict) -> dict:
    aid = article["article_id"]
    first_image = article.get("images", [{}])[0] if article.get("images") else {}
    audio = article.get("audio", {})
    return {
        "episode_id": aid,
        "source": "wechat",
        "position": 100000 + int(article.get("crawl_order", 0)),
        "guid": article["source_url"],
        "title": article.get("title") or article.get("page_title") or "",
        "subtitle": article.get("page_title", ""),
        "author": audio.get("program_author") or article.get("account") or "悦读FM",
        "published_at": article.get("published_at", ""),
        "duration_seconds": int(audio.get("duration_seconds") or 0),
        "explicit": "",
        "link": article["source_url"],
        "description_html": article.get("content_html", ""),
        "description_text": article.get("content_text", ""),
        "source_detail": {
            "kind": "wechat_article",
            "article_id": aid,
            "account": article.get("account", ""),
            "source_url": article["source_url"],
            "raw_html_relative_path": article.get("raw_html_relative_path", ""),
        },
        "audio": {
            "source_url": audio.get("source_url", ""),
            "content_type": audio.get("content_type", "audio/mp4"),
            "declared_bytes": 0,
            "actual_bytes": audio.get("actual_bytes", 0),
            "declared_size_matches": None,
            "signature_valid": audio.get("signature_valid"),
            "relative_path": audio.get("relative_path", f"wechat/audio/{aid}.m4a"),
            "downloaded": bool(audio.get("downloaded")),
            "downloaded_bytes": audio.get("actual_bytes", 0) if audio.get("downloaded") else 0,
            "sha256": audio.get("sha256", ""),
        },
        "image": {
            "source_url": first_image.get("source_url", ""),
            "actual_bytes": first_image.get("actual_bytes", 0),
            "signature_valid": first_image.get("signature_valid"),
            "relative_path": first_image.get("relative_path", ""),
            "downloaded": bool(first_image.get("downloaded")),
            "downloaded_bytes": first_image.get("actual_bytes", 0) if first_image.get("downloaded") else 0,
            "sha256": first_image.get("sha256", ""),
        },
    }


def build_combined(root_dir: Path, wechat_library: dict) -> dict:
    base_path = root_dir / "library.json"
    if not base_path.is_file():
        raise RuntimeError(f"缺少 RedCircle 主库：{base_path}")
    combined = deepcopy(json.loads(base_path.read_text(encoding="utf-8")))
    base_episodes = combined.get("episodes", [])
    base_keys = {
        (normalize_title(row.get("title", "")), int(row.get("duration_seconds") or 0))
        for row in base_episodes
    }
    base_hashes = {
        row.get("audio", {}).get("sha256", "")
        for row in base_episodes
        if row.get("audio", {}).get("sha256")
    }
    audit = []
    imported = []
    for article in wechat_library.get("articles", []):
        episode = to_episode(article)
        key = (normalize_title(episode.get("title", "")), int(episode.get("duration_seconds") or 0))
        audio_hash = episode.get("audio", {}).get("sha256", "")
        if key in base_keys:
            audit.append({"wechat_title": episode["title"], "action": "skip_exact_title_duration"})
            continue
        if audio_hash and audio_hash in base_hashes:
            audit.append({"wechat_title": episode["title"], "action": "skip_same_audio_sha256"})
            continue
        imported.append(episode)
        audit.append({"wechat_title": episode["title"], "action": "import"})
    combined["schema_version"] = max(int(combined.get("schema_version", 1)), 2)
    combined["combined_generated_at"] = utc_now()
    combined["source_libraries"] = {"redcircle": "library.json", "wechat": "wechat/wechat_library.json"}
    combined["episodes"] = base_episodes + imported
    stats = combined.setdefault("stats", {})
    stats["episode_count"] = len(combined["episodes"])
    stats["redcircle_episode_count"] = len(base_episodes)
    stats["wechat_accessible_article_count"] = len(wechat_library.get("articles", []))
    stats["wechat_imported_episode_count"] = len(imported)
    stats["wechat_skipped_duplicate_count"] = len(wechat_library.get("articles", [])) - len(imported)
    stats["downloaded_audio_count"] = sum(1 for row in combined["episodes"] if row.get("audio", {}).get("downloaded"))
    stats["downloaded_image_count"] = sum(1 for row in combined["episodes"] if row.get("image", {}).get("downloaded"))
    stats["downloaded_audio_bytes"] = sum(
        int(row.get("audio", {}).get("downloaded_bytes") or 0) for row in combined["episodes"]
    )
    stats["downloaded_image_bytes"] = sum(
        int(row.get("image", {}).get("downloaded_bytes") or 0) for row in combined["episodes"]
    )
    return {"combined": combined, "audit": audit}


def sync(args: argparse.Namespace) -> dict:
    root_dir = args.data_dir
    wechat_dir = root_dir / "wechat"
    previous_library_path = wechat_dir / "wechat_library.json"
    previous_articles = {}
    if previous_library_path.is_file():
        try:
            previous_data = json.loads(previous_library_path.read_text(encoding="utf-8"))
            previous_articles = {
                row.get("article_id"): row for row in previous_data.get("articles", [])
                if row.get("article_id")
            }
        except (OSError, json.JSONDecodeError):
            previous_articles = {}
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://mp.weixin.qq.com/",
    })
    queue = seed_urls(args.seed_file, args.url)
    seen = set()
    articles = []
    errors = []
    index = 0
    while queue and (args.discover_limit is None or len(seen) < args.discover_limit):
        url = stable_url(queue.pop(0))
        if url in seen:
            continue
        seen.add(url)
        index += 1
        try:
            html = fetch_html(session, url)
            aid = article_id(url)
            raw_path = wechat_dir / "raw" / "articles" / f"{aid}.html"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(html, encoding="utf-8")
            article = extract_article(url, html)
            article["crawl_order"] = index
            article["fetched_at"] = utc_now()
            article["raw_html_relative_path"] = str(raw_path.relative_to(root_dir)).replace(os.sep, "/")
            old_article = previous_articles.get(aid, {})
            old_audio = old_article.get("audio", {})
            if old_audio.get("downloaded") and old_audio.get("relative_path"):
                article.setdefault("audio", {}).update({
                    key: old_audio.get(key)
                    for key in (
                        "downloaded", "actual_bytes", "sha256", "signature_valid",
                        "content_type", "relative_path"
                    )
                    if old_audio.get(key) is not None
                })
            if not article.get("audio", {}).get("media_id"):
                errors.append({"url": url, "error": "未发现微信音频组件"})
            if args.discover_related:
                for next_url in article.get("discovered_article_urls", []):
                    if next_url not in seen and next_url not in queue:
                        queue.append(next_url)
            if not args.metadata_only:
                audio = article.get("audio", {})
                if audio.get("source_url"):
                    audio_target = wechat_dir / "audio" / f"{aid}.m4a"
                    result = download(session, audio["source_url"], audio_target, kind="audio")
                    audio.update(result)
                    audio["relative_path"] = str(audio_target.relative_to(root_dir)).replace(os.sep, "/")
                image_rows = []
                for image_index, image_url in enumerate(article.get("image_urls", [])[: args.max_images]):
                    try:
                        extension = media_extension(image_url, "", ".jpg")
                        image_target = wechat_dir / "images" / f"{aid}_{image_index}{extension}"
                        result = download(session, image_url, image_target, kind="image")
                        image_rows.append({
                            "source_url": image_url,
                            "relative_path": str(image_target.relative_to(root_dir)).replace(os.sep, "/"),
                            **result,
                        })
                    except Exception as exc:
                        errors.append({"url": url, "image_url": image_url, "error": str(exc)[:300]})
                article["images"] = image_rows
            else:
                article["images"] = old_article.get("images", [])
            atomic_json(wechat_dir / "metadata" / f"{aid}.json", article)
            articles.append(article)
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)[:500]})
        time.sleep(max(0.0, args.pause_seconds))
    library = {
        "schema_version": SCHEMA_VERSION,
        "source": "wechat",
        "generated_at": utc_now(),
        "seed_file": str(args.seed_file),
        "metadata_only": args.metadata_only,
        "discover_related": args.discover_related,
        "stats": {
            "seed_count": len(seed_urls(args.seed_file, args.url)),
            "visited_count": len(seen),
            "article_count": len(articles),
            "audio_count": sum(1 for row in articles if row.get("audio", {}).get("media_id")),
            "downloaded_audio_count": sum(1 for row in articles if row.get("audio", {}).get("downloaded")),
            "downloaded_image_count": sum(len(row.get("images", [])) for row in articles),
            "error_count": len(errors),
        },
        "articles": articles,
        "errors": errors,
    }
    atomic_json(wechat_dir / "wechat_library.json", library)
    merged = build_combined(root_dir, library)
    atomic_json(root_dir / "library_combined.json", merged["combined"])
    atomic_json(wechat_dir / "merge_audit.json", {"generated_at": utc_now(), "rows": merged["audit"]})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    atomic_json(wechat_dir / "manifests" / f"wechat_library_{stamp}.json", library)
    return {
        "state": "completed_with_errors" if errors else "completed",
        "wechat_articles": len(articles),
        "visited": len(seen),
        "errors": len(errors),
        "combined_episodes": len(merged["combined"].get("episodes", [])),
        "wechat_imported": merged["combined"].get("stats", {}).get("wechat_imported_episode_count", 0),
        "wechat_duplicates_skipped": merged["combined"].get("stats", {}).get("wechat_skipped_duplicate_count", 0),
        "output": str(wechat_dir / "wechat_library.json"),
        "combined_output": str(root_dir / "library_combined.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同步可公开访问的悦读FM微信公众号文章、音频和图片，并生成合并播放器主库"
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "yuedu_fm")
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED_FILE)
    parser.add_argument("--url", action="append", default=[], help="额外微信公众号文章 URL，可重复")
    parser.add_argument("--metadata-only", action="store_true", help="只保存 HTML/字段，不下载音频和图片")
    parser.add_argument("--discover-related", action="store_true", help="递归跟随文章正文中的公众号文章链接")
    parser.add_argument("--discover-limit", type=int, default=None, help="最多访问 N 篇文章")
    parser.add_argument("--max-images", type=int, default=8, help="每篇最多下载正文图片数")
    parser.add_argument("--pause-seconds", type=float, default=0.5, help="请求间隔，默认 0.5 秒")
    args = parser.parse_args()
    if args.discover_limit is not None and args.discover_limit < 1:
        parser.error("--discover-limit 必须大于 0")
    try:
        print(json.dumps(sync(args), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"state": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
