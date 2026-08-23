from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from davinci_track_visualizer.cli import _prepare_live_manifest
from davinci_track_visualizer.render import default_design


OUTPUT = ROOT / "outputs" / "test" / "production_probe"
SOURCES = (
    ROOT / "outputs" / "test" / "test.wav",
    ROOT / "outputs" / "test" / "encoding_xøugar.mp3",
    ROOT / "outputs" / "test" / "encoding_beyoncé_café.mp3",
)
SKINS = {
    "classic": (640, 160),
    "minimal": (640, 176),
    "portrait_glass": (420, 640),
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path in SOURCES if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))

    generated_audio_dir = OUTPUT / "generated_audio"
    generated_audio_dir.mkdir(parents=True, exist_ok=True)
    production_sources = []
    for index in range(1, 50):
        source = generated_audio_dir / f"production_track_{index:03d}.wav"
        if not source.is_file():
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 800)
        production_sources.append(source)

    case_lines: list[str] = []
    for skin, (player_width, player_height) in SKINS.items():
        case_dir = OUTPUT / skin
        sources = tuple(production_sources) if skin == "classic" else SOURCES
        duration_frames = 600 if skin == "classic" else 120
        jobs = {
            "version": 2,
            "skin": skin,
            "timeline_name": "Timeline 1",
            "output_dir": str(case_dir.resolve()),
            "design": default_design(skin),
            "fallback_logo_path": str((ROOT / "aplus.png").resolve()),
            "settings": {
                "width": 1920,
                "height": 1080,
                "skin": skin,
                "design": default_design(skin),
                "timeline_width": 1920,
                "timeline_height": 1080,
                "timeline_fps": 24,
                "player_width": player_width,
                "player_height": player_height,
                "margin": 48,
                "bake_position": True,
                "fps": 15,
                "bars": 0,
                "codec": "qtrle",
            },
            "tracks": [
                {
                    "id": f"production_probe_{index}",
                    "source_path": str(source.resolve()),
                    "record_frame": 86400 + (index - 1) * duration_frames,
                    "duration_frames": duration_frames,
                    "duration": duration_frames / 24.0,
                    "source_start_time": 0.0,
                    "timeline_item_name": source.name,
                }
                for index, source in enumerate(sources, start=1)
            ],
        }
        case_dir.mkdir(parents=True, exist_ok=True)
        jobs_path = case_dir / "jobs.json"
        manifest_path = case_dir / "live_manifest.json"
        jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = _prepare_live_manifest(jobs, case_dir, "ffprobe")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        case_lines.append(
            f"{jobs_path.resolve()}|{manifest_path.resolve()}|{skin}|{len(sources)}|{duration_frames}"
        )

    cases_path = OUTPUT / "cases.txt"
    cases_path.write_text("\n".join(case_lines) + "\n", encoding="utf-8")
    print(cases_path.resolve())


if __name__ == "__main__":
    main()
