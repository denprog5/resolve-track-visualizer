from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _creationflags() -> int:
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def ffprobe_duration(path: str | Path, ffprobe: str = "ffprobe") -> float:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
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
    value = data.get("format", {}).get("duration")
    return float(value or 0.0)
