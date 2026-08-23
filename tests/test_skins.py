from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from davinci_track_visualizer.metadata import TrackMetadata
from davinci_track_visualizer.render import (
    SUPPORTED_SKINS,
    RenderSettings,
    _dynamic_spec,
    _effective_design,
    _layout,
    draw_frame,
    render_live_carrier,
    render_style_preview,
)


class SkinRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = TrackMetadata(
            source_path="synthetic.wav",
            title="A Long Track Title",
            artist="Artist Name",
            album="Album",
            duration=245.8,
            cover_path=None,
        )

    def _settings(self, skin: str, scale: int = 1) -> RenderSettings:
        dimensions = {
            "classic": (640, 160),
            "minimal": (640, 176),
            "portrait_glass": (420, 640),
        }
        player_width, player_height = dimensions[skin]
        return RenderSettings(
            width=1920 * scale,
            height=1080 * scale,
            design={"glass_enabled": False},
            player_width=player_width * scale,
            player_height=player_height * scale,
            margin=48 * scale,
            bake_position=True,
            skin=skin,
        )

    def _assert_geometry_in_bounds(self, spec: dict) -> None:
        width = spec["canvas"]["width"]
        height = spec["canvas"]["height"]
        player = spec["player"]
        self.assertGreaterEqual(player["x"], 0)
        self.assertGreaterEqual(player["y"], 0)
        self.assertLessEqual(player["x"] + player["width"], width)
        self.assertLessEqual(player["y"] + player["height"], height)
        self.assertGreaterEqual(player["card_x"], 0)
        self.assertGreaterEqual(player["card_y"], 0)
        self.assertLessEqual(player["card_x"] + player["card_width"], width)
        self.assertLessEqual(player["card_y"] + player["card_height"], height)

        time_box = spec["time"]["box"]
        self.assertGreater(time_box["width"], 0)
        self.assertGreater(time_box["height"], 0)
        self.assertGreaterEqual(time_box["x"], 0)
        self.assertGreaterEqual(time_box["y"], 0)
        self.assertLessEqual(time_box["x"] + time_box["width"], width)
        self.assertLessEqual(time_box["y"] + time_box["height"], height)
        self.assertEqual(spec["time"]["x"], time_box["x"] + time_box["width"])
        self.assertEqual(spec["time"]["y"], time_box["y"] + time_box["height"] / 2.0)

        progress = spec["progress"]
        self.assertGreaterEqual(progress["x1"], 0)
        self.assertLess(progress["x1"], progress["x2"])
        self.assertLessEqual(progress["x2"], width)
        self.assertGreaterEqual(progress["y"], 0)
        self.assertLess(progress["y"], height)

    def test_supported_skins_are_strict(self) -> None:
        self.assertEqual(SUPPORTED_SKINS, ("classic", "minimal", "portrait_glass"))
        with self.assertRaisesRegex(ValueError, "Unsupported skin"):
            RenderSettings(skin="unknown")

    def test_structural_fields_are_enforced_per_skin(self) -> None:
        contradictory = {
            "show_cover": False,
            "show_brand": True,
            "show_time": False,
            "show_progress": False,
            "show_knob": True,
            "glass_enabled": False,
        }
        portrait = RenderSettings(skin="portrait_glass", design=contradictory)
        portrait_design = _effective_design(portrait)
        self.assertTrue(portrait_design["show_cover"])
        self.assertFalse(portrait_design["show_brand"])
        self.assertTrue(portrait_design["show_time"])
        self.assertTrue(portrait_design["show_progress"])
        self.assertFalse(portrait_design["show_knob"])
        self.assertTrue(portrait_design["glass_enabled"])

        minimal = RenderSettings(
            skin="minimal",
            design={key: not value if isinstance(value, bool) else value for key, value in contradictory.items()},
        )
        minimal_design = _effective_design(minimal)
        self.assertFalse(minimal_design["show_cover"])
        self.assertFalse(minimal_design["show_brand"])
        self.assertTrue(minimal_design["show_time"])
        self.assertFalse(minimal_design["show_progress"])
        self.assertFalse(minimal_design["show_knob"])
        self.assertFalse(minimal_design["glass_enabled"])

    def test_semantic_color_mapping(self) -> None:
        colors = {
            "panel_color": "#102030",
            "secondary_text_color": "#405060",
            "primary_text_color": "#708090",
            "border_color": "#A0B0C0",
            "accent_color": "#D0E0F0",
            "track_color": "#112233",
        }
        minimal = self._settings("minimal")
        minimal.design.update(colors)
        minimal_spec = _dynamic_spec(self.metadata, minimal)
        self.assertEqual(minimal_spec["time"]["color"], [16, 32, 48])
        self.assertFalse(minimal_spec["show_progress"])
        layout = _layout(minimal, _effective_design(minimal))
        static = Image.new("RGBA", (minimal.width, minimal.height), (0, 0, 0, 0))
        with tempfile.TemporaryDirectory() as temporary_dir:
            path, _ = render_live_carrier(self.metadata, Path(temporary_dir) / "minimal.png", minimal)
            with Image.open(path) as rendered:
                static = rendered.copy()
        timer_center = (
            int(layout["timer_x"]) + int(layout["timer_w"]) // 2,
            int(layout["timer_y"]) + int(layout["timer_h"]) // 2,
        )
        self.assertEqual(static.getpixel(timer_center), (112, 128, 144, 255))

        portrait = self._settings("portrait_glass")
        portrait.design.update(colors)
        portrait_spec = _dynamic_spec(self.metadata, portrait)
        self.assertEqual(portrait_spec["time"]["color"], [64, 80, 96])
        self.assertEqual(portrait_spec["progress"]["accent_color"], [208, 224, 240])
        self.assertEqual(portrait_spec["progress"]["track_color"], [17, 34, 51])

    def test_resolved_1080_and_4k_geometry_scales_exactly_and_stays_in_bounds(self) -> None:
        for skin in SUPPORTED_SKINS:
            with self.subTest(skin=skin):
                low = _dynamic_spec(self.metadata, self._settings(skin, 1))
                high = _dynamic_spec(self.metadata, self._settings(skin, 2))
                self._assert_geometry_in_bounds(low)
                self._assert_geometry_in_bounds(high)
                self.assertEqual(high["player"]["width"], low["player"]["width"] * 2)
                self.assertEqual(high["player"]["height"], low["player"]["height"] * 2)
                self.assertEqual(high["player"]["x"], low["player"]["x"] * 2)
                self.assertEqual(high["player"]["y"], low["player"]["y"] * 2)
                for field in ("x", "y", "width", "height"):
                    self.assertEqual(high["time"]["box"][field], low["time"]["box"][field] * 2)

    def test_live_static_and_legacy_dynamic_layers_share_geometry(self) -> None:
        for skin in SUPPORTED_SKINS:
            with self.subTest(skin=skin), tempfile.TemporaryDirectory() as temporary_dir:
                settings = self._settings(skin)
                static_path, live_spec = render_live_carrier(
                    self.metadata,
                    Path(temporary_dir) / f"{skin}.png",
                    settings,
                )
                self.assertEqual(live_spec, _dynamic_spec(self.metadata, settings))
                with Image.open(static_path) as image:
                    static = image.copy()
                at_start = draw_frame(self.metadata, [], 0.0, settings)
                midway = draw_frame(self.metadata, [], self.metadata.duration / 2.0, settings)
                self.assertIsNotNone(ImageChops.difference(static.convert("RGB"), at_start.convert("RGB")).getbbox())
                self.assertIsNotNone(ImageChops.difference(at_start.convert("RGB"), midway.convert("RGB")).getbbox())

    def test_classic_default_preserves_1080_layout_and_explicit_skin_output(self) -> None:
        design = {"show_cover": False, "show_brand": False, "glass_enabled": False}
        implicit = RenderSettings(
            width=1920,
            height=1080,
            design=design,
            player_width=640,
            player_height=160,
            margin=48,
            bake_position=True,
        )
        explicit = RenderSettings(
            width=1920,
            height=1080,
            design=design,
            player_width=640,
            player_height=160,
            margin=48,
            bake_position=True,
            skin="classic",
        )
        spec = _dynamic_spec(self.metadata, implicit)
        self.assertEqual(
            spec["player"],
            {
                "x": 48,
                "y": 872,
                "width": 640,
                "height": 160,
                "margin": 48,
                "bake_position": True,
                "scale": 1.0,
                "card_x": 52,
                "card_y": 876,
                "card_width": 632,
                "card_height": 152,
            },
        )
        self.assertEqual(spec["progress"]["x1"], 78)
        self.assertEqual(spec["progress"]["x2"], 660)
        self.assertEqual(spec["progress"]["y"], 1008)
        self.assertIsNone(
            ImageChops.difference(
                draw_frame(self.metadata, [], 100.0, implicit),
                draw_frame(self.metadata, [], 100.0, explicit),
            ).getbbox()
        )

    def test_minimal_full_frame_preview_keeps_timer_in_frame_corner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings = self._settings("minimal")
            target = Path(temporary_dir) / "minimal_preview.png"
            render_style_preview(target, settings, title="REACH YOUR DREAMS", artist="BRIGHT_LIGHT")
            with Image.open(target) as preview:
                self.assertEqual(preview.size, (1920, 1080))
                self.assertEqual(preview.getpixel((1919, 1079)), (255, 216, 74))


if __name__ == "__main__":
    unittest.main()
