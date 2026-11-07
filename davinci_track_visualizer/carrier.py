"""Transparent QuickTime carrier clips for live Fusion overlays.

Resolve clamps PNG stills to the user's standard still duration, so every overlay sits on a
video clip whose pixels are never shown: the Fusion composition attached to the clip renders
the card itself. This module writes that carrier without ffmpeg.

The file is a QuickTime movie with one Animation (``rle ``) video track. All samples are
identical fully transparent key frames; every chunk offset points at the same encoded frame,
so a one-hour carrier is a few hundred kilobytes and any frame decodes independently.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

CARRIER_SCHEMA = 1
CARRIER_SIZE = 16


@dataclass(frozen=True)
class FrameRate:
    timescale: int
    frame_duration: int

    @property
    def value(self) -> float:
        return self.timescale / self.frame_duration

    @property
    def tag(self) -> str:
        return f"{self.timescale}_{self.frame_duration}"


_NTSC_RATES = {23.976: 24000, 29.97: 30000, 47.952: 48000, 59.94: 60000, 119.88: 120000}


def frame_rate(fps: float) -> FrameRate:
    """Return an exact QuickTime timescale/duration pair for a Resolve frame rate."""
    value = float(fps)
    if not value > 0 or value > 1000:
        raise ValueError(f"Unsupported frame rate: {fps!r}")
    for rate, timescale in _NTSC_RATES.items():
        if abs(value - rate) < 0.002:
            return FrameRate(timescale, 1001)
    rounded = round(value)
    if abs(value - rounded) < 0.0005:
        return FrameRate(int(rounded) * 100, 100)
    exact = Fraction(value).limit_denominator(1001)
    return FrameRate(exact.numerator, exact.denominator)


def _atom(kind: bytes, *parts: bytes) -> bytes:
    payload = b"".join(parts)
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _full_atom(kind: bytes, version: int, flags: int, *parts: bytes) -> bytes:
    return _atom(kind, struct.pack(">I", (version << 24) | flags), *parts)


_MATRIX = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)


def _transparent_frame(width: int, height: int) -> bytes:
    """Encode one fully transparent 32-bit Animation key frame."""
    line = bytearray([1])  # skip code: no pixels skipped
    remaining = width
    while remaining > 0:
        run = min(remaining, 127)
        line += struct.pack(">b", -run) + b"\x00\x00\x00\x00"
        remaining -= run
    line += b"\xff"  # end of line
    body = struct.pack(">H", 0) + bytes(line) * height + b"\x00"
    return struct.pack(">I", 4 + len(body)) + body


def build_carrier(frame_count: int, fps: float, width: int = CARRIER_SIZE, height: int = CARRIER_SIZE) -> bytes:
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    if width <= 0 or height <= 0 or width > 8192 or height > 8192:
        raise ValueError("Invalid carrier size")
    rate = frame_rate(fps)
    frame = _transparent_frame(width, height)

    ftyp = _atom(b"ftyp", b"qt  ", struct.pack(">I", 0x20050300), b"qt  ")
    mdat_header_size = 8
    frame_offset = len(ftyp) + mdat_header_size
    mdat = _atom(b"mdat", frame)

    duration = frame_count * rate.frame_duration
    mvhd = _full_atom(
        b"mvhd", 0, 0,
        struct.pack(">IIII", 0, 0, rate.timescale, duration),
        struct.pack(">IH", 0x00010000, 0x0100), b"\x00" * 10, _MATRIX,
        struct.pack(">6I", 0, 0, 0, 0, 0, 0), struct.pack(">I", 2),
    )
    tkhd = _full_atom(
        b"tkhd", 0, 0x3,
        struct.pack(">IIIII", 0, 0, 1, 0, duration), b"\x00" * 8,
        struct.pack(">hhhH", 0, 0, 0, 0), _MATRIX,
        struct.pack(">II", width << 16, height << 16),
    )
    elst = _full_atom(b"elst", 0, 0, struct.pack(">IIIhh", 1, duration, 0, 1, 0))
    mdhd = _full_atom(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, rate.timescale, duration, 0, 0))
    hdlr_media = _full_atom(b"hdlr", 0, 0, b"mhlr", b"vide", b"appl", struct.pack(">II", 0, 0), b"\x00")
    vmhd = _full_atom(b"vmhd", 0, 0x1, struct.pack(">HHHH", 0x40, 0x8000, 0x8000, 0x8000))
    hdlr_data = _full_atom(b"hdlr", 0, 0, b"dhlr", b"alis", b"appl", struct.pack(">II", 0, 0), b"\x00")
    dref = _full_atom(b"dref", 0, 0, struct.pack(">I", 1), _full_atom(b"alis", 0, 0x1))
    compressor = b"Animation"
    sample_entry = _atom(
        b"rle ",
        b"\x00" * 6, struct.pack(">H", 1),
        struct.pack(">HH", 0, 0), b"appl",
        struct.pack(">II", 0, 1024),
        struct.pack(">HH", width, height),
        struct.pack(">II", 72 << 16, 72 << 16),
        struct.pack(">IH", 0, 1),
        bytes([len(compressor)]) + compressor + b"\x00" * (31 - len(compressor)),
        struct.pack(">hh", 32, -1),
    )
    stsd = _full_atom(b"stsd", 0, 0, struct.pack(">I", 1), sample_entry)
    stts = _full_atom(b"stts", 0, 0, struct.pack(">III", 1, frame_count, rate.frame_duration))
    stsc = _full_atom(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1))
    stsz = _full_atom(b"stsz", 0, 0, struct.pack(">II", len(frame), frame_count))
    stco = _full_atom(b"stco", 0, 0, struct.pack(">I", frame_count), struct.pack(">I", frame_offset) * frame_count)
    stbl = _atom(b"stbl", stsd, stts, stsc, stsz, stco)
    minf = _atom(b"minf", vmhd, hdlr_data, _atom(b"dinf", dref), stbl)
    mdia = _atom(b"mdia", mdhd, hdlr_media, minf)
    trak = _atom(b"trak", tkhd, _atom(b"edts", elst), mdia)
    moov = _atom(b"moov", mvhd, trak)
    return ftyp + mdat + moov


def carrier_frames_for(duration_frames: int, minimum_seconds: int, fps: float) -> int:
    """Round carrier length up to whole ten-minute blocks so one file serves many runs."""
    block = max(1, round(frame_rate(fps).value * 600))
    needed = max(int(duration_frames), int(round(minimum_seconds * frame_rate(fps).value)), 1)
    return ((needed + block - 1) // block) * block


def ensure_carrier(
    directory: Path,
    duration_frames: int,
    fps: float,
    *,
    width: int = CARRIER_SIZE,
    height: int = CARRIER_SIZE,
    minimum_seconds: int = 3600,
) -> tuple[Path, int]:
    """Return a carrier at least ``duration_frames`` long, writing it atomically if missing.

    The Fusion composition attached to the carrier inherits its frame size, so callers pass
    the timeline resolution.
    """
    rate = frame_rate(fps)
    frames = carrier_frames_for(duration_frames, minimum_seconds, fps)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"TVIZ_carrier_v{CARRIER_SCHEMA}_{width}x{height}_{rate.tag}_{frames}.mov"
    if target.is_file() and target.stat().st_size > 0:
        return target, frames
    data = build_carrier(frames, fps, width, height)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return target, frames
