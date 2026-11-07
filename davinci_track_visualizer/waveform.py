"""Waveform analysis for the player bars.

The audio is decoded by ffmpeg to mono 16-bit PCM at a low sample rate and streamed through a
pipe, so memory stays flat for hour-long mixes. Energy is collected in short windows, grouped
into bars, converted to decibels and normalised against a high percentile instead of the
single loudest moment, so one transient does not flatten the whole track.
"""

from __future__ import annotations

import array
import hashlib
import json
import math
from operator import mul
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

ANALYSIS_REVISION = 1
SAMPLE_RATE = 4000
WINDOW_SAMPLES = 80  # 20 ms at 4 kHz
DYNAMIC_RANGE_DB = 30.0
MIN_SPAN_DB = 12.0
REFERENCE_PERCENTILE = 0.95
MIN_LEVEL = 0.08
CHUNK_BYTES = 1 << 16


def _creationflags() -> int:
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


@dataclass(frozen=True)
class Waveform:
    levels: tuple[float, ...]
    analysed_seconds: float


def window_energies(chunks: Iterable[bytes], window: int = WINDOW_SAMPLES) -> list[float]:
    """Mean square energy for consecutive windows of signed 16-bit little-endian mono PCM."""
    energies: list[float] = []
    carry = b""
    pending_sum = 0.0
    pending_count = 0
    for chunk in chunks:
        data = carry + chunk
        usable = len(data) - (len(data) % 2)
        carry = data[usable:]
        samples = array.array("h")
        samples.frombytes(data[:usable])
        if sys.byteorder != "little":
            samples.byteswap()
        index = 0
        total = len(samples)
        if pending_count:
            take = min(window - pending_count, total)
            part = samples[:take]
            pending_sum += sum(map(mul, part, part))
            pending_count += take
            index = take
            if pending_count == window:
                energies.append(pending_sum / window)
                pending_sum = 0.0
                pending_count = 0
        while index + window <= total:
            part = samples[index:index + window]
            energies.append(sum(map(mul, part, part)) / window)
            index += window
        if index < total:
            part = samples[index:]
            pending_sum += sum(map(mul, part, part))
            pending_count += len(part)
    if pending_count:
        energies.append(pending_sum / pending_count)
    return energies


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def levels_from_energies(energies: list[float], bar_count: int) -> tuple[float, ...]:
    """Group window energies into ``bar_count`` perceptually scaled levels in ``[MIN_LEVEL, 1]``."""
    if bar_count <= 0:
        raise ValueError("bar_count must be positive")
    if not energies:
        return tuple([MIN_LEVEL] * bar_count)

    count = len(energies)
    decibels: list[float] = []
    for bar in range(bar_count):
        start = (bar * count) // bar_count
        end = max(start + 1, ((bar + 1) * count) // bar_count)
        window = energies[start:min(end, count)] or [energies[min(start, count - 1)]]
        mean_square = sum(window) / len(window)
        rms = math.sqrt(mean_square) / 32768.0
        decibels.append(20.0 * math.log10(rms) if rms > 1e-7 else -140.0)

    reference = _percentile(decibels, REFERENCE_PERCENTILE)
    if reference <= -120.0:
        return tuple([MIN_LEVEL] * bar_count)
    # Loud, compressed masters only use a few dB; adapt the floor to the track's own spread
    # so its structure stays visible, but never show more than DYNAMIC_RANGE_DB of range.
    floor = max(reference - DYNAMIC_RANGE_DB, _percentile(decibels, 0.05) - 6.0)
    span = max(MIN_SPAN_DB, reference - floor)
    floor = reference - span
    shaped = []
    for value in decibels:
        normalised = max(0.0, min(1.0, (value - floor) / span))
        shaped.append(normalised ** 1.4)

    smoothed = []
    for index, value in enumerate(shaped):
        left = shaped[index - 1] if index > 0 else value
        right = shaped[index + 1] if index + 1 < len(shaped) else value
        smoothed.append(0.2 * left + 0.6 * value + 0.2 * right)
    return tuple(round(MIN_LEVEL + (1.0 - MIN_LEVEL) * value, 4) for value in smoothed)


def _decode_command(path: str | Path, ffmpeg: str, start: float, duration: float | None) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error"]
    if start > 0:
        command.extend(["-ss", f"{start:.6f}"])
    command.extend(["-i", str(path)])
    if duration is not None and duration > 0:
        command.extend(["-t", f"{duration:.6f}"])
    command.extend(["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"])
    return command


def _stream(path: str | Path, ffmpeg: str, start: float, duration: float | None) -> Iterable[bytes]:
    process = subprocess.Popen(
        _decode_command(path, ffmpeg, start, duration),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=_creationflags(),
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        while True:
            chunk = process.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            yield chunk
        error = process.stderr.read()
        code = process.wait()
        if code != 0:
            message = error.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg could not decode audio ({code}): {message[-400:]}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def _cache_key(path: Path, start: float, duration: float | None, bar_count: int) -> str:
    try:
        stat = path.stat()
        identity = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        identity = str(path)
    text = f"{ANALYSIS_REVISION}|{identity}|{start:.3f}|{duration or 0:.3f}|{bar_count}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def analyse_waveform(
    path: str | Path,
    bar_count: int,
    *,
    ffmpeg: str = "ffmpeg",
    start: float = 0.0,
    duration: float | None = None,
    cache_dir: str | Path | None = None,
    decoder: Callable[[str | Path, str, float, float | None], Iterable[bytes]] | None = None,
) -> Waveform:
    source = Path(path)
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"wave_{_cache_key(source, start, duration, bar_count)}.json"
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            levels = tuple(float(value) for value in cached["levels"])
            if len(levels) == bar_count:
                return Waveform(levels, float(cached.get("seconds", 0.0)))
        except (OSError, ValueError, KeyError, TypeError):
            pass

    energies = window_energies((decoder or _stream)(source, ffmpeg, max(0.0, start), duration))
    waveform = Waveform(levels_from_energies(energies, bar_count), len(energies) * WINDOW_SAMPLES / SAMPLE_RATE)

    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_name(f"{cache_path.name}.tmp.{os.getpid()}")
            temporary.write_text(
                json.dumps({"levels": list(waveform.levels), "seconds": waveform.analysed_seconds}),
                encoding="utf-8",
            )
            os.replace(temporary, cache_path)
        except OSError:
            pass
    return waveform
