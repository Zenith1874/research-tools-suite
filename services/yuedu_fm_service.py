"""Local, auditable mirror and player data service for the YueDu FM RSS feed.

The feed and every remote asset remain attributed to their source.  Raw feed
snapshots are append-only; generated current-state files are written atomically.
Audio downloads use a ``.part`` file and HTTP Range so an interrupted sync can
resume without discarding already transferred bytes.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import mimetypes
import os
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests


log = logging.getLogger(__name__)

DEFAULT_FEED_URL = "https://feeds.redcircle.com/9e7cc2c9-54c2-431d-9be3-3305ce235d00"
USER_AGENT = "ResearchToolsSuite/1.0 (personal offline podcast reader)"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
PODCAST_NS = "https://podcastindex.org/namespace/1.0"
SCHEMA_VERSION = 1
CHUNK_BYTES = 1024 * 1024
COMBINED_LIBRARY_NAME = "library_combined.json"


class YueduFMError(RuntimeError):
    """A user-facing feed, sync, or local-library error."""


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "br", "p", "div", "li", "ul", "ol", "blockquote", "h1", "h2", "h3",
        "h4", "h5", "h6", "section", "article", "tr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    text = html.unescape("".join(parser.parts)).replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _text(node: ET.Element, name: str, namespaces: dict[str, str] | None = None) -> str:
    child = node.find(name, namespaces or {})
    return (child.text or "").strip() if child is not None and child.text else ""


def _safe_iso_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return raw


def _integer(raw, default=0) -> int:
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return default


def _episode_id(guid: str, audio_url: str, title: str) -> str:
    identity = guid or audio_url or title
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _extension(url: str, content_type: str, fallback: str) -> str:
    path_suffix = Path(urlparse(url).path).suffix.casefold()
    if re.fullmatch(r"\.[a-z0-9]{1,6}", path_suffix or ""):
        return path_suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return guessed or fallback


def parse_feed(xml_bytes: bytes, *, feed_url: str = DEFAULT_FEED_URL) -> dict:
    """Parse RSS into a stable local-library schema without network access."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise YueduFMError(f"RSS XML 无法解析：{exc}") from exc
    channel = root.find("channel")
    if channel is None:
        raise YueduFMError("RSS 缺少 channel")

    namespaces = {"itunes": ITUNES_NS, "content": CONTENT_NS, "podcast": PODCAST_NS}
    channel_image_node = channel.find("itunes:image", namespaces)
    channel_image_url = channel_image_node.get("href", "") if channel_image_node is not None else ""
    episodes = []
    declared_audio_bytes = 0
    for position, item in enumerate(channel.findall("item")):
        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url", "").strip() if enclosure is not None else ""
        audio_type = enclosure.get("type", "").strip() if enclosure is not None else ""
        audio_bytes = _integer(enclosure.get("length")) if enclosure is not None else 0
        declared_audio_bytes += audio_bytes
        image_node = item.find("itunes:image", namespaces)
        image_url = image_node.get("href", "").strip() if image_node is not None else channel_image_url
        title = _text(item, "title")
        guid = _text(item, "guid")
        description_html = _text(item, "content:encoded", namespaces) or _text(item, "description")
        episode_id = _episode_id(guid, audio_url, title)
        episodes.append({
            "episode_id": episode_id,
            "position": position,
            "guid": guid,
            "title": title,
            "subtitle": _text(item, "itunes:subtitle", namespaces),
            "author": _text(item, "itunes:author", namespaces) or _text(item, "author"),
            "published_at": _safe_iso_date(_text(item, "pubDate")),
            "duration_seconds": _integer(_text(item, "itunes:duration", namespaces)),
            "explicit": _text(item, "itunes:explicit", namespaces),
            "link": _text(item, "link"),
            "description_html": description_html,
            "description_text": html_to_text(description_html),
            "audio": {
                "source_url": audio_url,
                "content_type": audio_type or "audio/mpeg",
                "declared_bytes": audio_bytes,
                "actual_bytes": 0,
                "declared_size_matches": None,
                "signature_valid": None,
                "relative_path": f"audio/{episode_id}{_extension(audio_url, audio_type, '.mp3')}",
                "downloaded": False,
                "downloaded_bytes": 0,
                "sha256": "",
            },
            "image": {
                "source_url": image_url,
                "actual_bytes": 0,
                "signature_valid": None,
                "relative_path": f"images/{episode_id}{_extension(image_url, 'image/jpeg', '.jpg')}",
                "downloaded": False,
                "downloaded_bytes": 0,
                "sha256": "",
            },
        })

    if not episodes:
        raise YueduFMError("RSS 中没有可用单集")
    return {
        "schema_version": SCHEMA_VERSION,
        "feed_url": feed_url,
        "feed_fetched_at": datetime.now(timezone.utc).isoformat(),
        "channel": {
            "title": _text(channel, "title"),
            "link": _text(channel, "link"),
            "language": _text(channel, "language"),
            "copyright": _text(channel, "copyright"),
            "author": _text(channel, "itunes:author", namespaces),
            "subtitle": _text(channel, "itunes:subtitle", namespaces),
            "summary": _text(channel, "itunes:summary", namespaces),
            "description_html": _text(channel, "description"),
            "description_text": html_to_text(_text(channel, "description")),
            "image_source_url": channel_image_url,
        },
        "stats": {
            "episode_count": len(episodes),
            "declared_audio_bytes": declared_audio_bytes,
            "downloaded_audio_count": 0,
            "downloaded_image_count": 0,
            "downloaded_audio_bytes": 0,
            "downloaded_image_bytes": 0,
        },
        "episodes": episodes,
    }


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


class YueduFMManager:
    def __init__(self, root_dir, *, feed_url: str = DEFAULT_FEED_URL, session_factory=requests.Session):
        self.root_dir = Path(root_dir)
        self.feed_url = feed_url
        self.session_factory = session_factory
        self.library_path = self.root_dir / "library.json"
        self.combined_library_path = self.root_dir / COMBINED_LIBRARY_NAME
        self.status_path = self.root_dir / "sync_status.json"
        self._sync_lock = threading.Lock()
        self._status_lock = threading.Lock()
        for relative in ("audio", "images", "metadata", "raw", "manifests"):
            (self.root_dir / relative).mkdir(parents=True, exist_ok=True)
        if not self.status_path.exists():
            _atomic_json(self.status_path, self._idle_status())

    @staticmethod
    def _idle_status() -> dict:
        return {
            "state": "idle", "phase": "idle", "message": "尚未同步",
            "started_at": "", "finished_at": "", "episode_total": 0,
            "episode_processed": 0, "audio_downloaded": 0, "image_downloaded": 0,
            "bytes_downloaded": 0, "errors": [], "warnings": [],
        }

    def _read_json(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def status(self) -> dict:
        return self._read_json(self.status_path, self._idle_status())

    def library(self) -> dict:
        library = self._read_json(self.combined_library_path, None)
        if library is None:
            library = self._read_json(self.library_path, None)
        if library is None:
            return {
                "schema_version": SCHEMA_VERSION, "feed_url": self.feed_url,
                "channel": {"title": "悦读FM"},
                "stats": {"episode_count": 0, "declared_audio_bytes": 0,
                          "downloaded_audio_count": 0, "downloaded_image_count": 0,
                          "downloaded_audio_bytes": 0, "downloaded_image_bytes": 0},
                "episodes": [], "not_synced": True,
            }
        return library

    def _set_status(self, **changes) -> dict:
        with self._status_lock:
            status = self.status()
            status.update(changes)
            _atomic_json(self.status_path, status)
            return status

    def _reconcile_local_files(self, library: dict) -> None:
        stats = library["stats"]
        stats.update({
            "downloaded_audio_count": 0, "downloaded_image_count": 0,
            "downloaded_audio_bytes": 0, "downloaded_image_bytes": 0,
            "signature_valid_audio_count": 0, "signature_invalid_audio_count": 0,
            "declared_size_mismatch_count": 0,
        })
        for episode in library["episodes"]:
            if episode["audio"].get("signature_valid") is True:
                stats["signature_valid_audio_count"] += 1
            elif episode["audio"].get("signature_valid") is False:
                stats["signature_invalid_audio_count"] += 1
            if episode["audio"].get("declared_size_matches") is False:
                stats["declared_size_mismatch_count"] += 1
            for kind in ("audio", "image"):
                asset = episode[kind]
                path = self.root_dir / asset["relative_path"]
                size = path.stat().st_size if path.is_file() else 0
                expected = asset.get("actual_bytes", 0) or (
                    asset.get("declared_bytes", 0) if kind == "audio" else 0)
                complete = bool(size and (not expected or size == expected))
                asset["downloaded"] = complete
                asset["downloaded_bytes"] = size if complete else 0
                if complete:
                    stats[f"downloaded_{kind}_count"] += 1
                    stats[f"downloaded_{kind}_bytes"] += size

    def _write_library(self, library: dict, *, snapshot: bool = False) -> None:
        self._reconcile_local_files(library)
        _atomic_json(self.library_path, library)
        if snapshot:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            _atomic_json(self.root_dir / "manifests" / f"library_{stamp}.json", library)

    def _write_episode_metadata(self, episode: dict) -> None:
        _atomic_json(self.root_dir / "metadata" / f"{episode['episode_id']}.json", episode)

    def _fetch_feed(self, session: requests.Session) -> tuple[bytes, dict]:
        response = session.get(self.feed_url, timeout=(10, 45))
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "xml" not in content_type.casefold() and not response.content.lstrip().startswith(b"<?xml"):
            raise YueduFMError(f"订阅源返回了非 XML 内容：{content_type or 'unknown'}")
        xml_bytes = response.content
        library = parse_feed(xml_bytes, feed_url=self.feed_url)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        raw_path = self.root_dir / "raw" / f"feed_{stamp}.xml"
        raw_path.write_bytes(xml_bytes)
        library["raw_feed_snapshot"] = str(raw_path.relative_to(self.root_dir)).replace(os.sep, "/")
        return xml_bytes, library

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_media_signature(path: Path, expected_prefix: str) -> bool:
        with path.open("rb") as handle:
            prefix = handle.read(16)
        if expected_prefix == "audio/":
            valid = prefix.startswith(b"ID3") or (
                len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0)
        elif expected_prefix == "image/":
            valid = (prefix.startswith(b"\xff\xd8\xff") or prefix.startswith(b"\x89PNG\r\n\x1a\n")
                     or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"))
        else:
            valid = True
        return valid

    def _download_asset(self, session: requests.Session, source_url: str, target: Path,
                        *, expected_bytes: int = 0,
                        expected_prefix: str = "") -> tuple[int, str, int, bool]:
        if not source_url.startswith(("https://", "http://")):
            raise YueduFMError("资源 URL 无效")
        if target.is_file() and target.stat().st_size and (
                not expected_bytes or target.stat().st_size == expected_bytes):
            signature_valid = self._validate_media_signature(target, expected_prefix)
            return 0, "", target.stat().st_size, signature_valid
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        resume_at = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={resume_at}-"} if resume_at else {}
        response = session.get(source_url, headers=headers, stream=True, timeout=(15, 120))
        if resume_at and response.status_code == 416:
            match = re.search(r"bytes \*/(\d+)", response.headers.get("Content-Range", ""))
            response.close()
            if match and int(match.group(1)) == resume_at:
                signature_valid = self._validate_media_signature(part, expected_prefix)
                digest = self._hash_file(part)
                if target.exists():
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    target.replace(target.with_suffix(target.suffix + f".invalid-{stamp}"))
                os.replace(part, target)
                return 0, digest, resume_at, signature_valid
            response = session.get(source_url, stream=True, timeout=(15, 120))
            resume_at = 0
        if resume_at and response.status_code != 206:
            resume_at = 0
            response.close()
            response = session.get(source_url, stream=True, timeout=(15, 120))
        response.raise_for_status()
        response_type = (response.headers.get("Content-Type") or "").casefold()
        if expected_prefix and response_type and not response_type.startswith(expected_prefix):
            response.close()
            raise YueduFMError(f"资源返回了异常类型：{response_type}")
        mode = "ab" if resume_at and response.status_code == 206 else "wb"
        response_expected_bytes = 0
        if response.status_code == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)",
                                 response.headers.get("Content-Range", "").strip())
            if match and int(match.group(1)) == resume_at and match.group(3) != "*":
                response_expected_bytes = int(match.group(3))
        else:
            response_expected_bytes = _integer(response.headers.get("Content-Length"))
        digest = hashlib.sha256()
        if mode == "ab":
            with part.open("rb") as existing:
                for chunk in iter(lambda: existing.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
        transferred = 0
        with part.open(mode) as handle:
            for chunk in response.iter_content(CHUNK_BYTES):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                transferred += len(chunk)
        final_size = part.stat().st_size
        if response_expected_bytes and final_size != response_expected_bytes:
            raise YueduFMError(
                f"HTTP 文件大小校验失败：期望 {response_expected_bytes}，实际 {final_size}")
        signature_valid = self._validate_media_signature(part, expected_prefix)
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target.replace(target.with_suffix(target.suffix + f".invalid-{stamp}"))
        os.replace(part, target)
        return transferred, digest.hexdigest(), final_size, signature_valid

    def sync(self, *, download_audio: bool = True, limit: int | None = None,
             request_pause_seconds: float = 0.15) -> dict:
        if not self._sync_lock.acquire(blocking=False):
            raise YueduFMError("同步任务已经在运行")
        started_at = datetime.now(timezone.utc).isoformat()
        self._set_status(
            state="running", phase="feed", message="正在读取 RSS 目录", started_at=started_at,
            finished_at="", episode_total=0, episode_processed=0, audio_downloaded=0,
            image_downloaded=0, bytes_downloaded=0, errors=[], warnings=[],
            download_audio=download_audio,
        )
        try:
            session = self.session_factory()
            session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
            _xml_bytes, library = self._fetch_feed(session)
            previous = self.library()
            previous_by_id = {row["episode_id"]: row for row in previous.get("episodes", [])}
            for episode in library["episodes"]:
                old = previous_by_id.get(episode["episode_id"], {})
                for kind in ("audio", "image"):
                    episode[kind]["sha256"] = old.get(kind, {}).get("sha256", "")
                    episode[kind]["actual_bytes"] = old.get(kind, {}).get("actual_bytes", 0)
                    episode[kind]["signature_valid"] = old.get(kind, {}).get("signature_valid")
                    if kind == "audio":
                        episode[kind]["declared_size_matches"] = old.get(
                            kind, {}).get("declared_size_matches")
            self._write_library(library)
            for episode in library["episodes"]:
                self._write_episode_metadata(episode)

            selected = library["episodes"][:max(0, limit)] if limit is not None else library["episodes"]
            self._set_status(
                phase="assets", message="正在同步封面与音频" if download_audio else "正在同步封面",
                episode_total=len(selected),
            )
            errors = []
            warnings = []
            audio_downloaded = image_downloaded = bytes_downloaded = 0
            for index, episode in enumerate(selected, 1):
                for kind in ("image", "audio"):
                    if kind == "audio" and not download_audio:
                        continue
                    asset = episode[kind]
                    if not asset.get("source_url"):
                        errors.append({"episode_id": episode["episode_id"], "kind": kind,
                                       "error": "RSS 缺少资源 URL"})
                        continue
                    target = self.root_dir / asset["relative_path"]
                    was_downloaded = target.is_file() and target.stat().st_size > 0
                    try:
                        transferred, sha256, actual_bytes, signature_valid = self._download_asset(
                            session, asset["source_url"], target,
                            expected_bytes=asset.get("actual_bytes", 0),
                            expected_prefix="audio/" if kind == "audio" else "image/",
                        )
                        if sha256:
                            asset["sha256"] = sha256
                        asset["downloaded"] = target.is_file()
                        asset["downloaded_bytes"] = target.stat().st_size if target.is_file() else 0
                        asset["actual_bytes"] = actual_bytes
                        asset["signature_valid"] = signature_valid
                        if not signature_valid:
                            warnings.append({
                                "episode_id": episode["episode_id"], "kind": kind,
                                "warning": "服务器文件长度完整，但文件签名异常，可能无法播放或显示",
                            })
                        if kind == "audio":
                            declared = asset.get("declared_bytes", 0)
                            asset["declared_size_matches"] = bool(declared and declared == actual_bytes)
                        bytes_downloaded += transferred
                        if not was_downloaded and target.exists():
                            if kind == "audio":
                                audio_downloaded += 1
                            else:
                                image_downloaded += 1
                    except (requests.RequestException, OSError, YueduFMError) as exc:
                        errors.append({"episode_id": episode["episode_id"], "kind": kind,
                                       "error": str(exc)[:500]})
                    time.sleep(max(0.0, request_pause_seconds))
                self._write_episode_metadata(episode)
                if index % 10 == 0 or index == len(selected):
                    self._write_library(library)
                self._set_status(
                    episode_processed=index, audio_downloaded=audio_downloaded,
                    image_downloaded=image_downloaded, bytes_downloaded=bytes_downloaded,
                    errors=errors[-100:], message=f"已处理 {index}/{len(selected)} 集",
                    warnings=warnings[-100:],
                )

            self._write_library(library, snapshot=True)
            finished_at = datetime.now(timezone.utc).isoformat()
            state = "completed_with_errors" if errors else "completed"
            return self._set_status(
                state=state, phase="done", message=("同步完成，但部分资源失败" if errors else "同步完成"),
                finished_at=finished_at, episode_processed=len(selected), errors=errors[-100:],
                warnings=warnings[-100:],
            )
        except Exception as exc:
            self._set_status(
                state="failed", phase="failed", message=str(exc)[:500],
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            if isinstance(exc, YueduFMError):
                raise
            raise YueduFMError(f"同步失败：{exc}") from exc
        finally:
            self._sync_lock.release()

    def start_sync(self, *, download_audio: bool = True) -> dict:
        if self._sync_lock.locked():
            raise YueduFMError("同步任务已经在运行")

        def run():
            try:
                self.sync(download_audio=download_audio)
            except Exception:
                log.exception("悦读FM 后台同步失败")

        thread = threading.Thread(target=run, name="yuedu-fm-sync", daemon=True)
        thread.start()
        for _ in range(20):
            status = self.status()
            if status.get("state") == "running":
                return status
            time.sleep(0.01)
        return self.status()

    def media_path(self, episode_id: str, kind: str) -> tuple[Path, str]:
        if not re.fullmatch(r"[0-9a-f]{24}", episode_id or "") or kind not in {"audio", "image"}:
            raise YueduFMError("资源标识无效")
        episode = next((row for row in self.library().get("episodes", [])
                        if row.get("episode_id") == episode_id), None)
        if not episode:
            raise YueduFMError("单集不存在")
        relative = episode[kind].get("relative_path", "")
        target = (self.root_dir / relative).resolve()
        root = self.root_dir.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise YueduFMError("资源路径无效") from exc
        if not target.is_file():
            raise FileNotFoundError(target)
        return target, episode[kind].get("content_type") or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
