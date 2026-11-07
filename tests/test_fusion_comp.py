from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from davinci_track_visualizer.fusion_comp import (
    CompSpec,
    TextSpec,
    build_comp,
    elapsed_expression,
    format_clock,
    lua_string,
    progress_expression,
    text_expression,
    write_comp,
)


def _spec(**overrides) -> CompSpec:
    values = dict(
        width=1920,
        height=1080,
        fps=30.0,
        clip_frames=900,
        card_path=r"C:\Media\Песня\card.png",
        played_path=r"C:\Media\played.png",
        knob_path=r"C:\Media\knob.png",
        progress_x1=200.0,
        progress_x2=600.0,
        offset_seconds=30.0,
        total_seconds=200.0,
        texts=(TextSpec("elapsed_total", 620, 1000, "right"),),
    )
    values.update(overrides)
    return CompSpec(**values)


class FusionCompTests(unittest.TestCase):
    def test_lua_strings_are_escaped(self) -> None:
        self.assertEqual(lua_string('a"b\\c'), '"a\\"b\\\\c"')
        self.assertNotIn("\n", lua_string("line\nbreak"))

    def test_clock_format(self) -> None:
        self.assertEqual(format_clock(65, False), "01:05")
        self.assertEqual(format_clock(3725, True), "1:02:05")

    def test_expressions_use_offset_and_clamp(self) -> None:
        spec = _spec()
        elapsed = elapsed_expression(spec)
        self.assertIn("30", elapsed)
        self.assertIn("200", elapsed)
        self.assertIn("math.min", elapsed)
        self.assertIn("math.max", elapsed)
        self.assertIn("/", progress_expression(spec))
        for kind in ("elapsed_total", "elapsed", "remaining", "total"):
            self.assertIn("Text(", text_expression(spec, kind))

    def test_hours_appear_only_for_long_tracks(self) -> None:
        short = text_expression(_spec(total_seconds=200.0), "total")
        long = text_expression(_spec(total_seconds=4000.0), "total")
        self.assertNotEqual(short, long)

    def test_comp_has_loaders_mask_text_and_output(self) -> None:
        comp = build_comp(_spec())
        for fragment in ("Composition {", "Loader {", "Merge {", "RectangleMask {", "TextPlus {", "Saver {", "MediaOut1"):
            self.assertIn(fragment, comp)
        self.assertIn("Песня", comp)
        self.assertNotIn("MediaIn", comp)

    def test_optional_layers_are_omitted(self) -> None:
        comp = build_comp(_spec(played_path=None, knob_path=None, texts=()))
        self.assertEqual(comp.count("Loader {"), 1)
        self.assertNotIn("TextPlus", comp)
        self.assertNotIn("RectangleMask", comp)

    def test_write_comp_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = write_comp(Path(temporary) / "x.comp", _spec())
            self.assertTrue(target.is_file())
            self.assertEqual([p.name for p in Path(temporary).iterdir()], ["x.comp"])


if __name__ == "__main__":
    unittest.main()
