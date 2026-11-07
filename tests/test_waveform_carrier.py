from __future__ import annotations

import math
import struct
import tempfile
import unittest
from pathlib import Path

from davinci_track_visualizer.carrier import build_carrier, carrier_frames_for, ensure_carrier, frame_rate
from davinci_track_visualizer.waveform import MIN_LEVEL, SAMPLE_RATE, analyse_waveform, levels_from_energies, window_energies


def _pcm(seconds: float, amplitude) -> list[bytes]:
    samples = int(seconds * SAMPLE_RATE)
    values = [int(amplitude(i / SAMPLE_RATE) * 30000 * math.sin(i * 0.3)) for i in range(samples)]
    data = struct.pack(f"<{len(values)}h", *values)
    return [data[i:i + 4096] for i in range(0, len(data), 4096)]


class WaveformTests(unittest.TestCase):
    def test_energies_follow_loudness(self) -> None:
        energies = window_energies(_pcm(2.0, lambda t: 0.1 if t < 1 else 1.0))
        half = len(energies) // 2
        self.assertLess(sum(energies[:half]), sum(energies[half:]))

    def test_levels_are_bounded_and_sized(self) -> None:
        energies = window_energies(_pcm(4.0, lambda t: 0.2 + 0.8 * (t / 4)))
        levels = levels_from_energies(energies, 48)
        self.assertEqual(len(levels), 48)
        self.assertTrue(all(MIN_LEVEL <= level <= 1.0 for level in levels))
        self.assertLess(levels[2], levels[-3])

    def test_compressed_master_still_has_contrast(self) -> None:
        energies = window_energies(_pcm(4.0, lambda t: 0.7 + 0.3 * (1 if int(t * 2) % 2 else 0)))
        levels = levels_from_energies(energies, 32)
        self.assertGreater(max(levels) - min(levels), 0.2)

    def test_silence_is_flat_minimum(self) -> None:
        self.assertEqual(set(levels_from_energies([0.0] * 100, 10)), {MIN_LEVEL})

    def test_cache_is_used(self) -> None:
        calls = []

        def decoder(path, ffmpeg, start, duration):
            calls.append(start)
            return _pcm(1.0, lambda t: 0.5)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "a.mp3"
            source.write_bytes(b"x")
            first = analyse_waveform(source, 16, cache_dir=Path(temporary) / "cache", decoder=decoder)
            second = analyse_waveform(source, 16, cache_dir=Path(temporary) / "cache", decoder=decoder)
            self.assertEqual(first.levels, second.levels)
            self.assertEqual(len(calls), 1)


class CarrierTests(unittest.TestCase):
    def test_ntsc_rates_are_exact(self) -> None:
        rate = frame_rate(29.97)
        self.assertAlmostEqual(rate.value, 30000 / 1001)
        self.assertNotEqual(frame_rate(29.97).tag, frame_rate(30).tag)

    def test_length_rounds_up_to_ten_minute_blocks(self) -> None:
        self.assertEqual(carrier_frames_for(10, 3600, 30), 108000)
        self.assertEqual(carrier_frames_for(108001, 3600, 30), 108000 + 18000)

    def test_carrier_is_a_quicktime_file_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, frames = ensure_carrier(Path(temporary), 300, 25, width=64, height=36, minimum_seconds=60)
            self.assertEqual(frames, 15000)
            self.assertIn("_64x36_", path.name)
            data = path.read_bytes()
            self.assertIn(b"ftypqt", data[:16])
            self.assertIn(b"moov", data)
            stamp = path.stat().st_mtime_ns
            again, _ = ensure_carrier(Path(temporary), 300, 25, width=64, height=36, minimum_seconds=60)
            self.assertEqual((again, again.stat().st_mtime_ns), (path, stamp))

    def test_carrier_size_grows_slowly_with_length(self) -> None:
        short = len(build_carrier(1000, 30, 1920, 1080))
        long = len(build_carrier(100000, 30, 1920, 1080))
        self.assertLess(long, short * 20)


if __name__ == "__main__":
    unittest.main()
