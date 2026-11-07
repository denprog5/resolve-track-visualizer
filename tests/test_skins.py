from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from davinci_track_visualizer.render import (
    TrackInfo,
    compose_player,
    flatten_player,
    player_bounds,
    readout_text,
    render_preview,
    render_track_layers,
    sample_levels,
)
from davinci_track_visualizer.skins import (
    ANCHORS,
    COLOR_KEYS,
    DEFAULT_PALETTES,
    INT_RANGES,
    PALETTE_KEYS,
    PALETTES,
    SKIN_BASE_SIZES,
    SKIN_FEATURES,
    SUPPORTED_SKINS,
    catalog,
    check_skin,
    default_design,
    effective_flags,
    normalize_color,
    normalize_design,
)

INFO = TrackInfo(title="Песня / Song", artist="Исполнитель", cover_path=None)


class SkinCatalogTests(unittest.TestCase):
    def test_supported_skins_are_strict(self) -> None:
        for skin in SUPPORTED_SKINS:
            self.assertEqual(check_skin(skin), skin)
        for bad in ("Classic", "", None, "legacy"):
            with self.assertRaises(ValueError):
                check_skin(bad)

    def test_every_skin_has_size_features_and_palette(self) -> None:
        for skin in SUPPORTED_SKINS:
            self.assertIn(skin, SKIN_BASE_SIZES)
            self.assertIn(skin, SKIN_FEATURES)
            self.assertIn(DEFAULT_PALETTES[skin], PALETTES)

    def test_default_design_uses_the_skin_palette(self) -> None:
        for skin in SUPPORTED_SKINS:
            design = default_design(skin)
            palette = PALETTES[DEFAULT_PALETTES[skin]]
            for key in PALETTE_KEYS:
                self.assertEqual(design[key], palette[key], f"{skin}.{key}")

    def test_palettes_define_every_palette_key(self) -> None:
        for name, palette in PALETTES.items():
            self.assertEqual(set(palette), set(PALETTE_KEYS), name)
            for key in COLOR_KEYS:
                if key in palette:
                    self.assertRegex(palette[key], r"^#[0-9A-F]{6}$", f"{name}.{key}")

    def test_catalog_is_json_safe_and_complete(self) -> None:
        import json

        data = json.loads(json.dumps(catalog()))
        self.assertEqual(data["skins"], list(SUPPORTED_SKINS))
        self.assertEqual(data["enums"]["anchor"], list(ANCHORS))
        self.assertEqual(data["palette_order"], list(PALETTES))
        self.assertEqual(data["int_ranges"]["scale"], list(INT_RANGES["scale"]))


class NormalizeDesignTests(unittest.TestCase):
    def test_colors_are_normalized_or_fall_back(self) -> None:
        self.assertEqual(normalize_color("abc", "#000000"), "#AABBCC")
        self.assertEqual(normalize_color("#12ab34", "#000000"), "#12AB34")
        self.assertEqual(normalize_color("blue", "#010203"), "#010203")

    def test_ranges_enums_and_booleans_are_enforced(self) -> None:
        design = normalize_design(
            {
                "scale": 9999,
                "margin_x": -5,
                "anchor": "nowhere",
                "show_cover": "false",
                "show_time": 0,
                "bar_count": "40",
                "unknown_key": 1,
            },
            "classic",
        )
        self.assertEqual(design["scale"], INT_RANGES["scale"][1])
        self.assertEqual(design["margin_x"], INT_RANGES["margin_x"][0])
        self.assertEqual(design["anchor"], default_design("classic")["anchor"])
        self.assertFalse(design["show_cover"])
        self.assertFalse(design["show_time"])
        self.assertEqual(design["bar_count"], 40)
        self.assertNotIn("unknown_key", design)

    def test_unsupported_features_are_disabled_per_skin(self) -> None:
        everything_on = {key: True for key in ("show_cover", "show_bars", "show_progress", "show_knob", "glass_enabled")}
        for skin in SUPPORTED_SKINS:
            flags = effective_flags(normalize_design(everything_on, skin), skin)
            for feature, enabled in flags.items():
                if enabled:
                    self.assertIn(feature, SKIN_FEATURES[skin], f"{skin}: {feature}")


class GeometryTests(unittest.TestCase):
    def test_bounds_scale_with_resolution_and_stay_in_frame(self) -> None:
        for skin in SUPPORTED_SKINS:
            for anchor in ANCHORS:
                design = normalize_design({"anchor": anchor}, skin)
                x, y, w, h, unit = player_bounds(design, skin, 1920, 1080)
                x4, y4, w4, h4, unit4 = player_bounds(design, skin, 3840, 2160)
                self.assertAlmostEqual(unit4, unit * 2)
                self.assertAlmostEqual(w4, w * 2, delta=2)
                self.assertAlmostEqual(h4, h * 2, delta=2)
                for frame, box in (((1920, 1080), (x, y, w, h)), ((3840, 2160), (x4, y4, w4, h4))):
                    self.assertGreaterEqual(box[0], 0, f"{skin}/{anchor}")
                    self.assertGreaterEqual(box[1], 0, f"{skin}/{anchor}")
                    self.assertLessEqual(box[0] + box[2], frame[0], f"{skin}/{anchor}")
                    self.assertLessEqual(box[1] + box[3], frame[1], f"{skin}/{anchor}")

    def test_vertical_timeline_keeps_the_player_inside(self) -> None:
        for skin in SUPPORTED_SKINS:
            x, y, w, h, _ = player_bounds(default_design(skin), skin, 1080, 1920)
            self.assertLessEqual(x + w, 1080, skin)
            self.assertLessEqual(y + h, 1920, skin)

    def test_layers_are_full_frame_rgba_with_transparent_corners(self) -> None:
        for skin in SUPPORTED_SKINS:
            layers = compose_player(INFO, sample_levels(64), default_design(skin), skin, 960, 540)
            self.assertEqual(layers.card.mode, "RGBA")
            self.assertEqual(layers.card.size, (960, 540))
            x, y, w, h = layers.bounds
            corner = (959, 0) if x < 480 else (0, 0)
            if y < 270:
                corner = (corner[0], 539)
            self.assertEqual(layers.card.getpixel(corner)[3], 0, skin)

    def test_readouts_follow_time_modes(self) -> None:
        self.assertEqual(readout_text("elapsed_total", 65, 225), "01:05 / 03:45")
        self.assertEqual(readout_text("elapsed", 65, 225), "01:05")
        self.assertEqual(readout_text("remaining", 65, 225), "-02:40")
        self.assertEqual(readout_text("total", 65, 3725), "1:02:05")

    def test_time_mode_none_has_no_text_readouts(self) -> None:
        design = normalize_design({"time_mode": "none"}, "classic")
        layers = compose_player(INFO, None, design, "classic", 1920, 1080)
        self.assertEqual(layers.texts, [])

    def test_flatten_reveals_played_layer_with_progress(self) -> None:
        layers = compose_player(INFO, sample_levels(72), default_design("classic"), "classic", 1920, 1080)
        start = flatten_player(layers, 0.0, 0, 200)
        end = flatten_player(layers, 1.0, 200, 200)
        self.assertNotEqual(start.tobytes(), end.tobytes())


class OutputTests(unittest.TestCase):
    def test_track_layers_are_written_atomically_with_stable_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layers, paths = render_track_layers(INFO, sample_levels(72), default_design("wave"), "wave", 1280, 720, Path(temporary), "TVIZ_t_1")
            self.assertEqual(Path(paths["card"]).name, "TVIZ_t_1_card.png")
            for path in paths.values():
                if path:
                    with Image.open(path) as image:
                        self.assertEqual(image.size, (1280, 720))
            self.assertEqual([p.name for p in Path(temporary).iterdir() if ".tmp" in p.name], [])
            self.assertLess(layers.progress_x1, layers.progress_x2)

    def test_preview_full_frame_and_close_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            full = render_preview(Path(temporary) / "full.png", None, "classic", preview_width=640)
            close = render_preview(Path(temporary) / "close.png", None, "classic", preview_width=640, crop=True)
            with Image.open(full) as image:
                self.assertEqual(image.size, (640, 360))
            with Image.open(close) as image:
                self.assertEqual(image.width, 640)
                self.assertLess(image.height, 360)


if __name__ == "__main__":
    unittest.main()
