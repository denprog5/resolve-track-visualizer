from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import traceback
from pathlib import Path

from .metadata import read_track_metadata, safe_stem
from .render import (
    LIVE_DYNAMIC_SCHEMA_VERSION,
    RenderSettings,
    SUPPORTED_SKINS,
    render_live_carrier,
    render_overlay,
    render_style_preview,
    static_renderer_revision,
)


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


def _artwork_digest(metadata) -> str:
    artwork_path = None
    if metadata.cover_path:
        cover_path = Path(metadata.cover_path)
        if cover_path.is_file():
            artwork_path = cover_path
    if artwork_path is None:
        fallback_value = os.environ.get("DAVINCI_TRACK_VISUALIZER_LOGO")
        if fallback_value:
            fallback_path = Path(fallback_value)
            if fallback_path.is_file():
                artwork_path = fallback_path
    if artwork_path is None:
        return "none"

    digest = hashlib.sha256()
    try:
        with artwork_path.open("rb") as artwork_file:
            while chunk := artwork_file.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"Unable to read artwork bytes: {artwork_path}") from exc
    return digest.hexdigest()


def _load_playlist(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [str(item) for item in data]
    if isinstance(data, dict):
        return [str(item) for item in data.get("tracks", [])]
    raise ValueError("Playlist must be a JSON list or an object with a 'tracks' list")


def _collect_tracks(args: argparse.Namespace) -> list[Path]:
    tracks: list[str] = []
    if args.playlist:
        tracks.extend(_load_playlist(Path(args.playlist)))
    tracks.extend(args.tracks or [])

    unique: list[Path] = []
    seen: set[str] = set()
    for item in tracks:
        path = Path(item).expanduser().resolve()
        key = str(path).lower()
        if key in seen:
            continue
        if not path.exists():
            raise FileNotFoundError(path)
        seen.add(key)
        unique.append(path)
    if not unique:
        raise ValueError("No tracks were provided")
    return unique


def command_scan(args: argparse.Namespace) -> int:
    out_dir = Path(args.out).resolve()
    assets_dir = out_dir / "assets"
    tracks = _collect_tracks(args)
    payload = []
    for path in tracks:
        metadata = read_track_metadata(path, assets_dir, ffprobe=args.ffprobe)
        payload.append(metadata.to_dict())
    _emit(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_render(args: argparse.Namespace) -> int:
    out_dir = Path(args.out).resolve()
    assets_dir = out_dir / "assets"
    overlays_dir = out_dir / "overlays"
    settings = RenderSettings(
        width=args.width,
        height=args.height,
        fps=args.fps,
        bars=args.bars,
        codec=args.codec,
        skin=args.skin,
    )
    tracks = _collect_tracks(args)
    rendered = []

    for index, path in enumerate(tracks, start=1):
        _emit(f"[{index}/{len(tracks)}] Reading metadata: {path}")
        metadata = read_track_metadata(path, assets_dir, ffprobe=args.ffprobe)
        _emit(f"[{index}/{len(tracks)}] Preparing player: {metadata.artist} - {metadata.title}")
        _emit(f"[{index}/{len(tracks)}] Rendering overlay ({metadata.duration:.1f}s)")
        def progress(done: int, total: int, idx: int = index) -> None:
            percent = int(done * 100 / max(1, total))
            _emit(f"[{idx}/{len(tracks)}] Rendering frames: {done}/{total} ({percent}%)")

        rendered_track = render_overlay(
            metadata,
            [],
            overlays_dir,
            settings,
            ffmpeg=args.ffmpeg,
            progress_callback=progress,
        )
        rendered.append(rendered_track.to_dict())

    manifest = {
        "version": 1,
        "timeline_name": args.timeline_name,
        "settings": {
            "width": settings.width,
            "height": settings.height,
            "fps": settings.fps,
            "bars": settings.bars,
            "codec": settings.codec,
            "skin": settings.skin,
            "design": settings.design,
        },
        "tracks": rendered,
    }
    manifest_path = Path(args.manifest).resolve() if args.manifest else out_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit(f"Manifest: {manifest_path}")
    return 0


def _settings_from_args_or_jobs(args: argparse.Namespace, jobs: dict) -> RenderSettings:
    job_settings = jobs.get("settings", {}) if isinstance(jobs, dict) else {}
    design = jobs.get("design") or job_settings.get("design") or {}
    skin = getattr(args, "skin", None) or jobs.get("skin") or job_settings.get("skin") or "classic"
    return RenderSettings(
        width=int(args.width or job_settings.get("width") or 640),
        height=int(args.height or job_settings.get("height") or 160),
        fps=int(args.fps or job_settings.get("fps") or 30),
        bars=int(args.bars or job_settings.get("bars") or 56),
        codec=str(args.codec or job_settings.get("codec") or "qtrle"),
        design=design,
        player_width=int(job_settings.get("player_width") or 0) or None,
        player_height=int(job_settings.get("player_height") or 0) or None,
        margin=int(job_settings.get("margin") if job_settings.get("margin") is not None else 48),
        bake_position=bool(job_settings.get("bake_position") or False),
        skin=str(skin),
    )


def command_render_jobs(args: argparse.Namespace) -> int:
    jobs_path = Path(args.jobs).resolve()
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    tracks = jobs.get("tracks", [])
    if not tracks:
        raise ValueError("Jobs file has no tracks")

    out_dir = Path(args.out or jobs.get("output_dir") or jobs_path.parent).resolve()
    assets_dir = out_dir / "assets"
    overlays_dir = out_dir / "overlays"
    settings = _settings_from_args_or_jobs(args, jobs)
    rendered = []

    for index, job in enumerate(tracks, start=1):
        path = Path(job["source_path"]).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        duration = float(job.get("duration") or 0.0)
        source_start_time = float(job.get("source_start_time") or 0.0)
        if duration <= 0:
            raise ValueError(f"Track job has invalid duration: {path}")

        job_id = str(job.get("id") or safe_stem(f"job_{index}_{path.stem}"))
        output_stem = f"TVIZ__{safe_stem(job_id)}"
        _emit(f"[{index}/{len(tracks)}] Reading metadata: {path}")
        metadata = read_track_metadata(path, assets_dir, ffprobe=args.ffprobe)
        metadata.duration = duration
        _emit(
            f"[{index}/{len(tracks)}] Preparing segment: {metadata.artist} - {metadata.title} "
            f"({source_start_time:.2f}s + {duration:.2f}s)"
        )
        metadata.duration = duration
        rendered_track = render_overlay(
            metadata,
            [],
            overlays_dir,
            settings,
            ffmpeg=args.ffmpeg,
            output_stem=output_stem,
            job_id=job_id,
            record_frame=int(round(float(job.get("record_frame") or 0))),
            source_start_time=source_start_time,
            timeline_item_name=str(job.get("timeline_item_name") or ""),
            progress_callback=lambda done, total, idx=index: _emit(
                f"[{idx}/{len(tracks)}] Rendering frames: {done}/{total} ({int(done * 100 / max(1, total))}%)"
            ),
        )
        item = rendered_track.to_dict()
        item.update({key: value for key, value in job.items() if key not in item})
        rendered.append(item)

    manifest = {
        "version": 2,
        "mode": "timeline_update",
        "timeline_name": jobs.get("timeline_name") or args.timeline_name or "Track Visualizer",
        "settings": {
            "width": settings.width,
            "height": settings.height,
            "fps": settings.fps,
            "bars": settings.bars,
            "codec": settings.codec,
            "skin": settings.skin,
            "design": settings.design,
            "player_width": settings.player_width,
            "player_height": settings.player_height,
            "margin": settings.margin,
            "bake_position": settings.bake_position,
        },
        "tracks": rendered,
    }
    manifest_path = Path(args.manifest).resolve() if args.manifest else out_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit(f"Manifest: {manifest_path}")
    return 0


def _prepare_live_manifest(jobs: dict, out_dir: Path, ffprobe: str) -> dict:
    if int(jobs.get("version") or 0) != 2:
        raise ValueError("Live preparation requires timeline jobs version 2")
    tracks = jobs.get("tracks", [])
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("Jobs file has no tracks")

    job_settings = jobs.get("settings", {})
    if not isinstance(job_settings, dict):
        raise ValueError("Jobs settings must be an object")

    def exact_int(value, name: str, minimum: int | None = None) -> int:
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

    timeline_width = exact_int(job_settings.get("timeline_width"), "Jobs setting timeline_width", 1)
    timeline_height = exact_int(job_settings.get("timeline_height"), "Jobs setting timeline_height", 1)
    player_width = exact_int(job_settings.get("player_width"), "Jobs setting player_width", 1)
    player_height = exact_int(job_settings.get("player_height"), "Jobs setting player_height", 1)
    margin = exact_int(job_settings.get("margin"), "Jobs setting margin", 0)
    if job_settings.get("bake_position") is not True:
        raise ValueError("Jobs setting bake_position must be true for live Fusion rendering")
    if margin + player_width > timeline_width or margin + player_height > timeline_height:
        raise ValueError("Live player and margin must fit inside the timeline canvas")
    if "timeline_fps" not in job_settings:
        raise ValueError("Jobs setting timeline_fps is required for live Fusion rendering")
    timeline_fps_value = job_settings["timeline_fps"]
    if isinstance(timeline_fps_value, bool) or not isinstance(timeline_fps_value, (int, float)):
        raise ValueError("Jobs setting timeline_fps must be a positive finite number")
    timeline_fps = float(timeline_fps_value)
    if not math.isfinite(timeline_fps) or timeline_fps <= 0:
        raise ValueError("Jobs setting timeline_fps must be a positive finite number")
    design = jobs.get("design") if "design" in jobs else job_settings.get("design", {})
    if design is None:
        design = {}
    if not isinstance(design, dict):
        raise ValueError("Jobs design must be an object")
    skin = jobs.get("skin") if "skin" in jobs else job_settings.get("skin", "classic")
    if not isinstance(skin, str) or skin not in SUPPORTED_SKINS:
        raise ValueError(f"Jobs skin must be one of {', '.join(SUPPORTED_SKINS)}")
    settings = RenderSettings(
        width=timeline_width,
        height=timeline_height,
        fps=max(1, int(round(timeline_fps))),
        bars=0,
        codec="qtrle",
        design=design,
        player_width=player_width,
        player_height=player_height,
        margin=margin,
        bake_position=True,
        skin=skin,
    )

    normalized_jobs = []
    seen_ids: set[str] = set()
    seen_ids_casefold: dict[str, str] = {}
    for index, job in enumerate(tracks, start=1):
        if not isinstance(job, dict):
            raise ValueError(f"Track job {index} must be an object")
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError(f"Track job {index} must have a non-empty string id")
        if job_id in seen_ids:
            raise ValueError(f"Duplicate track job id: {job_id}")
        folded_id = job_id.casefold()
        if folded_id in seen_ids_casefold:
            raise ValueError(
                f"Duplicate track job id on a case-insensitive filesystem: "
                f"{seen_ids_casefold[folded_id]} / {job_id}"
            )
        seen_ids.add(job_id)
        seen_ids_casefold[folded_id] = job_id

        source_value = job.get("source_path")
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError(f"Track job {job_id!r} must have a non-empty source path")
        path = Path(source_value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        record_frame = exact_int(job.get("record_frame"), f"Track job {job_id!r} record_frame")
        duration_frames = exact_int(job.get("duration_frames"), f"Track job {job_id!r} duration_frames", 1)
        duration = duration_frames / timeline_fps
        if "duration" in job:
            duration_value = job["duration"]
            if isinstance(duration_value, bool) or not isinstance(duration_value, (int, float)):
                raise ValueError(f"Track job {job_id!r} duration must be a finite number")
            supplied_duration = float(duration_value)
            if not math.isfinite(supplied_duration):
                raise ValueError(f"Track job {job_id!r} duration must be a finite number")
            if abs(supplied_duration - duration) > 0.5 / timeline_fps:
                raise ValueError(
                    f"Track job {job_id!r} duration differs from duration_frames/timeline_fps "
                    f"by more than half a timeline frame"
                )
        source_start_value = job.get("source_start_time", 0.0)
        if isinstance(source_start_value, bool) or not isinstance(source_start_value, (int, float)):
            raise ValueError(f"Track job {job_id!r} source_start_time must be a finite number")
        source_start_time = float(source_start_value)
        if not math.isfinite(source_start_time):
            raise ValueError(f"Track job {job_id!r} source_start_time must be a finite number")
        normalized_jobs.append(
            {
                "job": job,
                "id": job_id,
                "path": path,
                "record_frame": record_frame,
                "duration_frames": duration_frames,
                "duration": duration,
                "source_start_time": source_start_time,
            }
        )

    assets_dir = out_dir / "assets"
    live_dir = out_dir / "live"
    prepared = []
    for index, normalized in enumerate(normalized_jobs, start=1):
        job = normalized["job"]
        job_id = normalized["id"]
        path = normalized["path"]
        duration = normalized["duration"]
        _emit(f"[{index}/{len(tracks)}] Reading metadata: {path}")
        metadata = read_track_metadata(path, assets_dir, ffprobe=ffprobe)
        metadata.duration = duration
        metadata_fields = metadata.to_dict()
        hash_payload = {
            "job_id": job_id,
            "metadata": metadata_fields,
            "artwork_digest": _artwork_digest(metadata),
            "design": design,
            "skin": settings.skin,
            "timeline": {
                "width": timeline_width,
                "height": timeline_height,
            },
            "player": {
                "width": player_width,
                "height": player_height,
            },
            "margin": margin,
            "duration_frames": normalized["duration_frames"],
            "timeline_fps": timeline_fps,
            "dynamic_schema_version": LIVE_DYNAMIC_SCHEMA_VERSION,
            "static_renderer_revision": static_renderer_revision(settings.skin),
        }
        canonical_json = json.dumps(
            hash_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        content_hash = hashlib.sha256(canonical_json).hexdigest()[:16]
        readable_stem = safe_stem(job_id)[:48].rstrip("._-") or "track"
        static_target = live_dir / f"TVIZ__{readable_stem}__{content_hash}_static.png"
        _emit(f"[{index}/{len(tracks)}] Preparing live carrier: {metadata.artist} - {metadata.title}")
        static_path, dynamic_spec = render_live_carrier(metadata, static_target, settings)

        item = dict(job)
        item.update(metadata_fields)
        item.update(
            {
                "schema": "tviz.live.track",
                "id": job_id,
                "record_frame": normalized["record_frame"],
                "duration_frames": normalized["duration_frames"],
                "duration": duration,
                "source_start_time": normalized["source_start_time"],
            }
        )
        item["static_path"] = str(static_path)
        item["dynamic"] = dynamic_spec
        prepared.append(item)

    return {
        "schema": "tviz.live.manifest",
        "version": 3,
        "mode": "live_fusion",
        "timeline_name": jobs.get("timeline_name") or "Track Visualizer",
        "settings": {
            "skin": settings.skin,
            "design": settings.design,
            "player": {
                "width": settings.player_width,
                "height": settings.player_height,
                "margin": settings.margin,
            },
            "layout": {
                "timeline_width": settings.width,
                "timeline_height": settings.height,
                "bake_position": settings.bake_position,
            },
            "timeline_fps": timeline_fps,
        },
        "tracks": prepared,
    }


def command_prepare_live(args: argparse.Namespace) -> int:
    jobs_path = Path(args.jobs).resolve()
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    if not isinstance(jobs, dict):
        raise ValueError("Jobs file must contain an object")
    out_dir = Path(args.out).resolve()
    manifest = _prepare_live_manifest(jobs, out_dir, args.ffprobe)
    manifest_path = Path(args.manifest).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit(f"Manifest: {manifest_path}")
    return 0


def command_preview_style(args: argparse.Namespace) -> int:
    design = {}
    if args.design_json:
        design_path = Path(args.design_json).resolve()
        design = json.loads(design_path.read_text(encoding="utf-8"))
    settings = RenderSettings(
        width=args.width,
        height=args.height,
        fps=1,
        bars=0,
        codec="qtrle",
        design=design,
        skin=args.skin,
        player_width=args.player_width,
        player_height=args.player_height,
        margin=args.margin,
        bake_position=args.bake_position,
    )
    target = render_style_preview(
        args.out,
        settings,
        title=args.title,
        artist=args.artist,
        duration=args.duration,
        progress=args.progress,
        cover_path=args.cover,
    )
    _emit(f"Preview: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="davinci-track-visualizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("tracks", nargs="*", help="Audio files to process")
    common.add_argument("--playlist", help="JSON playlist: list of paths or {'tracks': [...]}")
    common.add_argument("--out", default="outputs", help="Output directory")
    common.add_argument("--ffmpeg", default="ffmpeg", help="Path to ffmpeg")
    common.add_argument("--ffprobe", default="ffprobe", help="Path to ffprobe")

    scan = subparsers.add_parser("scan", parents=[common], help="Read track tags and covers")
    scan.set_defaults(func=command_scan)

    render = subparsers.add_parser("render", parents=[common], help="Render alpha overlays")
    render.add_argument("--width", type=int, default=640)
    render.add_argument("--height", type=int, default=160)
    render.add_argument("--fps", type=int, default=30)
    render.add_argument("--bars", type=int, default=56)
    render.add_argument("--codec", choices=["qtrle", "prores4444"], default="qtrle")
    render.add_argument("--skin", choices=SUPPORTED_SKINS, default="classic")
    render.add_argument("--timeline-name", default="Track Visualizer")
    render.add_argument("--manifest", help="Manifest JSON output path")
    render.set_defaults(func=command_render)

    render_jobs = subparsers.add_parser("render-jobs", help="Render Resolve timeline jobs")
    render_jobs.add_argument("--jobs", required=True, help="Resolve timeline jobs JSON")
    render_jobs.add_argument("--out", help="Output directory")
    render_jobs.add_argument("--manifest", help="Manifest JSON output path")
    render_jobs.add_argument("--width", type=int)
    render_jobs.add_argument("--height", type=int)
    render_jobs.add_argument("--fps", type=int)
    render_jobs.add_argument("--bars", type=int)
    render_jobs.add_argument("--codec", choices=["qtrle", "prores4444"])
    render_jobs.add_argument("--skin", choices=SUPPORTED_SKINS)
    render_jobs.add_argument("--timeline-name")
    render_jobs.add_argument("--ffmpeg", default="ffmpeg", help="Path to ffmpeg")
    render_jobs.add_argument("--ffprobe", default="ffprobe", help="Path to ffprobe")
    render_jobs.set_defaults(func=command_render_jobs)

    prepare_live = subparsers.add_parser("prepare-live", help="Prepare static carriers for live Fusion rendering")
    prepare_live.add_argument("--jobs", required=True, help="Resolve timeline jobs v2 JSON")
    prepare_live.add_argument("--out", required=True, help="Output directory")
    prepare_live.add_argument("--manifest", required=True, help="Live Fusion manifest JSON output path")
    prepare_live.add_argument("--ffprobe", default="ffprobe", help="Path to ffprobe")
    prepare_live.set_defaults(func=command_prepare_live)

    preview = subparsers.add_parser("preview-style", help="Render a static style preview PNG")
    preview.add_argument("--out", required=True, help="Preview PNG output path")
    preview.add_argument("--design-json", help="JSON file with design settings")
    preview.add_argument("--width", type=int, default=640)
    preview.add_argument("--height", type=int, default=160)
    preview.add_argument("--title", default="Track Title Preview")
    preview.add_argument("--artist", default="Artist Name")
    preview.add_argument("--duration", type=float, default=225.0)
    preview.add_argument("--progress", type=float, default=0.36)
    preview.add_argument("--cover", help="Optional cover PNG/JPG path")
    preview.add_argument("--skin", choices=SUPPORTED_SKINS, default="classic")
    preview.add_argument("--player-width", type=int)
    preview.add_argument("--player-height", type=int)
    preview.add_argument("--margin", type=int, default=0)
    preview.add_argument("--bake-position", action="store_true")
    preview.set_defaults(func=command_preview_style)

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
