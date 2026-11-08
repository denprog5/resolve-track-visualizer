from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .carrier import ensure_carrier
from .fusion_comp import CompSpec, write_comp
from .metadata import read_track_metadata, safe_stem
from .platform_paths import comp_staging_dir
from .render import RENDERER_REVISION, TrackInfo, render_preview, render_track_layers
from .skins import SUPPORTED_SKINS, catalog, effective_flags, normalize_design
from .waveform import analyse_waveform

JOBS_VERSION = 3
MANIFEST_SCHEMA = "tviz.manifest"
MANIFEST_VERSION = 4
MAX_TRACKS = 2000
COMP_RETENTION_SECONDS = 7 * 24 * 3600


def _configure_stdio() -> None:
    os.environ["PYTHONIOENCODING"] = "utf-8:replace"
    os.environ["PYTHONUTF8"] = "1"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _stream_safe_text(value: object, stream) -> str:
    text = str(value)
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeError:
        return text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def _emit(value: object = "", *, stream=None) -> None:
    stream = stream or sys.stdout
    stream.write(_stream_safe_text(value, stream) + "\n")
    stream.flush()


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _artwork_digest(cover_path: str | None) -> str:
    candidates = []
    if cover_path:
        candidates.append(Path(cover_path))
    fallback = os.environ.get("DAVINCI_TRACK_VISUALIZER_LOGO")
    if fallback:
        candidates.append(Path(fallback))
    for candidate in candidates:
        if candidate.is_file():
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                while chunk := handle.read(1 << 20):
                    digest.update(chunk)
            return digest.hexdigest()
    return "none"


# --------------------------------------------------------------------------------------------
# Job validation


def _exact_int(value: Any, name: str, minimum: int | None = None) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
    ):
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


def _finite(value: Any, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    parsed = float(value)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


@dataclass(frozen=True)
class TrackJob:
    id: str
    source: Path
    record_frame: int
    duration_frames: int
    source_start: float


@dataclass(frozen=True)
class Jobs:
    skin: str
    design: dict[str, Any]
    width: int
    height: int
    fps: float
    timeline_name: str
    tracks: tuple[TrackJob, ...]


def parse_jobs(data: Any) -> Jobs:
    if not isinstance(data, dict):
        raise ValueError("Jobs file must contain an object")
    if data.get("version") != JOBS_VERSION:
        raise ValueError(f"Jobs version must be {JOBS_VERSION}")
    timeline = data.get("timeline")
    if not isinstance(timeline, dict):
        raise ValueError("Jobs timeline must be an object")
    width = _exact_int(timeline.get("width"), "timeline.width", 16)
    height = _exact_int(timeline.get("height"), "timeline.height", 16)
    if width > 8192 or height > 8192:
        raise ValueError("Timeline resolution above 8192 pixels is not supported")
    fps = _finite(timeline.get("fps"), "timeline.fps")
    if not 1 <= fps <= 240:
        raise ValueError("timeline.fps must be between 1 and 240")
    skin = data.get("skin")
    if not isinstance(skin, str) or skin not in SUPPORTED_SKINS:
        raise ValueError(f"Jobs skin must be one of {', '.join(SUPPORTED_SKINS)}")
    design = data.get("design") or {}
    if not isinstance(design, dict):
        raise ValueError("Jobs design must be an object")
    tracks = data.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("Jobs file has no tracks")
    if len(tracks) > MAX_TRACKS:
        raise ValueError(f"At most {MAX_TRACKS} tracks can be prepared at once")

    parsed: list[TrackJob] = []
    seen: dict[str, str] = {}
    for index, job in enumerate(tracks, start=1):
        if not isinstance(job, dict):
            raise ValueError(f"Track job {index} must be an object")
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError(f"Track job {index} must have a non-empty string id")
        folded = job_id.casefold()
        if folded in seen:
            raise ValueError(f"Duplicate track job id: {seen[folded]} / {job_id}")
        seen[folded] = job_id
        source_value = job.get("source_path")
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError(f"Track job {job_id!r} must have a source path")
        source = Path(source_value).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Audio file not found: {source}")
        parsed.append(
            TrackJob(
                id=job_id,
                source=source.resolve(),
                record_frame=_exact_int(job.get("record_frame"), f"Track job {job_id!r} record_frame"),
                duration_frames=_exact_int(job.get("duration_frames"), f"Track job {job_id!r} duration_frames", 1),
                source_start=_finite(job.get("source_start_time", 0.0), f"Track job {job_id!r} source_start_time", 0.0),
            )
        )
    return Jobs(
        skin=skin,
        design=normalize_design(design, skin),
        width=width,
        height=height,
        fps=fps,
        timeline_name=str(timeline.get("name") or "Timeline"),
        tracks=tuple(parsed),
    )


# --------------------------------------------------------------------------------------------
# Preparation


def _content_hash(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _cleanup_old_comps(directory: Path) -> None:
    cutoff = time.time() - COMP_RETENTION_SECONDS
    try:
        for path in directory.glob("TVIZ_*.comp"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _prepare_track(
    job: TrackJob,
    jobs: Jobs,
    out_dir: Path,
    comp_dir: Path,
    ffmpeg: str,
    ffprobe: str,
) -> dict[str, Any]:
    flags = effective_flags(jobs.design, jobs.skin)
    metadata = read_track_metadata(job.source, out_dir / "assets", ffprobe=ffprobe)
    clip_seconds = job.duration_frames / jobs.fps
    if jobs.design["progress_basis"] == "clip" or metadata.duration <= 0:
        offset = 0.0
        total = clip_seconds
        segment = (job.source_start, clip_seconds)
    else:
        offset = job.source_start
        total = max(metadata.duration, job.source_start + clip_seconds * 0.5)
        segment = (0.0, None)

    levels = None
    warnings: list[str] = []
    if flags["bars"]:
        try:
            levels = list(
                analyse_waveform(
                    job.source,
                    int(jobs.design["bar_count"]),
                    ffmpeg=ffmpeg,
                    start=segment[0],
                    duration=segment[1],
                    cache_dir=out_dir / "cache",
                ).levels
            )
        except (OSError, RuntimeError) as exc:
            warnings.append(f"Waveform unavailable for {job.source.name}: {exc}")
            levels = [0.12] * int(jobs.design["bar_count"])

    info = TrackInfo(title=metadata.title, artist=metadata.artist, cover_path=metadata.cover_path)
    layer_hash = _content_hash(
        {
            "renderer": RENDERER_REVISION,
            "skin": jobs.skin,
            "design": jobs.design,
            "frame": [jobs.width, jobs.height],
            "title": metadata.title,
            "artist": metadata.artist,
            "artwork": _artwork_digest(metadata.cover_path),
            "levels": levels,
        }
    )
    stem = f"TVIZ_{safe_stem(job.id)[:40].rstrip('._-') or 'track'}_{layer_hash}"
    layers, paths = render_track_layers(info, levels, jobs.design, jobs.skin, jobs.width, jobs.height, out_dir / "layers", stem)

    spec = CompSpec(
        width=jobs.width,
        height=jobs.height,
        fps=jobs.fps,
        clip_frames=job.duration_frames,
        card_path=str(paths["card"]),
        played_path=paths["played"],
        knob_path=paths["knob"],
        progress_x1=layers.progress_x1,
        progress_x2=layers.progress_x2,
        offset_seconds=offset,
        total_seconds=total,
        texts=tuple(layers.texts),
        title_scroll=replace(layers.title_scroll, path=paths["title"]) if layers.title_scroll and paths["title"] else None,
    )
    comp_hash = _content_hash({"layers": stem, "timing": [job.duration_frames, jobs.fps, round(offset, 6), round(total, 6)], "texts": [t.__dict__ for t in layers.texts]})
    comp_path = write_comp(comp_dir / f"{stem}_{comp_hash[:8]}.comp", spec)
    return {
        "id": job.id,
        "source_path": str(job.source),
        "title": metadata.title,
        "artist": metadata.artist,
        "record_frame": job.record_frame,
        "duration_frames": job.duration_frames,
        "offset_seconds": offset,
        "total_seconds": total,
        "card_path": paths["card"],
        "comp_path": str(comp_path),
        "warnings": warnings,
    }


def prepare(jobs: Jobs, out_dir: Path, *, ffmpeg: str, ffprobe: str, workers: int = 0) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    comp_dir = comp_staging_dir(out_dir / "comps")
    comp_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_comps(comp_dir)

    longest = max(job.duration_frames for job in jobs.tracks)
    carrier_path, carrier_frames = ensure_carrier(out_dir / "carriers", longest, jobs.fps, width=jobs.width, height=jobs.height)
    _emit(f"Carrier: {carrier_path.name} ({carrier_frames} frames)")

    total = len(jobs.tracks)
    worker_count = workers or max(1, min(4, (os.cpu_count() or 2) - 1))
    results: list[dict[str, Any] | None] = [None] * total
    failed: list[dict[str, str]] = []
    done = 0

    def run(index: int) -> tuple[int, dict[str, Any] | None, str]:
        job = jobs.tracks[index]
        try:
            return index, _prepare_track(job, jobs, out_dir, comp_dir, ffmpeg, ffprobe), ""
        except Exception as exc:  # one unreadable file must not cost the whole run
            return index, None, f"{job.source.name}: {exc}"

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        for index, item, error in pool.map(run, range(total)):
            done += 1
            if item is None:
                failed.append({"id": jobs.tracks[index].id, "error": error})
                _emit(f"[{done}/{total}] Warning: {error}")
                continue
            results[index] = item
            _emit(f"[{done}/{total}] {item['artist']} - {item['title']}")

    tracks = [item for item in results if item is not None]
    if not tracks:
        raise RuntimeError(failed[0]["error"] if failed else "No tracks were prepared")
    warnings = [warning for item in tracks for warning in item.pop("warnings")]
    return {
        "schema": MANIFEST_SCHEMA,
        "version": MANIFEST_VERSION,
        "renderer": RENDERER_REVISION,
        "timeline": {"name": jobs.timeline_name, "width": jobs.width, "height": jobs.height, "fps": jobs.fps},
        "skin": jobs.skin,
        "carrier": {"path": str(carrier_path), "frames": carrier_frames},
        "tracks": tracks,
        "failed": failed,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------------------------
# Commands


def command_prepare(args: argparse.Namespace) -> int:
    jobs = parse_jobs(json.loads(Path(args.jobs).read_text(encoding="utf-8")))
    _emit(f"Preparing {len(jobs.tracks)} player(s): {jobs.skin}, {jobs.width}x{jobs.height} @ {jobs.fps:g} fps")
    manifest = prepare(jobs, Path(args.out).resolve(), ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, workers=args.workers)
    manifest_path = Path(args.manifest).resolve()
    _write_json_atomic(manifest_path, manifest)
    for warning in manifest["warnings"]:
        _emit(f"Warning: {warning}")
    _emit(f"Manifest: {manifest_path}")
    return 0


def command_scan(args: argparse.Namespace) -> int:
    out_dir = Path(args.out).resolve()
    payload = []
    for item in args.tracks:
        path = Path(item).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        payload.append(read_track_metadata(path, out_dir / "assets", ffprobe=args.ffprobe).to_dict())
    _emit(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_preview(args: argparse.Namespace) -> int:
    design: dict[str, Any] = {}
    skin = args.skin
    if args.design_json:
        loaded = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Design JSON must contain an object")
        design = loaded.get("design", loaded) if isinstance(loaded.get("design"), dict) else loaded
        skin = loaded.get("skin", skin) if isinstance(loaded.get("skin"), str) else skin
    options = dict(
        frame_width=args.frame_width,
        frame_height=args.frame_height,
        preview_width=args.preview_width,
        title=args.title,
        artist=args.artist,
        duration=args.duration,
        progress=args.progress,
        cover_path=args.cover,
    )
    target = render_preview(args.out, design, skin, crop=args.crop, **options)
    _emit(f"Preview: {target}")
    if args.crop_out:
        close_up = render_preview(args.crop_out, design, skin, crop=True, **options)
        _emit(f"Close-up: {close_up}")
    return 0


def command_catalog(args: argparse.Namespace) -> int:
    payload = catalog()
    if args.out:
        _write_json_atomic(Path(args.out), payload)
        _emit(f"Catalog: {args.out}")
    else:
        _emit(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_update(args: argparse.Namespace) -> int:
    from .updater import check_for_update

    def progress(percent: int) -> None:
        _emit(f"TVIZ_UPDATE_PROGRESS {percent}")

    result = check_for_update(
        Path(args.install_root),
        download=args.download,
        current=args.current_version,
        source_dir=Path(args.source_dir) if args.source_dir else None,
        progress=progress,
    )
    _emit("TVIZ_UPDATE " + json.dumps(result, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="davinci-track-visualizer", description="Track Visualizer engine for DaVinci Resolve")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Render player layers, Fusion comps and the carrier clip")
    prepare_parser.add_argument("--jobs", required=True, help="Timeline jobs JSON (version 3)")
    prepare_parser.add_argument("--out", required=True, help="Output directory")
    prepare_parser.add_argument("--manifest", required=True, help="Manifest JSON output path")
    prepare_parser.add_argument("--ffmpeg", default="ffmpeg", help="Path to ffmpeg")
    prepare_parser.add_argument("--ffprobe", default="ffprobe", help="Path to ffprobe")
    prepare_parser.add_argument("--workers", type=int, default=0, help="Parallel workers (0 = automatic)")
    prepare_parser.set_defaults(func=command_prepare)

    scan = subparsers.add_parser("scan", help="Read track tags and covers")
    scan.add_argument("tracks", nargs="+", help="Audio files")
    scan.add_argument("--out", default="outputs", help="Output directory for extracted covers")
    scan.add_argument("--ffprobe", default="ffprobe", help="Path to ffprobe")
    scan.set_defaults(func=command_scan)

    preview = subparsers.add_parser("preview-style", help="Render a style preview PNG")
    preview.add_argument("--out", required=True, help="Preview PNG output path")
    preview.add_argument("--design-json", help="JSON file with a design object (optionally {skin, design})")
    preview.add_argument("--skin", choices=SUPPORTED_SKINS, default="classic")
    preview.add_argument("--frame-width", type=int, default=1920)
    preview.add_argument("--frame-height", type=int, default=1080)
    preview.add_argument("--preview-width", type=int, default=640)
    preview.add_argument("--title", default="Track Title Preview")
    preview.add_argument("--artist", default="Artist Name")
    preview.add_argument("--duration", type=float, default=225.0)
    preview.add_argument("--progress", type=float, default=0.36)
    preview.add_argument("--cover", help="Optional cover image path")
    preview.add_argument("--crop", action="store_true", help="Crop to the player instead of the full frame")
    preview.add_argument("--crop-out", help="Also write a close-up cropped to the player at this path")
    preview.set_defaults(func=command_preview)

    catalog_parser = subparsers.add_parser("catalog", help="Print skins, defaults and palettes as JSON")
    catalog_parser.add_argument("--out", help="Write to a file instead of stdout")
    catalog_parser.set_defaults(func=command_catalog)

    update = subparsers.add_parser("update", help="Check for a signed update and optionally download its installer")
    update.add_argument("--install-root", required=True, help="Installed application directory (holds manifest.json)")
    update.add_argument("--download", action="store_true", help="Download and verify the installer when a newer version exists")
    update.add_argument("--current-version", help="Override the installed version (testing)")
    update.add_argument("--source-dir", help="Read update.json and the installer from this directory (testing; the signature is still required)")
    update.set_defaults(func=command_update)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        _emit(f"Error: {exc}", stream=sys.stderr)
        _emit(traceback.format_exc(), stream=sys.stderr)
        return 1
