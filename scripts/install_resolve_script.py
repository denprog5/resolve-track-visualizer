from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from davinci_track_visualizer.platform_paths import executable_name, resolve_scripts_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the development Resolve menu script")
    parser.add_argument("--target", type=Path, help="Override the Resolve Utility scripts directory")
    args = parser.parse_args(argv)
    project_root = PROJECT_ROOT
    source = project_root / "resolve_scripts" / "Track Visualizer.lua"
    if not source.exists():
        raise FileNotFoundError(source)

    engine_exe = project_root / "dist" / executable_name("TrackVisualizerEngine")
    runner_exe = project_root / "dist" / executable_name("TrackVisualizerRunner")
    ffmpeg_name = executable_name("ffmpeg")
    ffprobe_name = executable_name("ffprobe")
    ffmpeg_exe = project_root / ffmpeg_name
    ffprobe_exe = project_root / ffprobe_name

    target_dir = args.target or resolve_scripts_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "Track Visualizer.lua"
    legacy_target = target_dir / "Track Visualizer.py"

    content = source.read_text(encoding="utf-8")
    content = content.replace(r"__INSTALL_ROOT__", str(project_root))
    content = content.replace(r"__ENGINE_EXECUTABLE__", str(engine_exe if engine_exe.exists() else ""))
    content = content.replace(r"__RUNNER_EXECUTABLE__", str(runner_exe if runner_exe.exists() else ""))
    content = content.replace(
        r"__FFMPEG_EXECUTABLE__",
        str(ffmpeg_exe if ffmpeg_exe.exists() else shutil.which(ffmpeg_name) or ffmpeg_name),
    )
    content = content.replace(
        r"__FFPROBE_EXECUTABLE__",
        str(ffprobe_exe if ffprobe_exe.exists() else shutil.which(ffprobe_name) or ffprobe_name),
    )
    target.write_text(content, encoding="utf-8")
    if legacy_target.exists():
        legacy_target.unlink()

    print(f"Installed Resolve script: {target}")
    print("Restart DaVinci Resolve, then open Workspace -> Scripts -> Utility -> Track Visualizer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
