from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from davinci_track_visualizer.cli import _prepare_live_manifest, _settings_from_args_or_jobs, command_prepare_live
from davinci_track_visualizer.metadata import TrackMetadata, safe_stem
from davinci_track_visualizer.render import STATIC_RENDERER_REVISION, RenderSettings, render_live_carrier


class LiveCarrierTests(unittest.TestCase):
    def test_static_carrier_is_full_frame_rgba_without_dynamic_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            target = Path(temporary_dir) / "carrier.png"
            metadata = TrackMetadata(
                source_path="synthetic.wav",
                title="Unicode title: Песня",
                artist="Исполнитель",
                album="Album",
                duration=125.8,
                cover_path=None,
            )
            settings = RenderSettings(
                width=640,
                height=360,
                design={
                    "show_cover": False,
                    "glass_enabled": False,
                    "panel_color": "#102030",
                    "panel_alpha": 255,
                    "show_time": True,
                    "show_progress": True,
                    "show_knob": True,
                },
                player_width=320,
                player_height=100,
                margin=0,
                bake_position=True,
            )

            rendered_path, dynamic = render_live_carrier(metadata, target, settings)

            self.assertEqual(rendered_path, target)
            with Image.open(target) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (640, 360))
                self.assertEqual(image.getpixel((639, 0))[3], 0)
                progress = dynamic["progress"]
                midpoint = ((progress["x1"] + progress["x2"]) // 2, progress["y"])
                self.assertEqual(image.getpixel(midpoint), (16, 32, 48, 255))

            self.assertEqual(dynamic["canvas"], {"width": 640, "height": 360})
            self.assertEqual(dynamic["duration_seconds"], 125.8)
            self.assertEqual(dynamic["total_duration_label"], "02:05")
            self.assertEqual(dynamic["player"]["y"], 260)
            time_box = dynamic["time"]["box"]
            self.assertEqual(dynamic["time"]["x"], time_box["x"] + time_box["width"])
            self.assertEqual(dynamic["time"]["y"], time_box["y"] + time_box["height"] / 2)
            self.assertEqual(dynamic["time"]["anchor"], "right_center")
            self.assertEqual(dynamic["time"]["horizontal_alignment"], "right")
            self.assertEqual(dynamic["time"]["vertical_alignment"], "center")
            self.assertEqual(dynamic["time"]["font_family"], "Segoe UI")
            self.assertEqual(dynamic["version"], 3)
            self.assertEqual(dynamic["skin"], "classic")
            self.assertTrue(dynamic["show_time"])
            self.assertTrue(dynamic["show_progress"])
            self.assertTrue(dynamic["show_knob"])
            json.dumps(dynamic)

    def test_margin_zero_is_preserved_for_job_settings(self) -> None:
        args = argparse.Namespace(width=None, height=None, fps=None, bars=None, codec=None)
        settings = _settings_from_args_or_jobs(args, {"settings": {"margin": 0}})
        self.assertEqual(settings.margin, 0)


class PrepareLiveCommandTests(unittest.TestCase):
    def _jobs(self, source: Path, ids: tuple[str, ...] = ("clip_é_трек",)) -> dict:
        return {
            "version": 2,
            "timeline_name": "Таймлайн é",
            "design": {"show_cover": False, "glass_enabled": False},
            "settings": {
                "timeline_width": 800,
                "timeline_height": 450,
                "timeline_fps": 24,
                "player_width": 320,
                "player_height": 100,
                "margin": 0,
                "bake_position": True,
            },
            "tracks": [
                {
                    "id": job_id,
                    "source_path": str(source),
                    "record_frame": 42 + index * 108,
                    "duration": 4.5,
                    "duration_frames": 108,
                    "source_start_time": 1.25,
                    "timeline_item_name": f"Песня é {index}",
                }
                for index, job_id in enumerate(ids)
            ],
        }

    def _metadata(self, path, assets_dir, ffprobe="ffprobe") -> TrackMetadata:
        return TrackMetadata(
            source_path=str(Path(path).resolve()),
            title="Заголовок é",
            artist="Артист",
            album="Альбом",
            duration=999.0,
            cover_path=None,
        )

    def test_prepare_live_writes_v3_manifest_and_png_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "аудио é.mp3"
            source.write_bytes(b"synthetic")
            jobs_path = root / "jobs.json"
            out_dir = root / "output"
            manifest_path = root / "nested" / "live_manifest.json"
            jobs = self._jobs(source)
            jobs_path.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")

            def fake_metadata(path, assets_dir, ffprobe="ffprobe"):
                self.assertEqual(Path(path), source.resolve())
                self.assertEqual(ffprobe, "custom-ffprobe")
                return self._metadata(path, assets_dir, ffprobe)

            args = argparse.Namespace(
                jobs=str(jobs_path),
                out=str(out_dir),
                manifest=str(manifest_path),
                ffprobe="custom-ffprobe",
            )
            with (
                patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=fake_metadata),
                patch("davinci_track_visualizer.cli.render_overlay") as render_overlay_mock,
                patch("davinci_track_visualizer.render.subprocess.Popen") as popen_mock,
                patch("davinci_track_visualizer.metadata.subprocess.run") as subprocess_run_mock,
            ):
                result = command_prepare_live(args)
                render_overlay_mock.assert_not_called()
                popen_mock.assert_not_called()
                subprocess_run_mock.assert_not_called()

            self.assertEqual(result, 0)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "tviz.live.manifest")
            self.assertEqual(manifest["version"], 3)
            self.assertEqual(manifest["mode"], "live_fusion")
            self.assertEqual(manifest["timeline_name"], "Таймлайн é")
            self.assertEqual(manifest["settings"]["timeline_fps"], 24.0)
            self.assertEqual(manifest["settings"]["skin"], "classic")
            self.assertEqual(manifest["settings"]["player"]["margin"], 0)
            self.assertEqual(manifest["settings"]["layout"]["timeline_width"], 800)

            track = manifest["tracks"][0]
            self.assertEqual(track["schema"], "tviz.live.track")
            self.assertEqual(track["record_frame"], 42)
            self.assertEqual(track["timeline_item_name"], "Песня é 0")
            self.assertEqual(track["title"], "Заголовок é")
            self.assertEqual(track["duration"], 4.5)
            self.assertEqual(track["dynamic"]["duration_seconds"], 4.5)
            expected_static = Path(track["static_path"])
            self.assertEqual(expected_static.parent, (out_dir / "live").resolve())
            self.assertRegex(expected_static.name, r"^TVIZ__[A-Za-z0-9._-]{1,48}__[0-9a-f]{16}_static\.png$")
            with Image.open(expected_static) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (800, 450))
                self.assertEqual(image.getpixel((799, 0))[3], 0)
            self.assertEqual(list(out_dir.rglob("*.mov")), [])

    def test_unicode_ids_with_same_safe_stem_have_distinct_bounded_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            ids = ("трек", "歌曲")
            self.assertEqual(safe_stem(ids[0]), safe_stem(ids[1]))
            jobs = self._jobs(source, ids)

            with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                manifest = _prepare_live_manifest(jobs, root / "out", "ffprobe")

            paths = [Path(track["static_path"]) for track in manifest["tracks"]]
            self.assertNotEqual(paths[0], paths[1])
            for path in paths:
                path.name.encode("ascii")
                self.assertLessEqual(len(path.name), 96)
                self.assertTrue(path.is_file())

    def test_duplicate_ids_are_rejected_case_sensitively_and_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            for ids in (("duplicate", "duplicate"), ("Duplicate", "duplicate")):
                with self.subTest(ids=ids):
                    with self.assertRaisesRegex(ValueError, "Duplicate track job id"):
                        _prepare_live_manifest(self._jobs(source, ids), root / "out", "ffprobe")

            for invalid_id in (None, "", "   "):
                with self.subTest(invalid_id=invalid_id):
                    jobs = self._jobs(source)
                    jobs["tracks"][0]["id"] = invalid_id
                    with self.assertRaisesRegex(ValueError, "non-empty string id"):
                        _prepare_live_manifest(jobs, root / "out", "ffprobe")

    def test_missing_or_noninteger_frame_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            cases = (
                ("duration_frames", None),
                ("duration_frames", 10.5),
                ("duration_frames", 0),
                ("record_frame", None),
                ("record_frame", 42.5),
            )
            for field, value in cases:
                with self.subTest(field=field, value=value):
                    jobs = self._jobs(source)
                    if value is None:
                        jobs["tracks"][0].pop(field)
                    else:
                        jobs["tracks"][0][field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        _prepare_live_manifest(jobs, root / "out", "ffprobe")

    def test_duration_must_match_frames_and_output_uses_canonical_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            inconsistent = self._jobs(source)
            inconsistent["tracks"][0]["duration"] = 4.6
            with self.assertRaisesRegex(ValueError, "more than half a timeline frame"):
                _prepare_live_manifest(inconsistent, root / "out", "ffprobe")

            missing_fps = self._jobs(source)
            missing_fps["settings"].pop("timeline_fps")
            with self.assertRaisesRegex(ValueError, "timeline_fps is required"):
                _prepare_live_manifest(missing_fps, root / "out", "ffprobe")

            accepted = self._jobs(source)
            accepted["tracks"][0]["duration"] = 4.49
            with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                manifest = _prepare_live_manifest(accepted, root / "out", "ffprobe")
            track = manifest["tracks"][0]
            self.assertEqual(track["duration"], 4.5)
            self.assertEqual(track["dynamic"]["duration_seconds"], 4.5)

    def test_invalid_live_layout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")

            not_baked = self._jobs(source)
            not_baked["settings"]["bake_position"] = False
            with self.assertRaisesRegex(ValueError, "bake_position must be true"):
                _prepare_live_manifest(not_baked, root / "out", "ffprobe")

            outside = self._jobs(source)
            outside["settings"]["player_width"] = 800
            outside["settings"]["margin"] = 1
            with self.assertRaisesRegex(ValueError, "fit inside the timeline canvas"):
                _prepare_live_manifest(outside, root / "out", "ffprobe")

    def test_metadata_overrides_conflicting_job_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            jobs = self._jobs(source)
            jobs["tracks"][0].update(
                {
                    "title": "Wrong title",
                    "artist": "Wrong artist",
                    "album": "Wrong album",
                    "record_frame": 42.0,
                    "duration_frames": 108.0,
                    "duration": 4.49,
                    "source_start_time": 1,
                }
            )

            with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                track = _prepare_live_manifest(jobs, root / "out", "ffprobe")["tracks"][0]

            self.assertEqual(track["title"], "Заголовок é")
            self.assertEqual(track["artist"], "Артист")
            self.assertEqual(track["album"], "Альбом")
            self.assertEqual(track["record_frame"], 42)
            self.assertEqual(track["duration_frames"], 108)
            self.assertEqual(track["duration"], 4.5)
            self.assertEqual(track["source_start_time"], 1.0)

    def test_changed_design_changes_content_hash_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            first_jobs = self._jobs(source)
            second_jobs = copy.deepcopy(first_jobs)
            first_jobs["design"]["panel_color"] = "#102030"
            second_jobs["design"]["panel_color"] = "#203040"

            with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                first = _prepare_live_manifest(first_jobs, root / "out", "ffprobe")
                second = _prepare_live_manifest(second_jobs, root / "out", "ffprobe")

            self.assertNotEqual(first["tracks"][0]["static_path"], second["tracks"][0]["static_path"])

            changed_metadata = self._metadata(source, root / "assets")
            changed_metadata.title = "Другой заголовок"
            with patch("davinci_track_visualizer.cli.read_track_metadata", return_value=changed_metadata):
                third = _prepare_live_manifest(first_jobs, root / "out", "ffprobe")
            self.assertNotEqual(first["tracks"][0]["static_path"], third["tracks"][0]["static_path"])

    def test_skin_is_manifested_and_changes_content_hash_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            paths = {}

            for skin in ("classic", "minimal", "portrait_glass"):
                jobs = self._jobs(source)
                jobs["skin"] = skin
                if skin == "portrait_glass":
                    jobs["settings"]["player_height"] = 400
                with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                    manifest = _prepare_live_manifest(jobs, root / "out", "ffprobe")
                self.assertEqual(manifest["version"], 3)
                self.assertEqual(manifest["settings"]["skin"], skin)
                self.assertEqual(manifest["tracks"][0]["dynamic"]["skin"], skin)
                self.assertEqual(manifest["tracks"][0]["dynamic"]["version"], 3)
                paths[skin] = manifest["tracks"][0]["static_path"]

            self.assertEqual(len(set(paths.values())), 3)

    def test_static_renderer_revision_changes_content_hash_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            jobs = self._jobs(source)

            with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                first = _prepare_live_manifest(jobs, root / "out", "ffprobe")
            with (
                patch("davinci_track_visualizer.render.STATIC_RENDERER_REVISION", STATIC_RENDERER_REVISION + 1),
                patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata),
            ):
                second = _prepare_live_manifest(jobs, root / "out", "ffprobe")

            self.assertNotEqual(first["tracks"][0]["static_path"], second["tracks"][0]["static_path"])

    def test_changed_fallback_logo_bytes_change_content_hash_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.mp3"
            source.write_bytes(b"synthetic")
            logo = root / "логотип.png"
            jobs = self._jobs(source)
            jobs["design"]["show_cover"] = True
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(logo)

            with patch.dict(os.environ, {"DAVINCI_TRACK_VISUALIZER_LOGO": str(logo)}):
                with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                    first = _prepare_live_manifest(jobs, root / "out", "ffprobe")

                Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(logo)
                with patch("davinci_track_visualizer.cli.read_track_metadata", side_effect=self._metadata):
                    second = _prepare_live_manifest(jobs, root / "out", "ffprobe")

            self.assertNotEqual(first["tracks"][0]["static_path"], second["tracks"][0]["static_path"])


if __name__ == "__main__":
    unittest.main()
