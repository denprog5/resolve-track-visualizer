from __future__ import annotations

import base64
import hashlib
import os
import threading
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import Picture
from mutagen.mp4 import MP4Cover
from PIL import Image

from .audio import ffprobe_duration


def _creationflags() -> int:
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


@dataclass
class TrackMetadata:
    source_path: str
    title: str
    artist: str
    album: str
    duration: float
    cover_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_stem(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    value = value.strip("._-")
    return value or "track"


def _first_text(tags: Any, keys: list[str]) -> str:
    if not tags:
        return ""
    for key in keys:
        try:
            value = tags.get(key)
        except AttributeError:
            value = None
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        text = str(value).strip()
        if text:
            return text
    return ""


def join_artists(text: str) -> str:
    """ID3v2.3 stores several artists as ``A/B/C``; show them as ``A, B, C``.

    Names such as ``AC/DC`` keep their slash: only split when every part is a
    plausible standalone name (three or more characters).
    """
    parts = [part.strip() for part in text.split("/")]
    if len(parts) > 1 and all(len(part) >= 3 for part in parts):
        return ", ".join(parts)
    return text


def _cover_from_tags(audio: Any) -> tuple[bytes, str] | tuple[None, None]:
    if audio is None:
        return None, None

    pictures = getattr(audio, "pictures", None)
    if pictures:
        picture = pictures[0]
        ext = "png" if picture.mime == "image/png" else "jpg"
        return picture.data, ext

    tags = getattr(audio, "tags", None)
    if not tags:
        return None, None

    for value in tags.values():
        if getattr(value, "FrameID", None) == "APIC" and getattr(value, "data", None):
            ext = "png" if getattr(value, "mime", "") == "image/png" else "jpg"
            return value.data, ext

    covr = tags.get("covr") if hasattr(tags, "get") else None
    if covr:
        cover = covr[0]
        ext = "png" if getattr(cover, "imageformat", None) == MP4Cover.FORMAT_PNG else "jpg"
        return bytes(cover), ext

    block = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
    if block:
        try:
            raw = base64.b64decode(block[0])
            picture = Picture(raw)
            ext = "png" if picture.mime == "image/png" else "jpg"
            return picture.data, ext
        except Exception:
            return None, None

    return None, None


def _save_cover(data: bytes, assets_dir: Path, stem: str) -> str | None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    try:
        image = Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    target = assets_dir / f"{safe_stem(stem)[:60]}_cover.png"
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    temporary = target.with_name(f"{target.stem}.tmp{os.getpid()}_{threading.get_ident()}.png")
    image.save(temporary)
    os.replace(temporary, target)
    return str(target)


def _ffprobe_tags(path: Path, ffprobe: str) -> dict[str, str]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format_tags",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creationflags(),
        )
        data = json.loads(result.stdout or "{}")
    except Exception:
        return {}
    tags = data.get("format", {}).get("tags", {}) or {}
    return {str(key).lower(): str(value) for key, value in tags.items() if value is not None}


def read_track_metadata(
    path: str | Path,
    assets_dir: str | Path,
    ffprobe: str = "ffprobe",
) -> TrackMetadata:
    source = Path(path)
    audio = MutagenFile(str(source), easy=False)
    tags = getattr(audio, "tags", None)

    title = _first_text(tags, ["TIT2", "title", "\xa9nam"])
    artist = _first_text(tags, ["TPE1", "artist", "\xa9ART"])
    album = _first_text(tags, ["TALB", "album", "\xa9alb"])

    if not title or not artist or not album:
        probe_tags = _ffprobe_tags(source, ffprobe)
        title = title or probe_tags.get("title", "")
        artist = artist or probe_tags.get("artist", "")
        album = album or probe_tags.get("album", "")

    if not title:
        title = source.stem
    artist = join_artists(artist)
    if not artist:
        artist = "Unknown Artist"

    duration = float(getattr(getattr(audio, "info", None), "length", 0.0) or 0.0)
    if duration <= 0.0:
        try:
            duration = ffprobe_duration(source, ffprobe=ffprobe)
        except (subprocess.CalledProcessError, ValueError):
            duration = 0.0

    cover_data, _ = _cover_from_tags(audio)
    cover_key = hashlib.sha256(cover_data).hexdigest()[:16] if cover_data else ""
    cover_path = _save_cover(cover_data, Path(assets_dir), f"{source.stem[:40]}_{cover_key}") if cover_data else None

    return TrackMetadata(
        source_path=str(source),
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        cover_path=cover_path,
    )
