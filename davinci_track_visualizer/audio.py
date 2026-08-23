from __future__ import annotations

import array
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _creationflags() -> int:
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


@dataclass
class AudioAnalysis:
    duration: float
    levels: list[float]


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


def decode_pcm_mono(
    path: str | Path,
    sample_rate: int = 12000,
    ffmpeg: str = "ffmpeg",
    start_time: float = 0.0,
    duration: float | None = None,
) -> array.array:
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if start_time > 0:
        cmd.extend(["-ss", f"{start_time:.6f}"])
    cmd.extend(["-i", str(path)])
    if duration is not None and duration > 0:
        cmd.extend(["-t", f"{duration:.6f}"])
    cmd.extend([
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "pipe:1",
    ])
    result = subprocess.run(cmd, check=True, capture_output=True, creationflags=_creationflags())
    samples = array.array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def compute_bar_levels(samples: array.array, bar_count: int) -> list[float]:
    if bar_count <= 0:
        raise ValueError("bar_count must be positive")
    if not samples:
        return [0.12] * bar_count

    sample_count = len(samples)
    window = max(1, sample_count // bar_count)
    rms_values: list[float] = []

    for idx in range(bar_count):
        start = idx * window
        end = sample_count if idx == bar_count - 1 else min(sample_count, start + window)
        chunk_len = max(1, end - start)
        step = max(1, chunk_len // 3000)
        total = 0.0
        count = 0
        for sample in samples[start:end:step]:
            total += float(sample) * float(sample)
            count += 1
        rms = math.sqrt(total / max(1, count))
        rms_values.append(rms)

    peak = max(rms_values) or 1.0
    levels = []
    for rms in rms_values:
        normalized = max(0.0, min(1.0, rms / peak))
        levels.append(0.08 + 0.92 * math.sqrt(normalized))
    return levels


def analyze_audio(
    path: str | Path,
    bar_count: int = 56,
    sample_rate: int = 12000,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    start_time: float = 0.0,
    duration: float | None = None,
) -> AudioAnalysis:
    samples = decode_pcm_mono(
        path,
        sample_rate=sample_rate,
        ffmpeg=ffmpeg,
        start_time=start_time,
        duration=duration,
    )
    measured_duration = len(samples) / float(sample_rate) if samples else ffprobe_duration(path, ffprobe)
    if duration is not None and duration > 0:
        measured_duration = min(measured_duration, duration)
    levels = compute_bar_levels(samples, bar_count)
    return AudioAnalysis(duration=measured_duration, levels=levels)
