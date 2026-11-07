from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from davinci_track_visualizer import cli
from davinci_track_visualizer.metadata import TrackMetadata, join_artists
from davinci_track_visualizer.waveform import Waveform


def _jobs(directory: Path, count: int = 2, **overrides) -> dict:
    tracks = []
    for index in range(count):
        source = directory / f"track_{index}.mp3"
        source.write_bytes(b"not really audio")
        tracks.append({
            "id": f"clip-{index}",
            "source_path": str(source),
            "record_frame": 86400 + index * 900,
            "duration_frames": 900,
            "source_start_time": 30.0 if index == 1 else 0.0,
        })
    data = {
        "version": cli.JOBS_VERSION,
        "skin": "classic",
        "design": {},
        "timeline": {"name": "Mix", "width": 1280, "height": 720, "fps": 30},
        "tracks": tracks,
    }
    data.update(overrides)
    return data


def _metadata(path, assets_dir, ffprobe="ffprobe") -> TrackMetadata:
    name = Path(path).stem
    if name == "track_bad":
        raise RuntimeError("broken file")
    return TrackMetadata(str(path), f"Title {name}", "Artist", "Album", 200.0, None)


def _waveform(path, bar_count, **kwargs) -> Waveform:
    return Waveform(tuple(0.5 for _ in range(bar_count)), 200.0)


class ParseJobsTests(unittest.TestCase):
    def test_valid_jobs_parse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            jobs = cli.parse_jobs(_jobs(Path(temporary)))
            self.assertEqual(len(jobs.tracks), 2)
            self.assertEqual(jobs.tracks[1].source_start, 30.0)
            self.assertEqual(jobs.design["anchor"], "bottom_left")

    def test_invalid_jobs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = _jobs(Path(temporary))
            cases = []
            cases.append(dict(base, version=2))
            cases.append(dict(base, skin="legacy"))
            cases.append(dict(base, tracks=[]))
            cases.append(dict(base, timeline=dict(base["timeline"], width=9000)))
            cases.append(dict(base, timeline=dict(base["timeline"], fps=0)))
            duplicate = copy.deepcopy(base)
            duplicate["tracks"][1]["id"] = "CLIP-0"
            cases.append(duplicate)
            fractional = copy.deepcopy(base)
            fractional["tracks"][0]["record_frame"] = 1.5
            cases.append(fractional)
            missing = copy.deepcopy(base)
            missing["tracks"][0]["source_path"] = str(Path(temporary) / "missing.mp3")
            cases.append(missing)
            for case in cases:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    cli.parse_jobs(case)


@patch.object(cli, "analyse_waveform", _waveform)
@patch.object(cli, "read_track_metadata", _metadata)
class PrepareTests(unittest.TestCase):
    def test_manifest_v4_has_comps_and_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = cli.prepare(cli.parse_jobs(_jobs(root)), root / "out", ffmpeg="ffmpeg", ffprobe="ffprobe", workers=2)
            self.assertEqual((manifest["schema"], manifest["version"]), ("tviz.manifest", 4))
            self.assertTrue(Path(manifest["carrier"]["path"]).is_file())
            self.assertIn("_1280x720_", Path(manifest["carrier"]["path"]).name)
            self.assertEqual([track["id"] for track in manifest["tracks"]], ["clip-0", "clip-1"])
            self.assertEqual(manifest["failed"], [])
            second = manifest["tracks"][1]
            self.assertEqual(second["offset_seconds"], 30.0)
            self.assertEqual(second["total_seconds"], 200.0)
            comp = Path(second["comp_path"]).read_text(encoding="utf-8")
            self.assertTrue(Path(second["comp_path"]).name.isascii())
            self.assertIn("Loader", comp)
            self.assertIn("TextPlus", comp)
            json.dumps(manifest)

    def test_clip_progress_basis_uses_clip_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = _jobs(root, design={"progress_basis": "clip"})
            manifest = cli.prepare(cli.parse_jobs(data), root / "out", ffmpeg="ffmpeg", ffprobe="ffprobe", workers=1)
            for track in manifest["tracks"]:
                self.assertEqual(track["offset_seconds"], 0.0)
                self.assertEqual(track["total_seconds"], 30.0)

    def test_one_broken_track_does_not_fail_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = _jobs(root)
            bad = root / "track_bad.mp3"
            bad.write_bytes(b"x")
            data["tracks"].append(dict(data["tracks"][0], id="bad", source_path=str(bad)))
            manifest = cli.prepare(cli.parse_jobs(data), root / "out", ffmpeg="ffmpeg", ffprobe="ffprobe", workers=1)
            self.assertEqual(len(manifest["tracks"]), 2)
            self.assertEqual(manifest["failed"][0]["id"], "bad")
            self.assertIn("broken file", manifest["failed"][0]["error"])

    def test_all_tracks_failing_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad = root / "track_bad.mp3"
            bad.write_bytes(b"x")
            data = _jobs(root, count=1)
            data["tracks"][0]["source_path"] = str(bad)
            with self.assertRaises(RuntimeError):
                cli.prepare(cli.parse_jobs(data), root / "out", ffmpeg="ffmpeg", ffprobe="ffprobe", workers=1)

    def test_design_change_changes_layer_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = cli.prepare(cli.parse_jobs(_jobs(root, count=1)), root / "out", ffmpeg="f", ffprobe="f", workers=1)
            changed = _jobs(root, count=1, design={"accent_color": "#FF0000"})
            second = cli.prepare(cli.parse_jobs(changed), root / "out", ffmpeg="f", ffprobe="f", workers=1)
            self.assertNotEqual(first["tracks"][0]["card_path"], second["tracks"][0]["card_path"])


class MetadataTests(unittest.TestCase):
    def test_slash_separated_artists_are_joined(self) -> None:
        self.assertEqual(join_artists("4444 OF A KIND/D-Block & S-te-Fan/Sub Zero Project"), "4444 OF A KIND, D-Block & S-te-Fan, Sub Zero Project")
        self.assertEqual(join_artists("AC/DC"), "AC/DC")
        self.assertEqual(join_artists("Solo"), "Solo")


if __name__ == "__main__":
    unittest.main()
