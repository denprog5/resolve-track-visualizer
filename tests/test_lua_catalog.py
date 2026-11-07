from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_lua_catalog  # noqa: E402

from davinci_track_visualizer.skins import ENUMS, PALETTES, SUPPORTED_SKINS  # noqa: E402

LUA_SOURCE = (ROOT / "resolve_scripts" / "Track Visualizer.lua").read_text(encoding="utf-8")


def _keys(name: str, following: str) -> set[str]:
    start = LUA_SOURCE.index(f"    {name} = {{")
    end = LUA_SOURCE.index(f"\n    {following}", start)
    return set(re.findall(r'^\s*\["([^"]+)"\]\s*=', LUA_SOURCE[start:end], re.MULTILINE))


class LuaCatalogTests(unittest.TestCase):
    def test_embedded_catalog_matches_python_skins(self) -> None:
        self.assertEqual(
            sync_lua_catalog.sync(LUA_SOURCE),
            LUA_SOURCE,
            "SKIN_CATALOG is stale; run scripts/sync_lua_catalog.py",
        )

    def test_lua_literal_is_deterministic_and_ascii_only(self) -> None:
        self.assertEqual(sync_lua_catalog.lua_literal({"b": [1, 2], "a": True}), "{\n    a = true,\n    b = { 1, 2 },\n}")
        self.assertEqual(sync_lua_catalog.lua_literal({"end": "x"}), '{\n    ["end"] = "x",\n}')
        with self.assertRaises(ValueError):
            sync_lua_catalog.lua_literal("тест")

    def test_dynamic_translation_keys_exist_in_both_catalogs(self) -> None:
        english = _keys("en", "ru = {")
        russian = _keys("ru", "},\n}")
        wanted = {f"skin.{skin}" for skin in SUPPORTED_SKINS}
        wanted |= {f"palette.{name}" for name in PALETTES} | {"palette.Custom", "palette.custom_mark"}
        prefixes = dict(re.findall(r'key = "([a-z_]+)", prefix = "([a-z_.]+)"', LUA_SOURCE))
        self.assertEqual(set(prefixes), set(ENUMS))
        for key, values in ENUMS.items():
            wanted |= {prefixes[key] + value for value in values}
        wanted |= set(re.findall(r'\blabel = "([a-z_]+\.[a-z_]+)"', LUA_SOURCE))
        modes = re.search(r"local SWITCH_MODES = \{([^}]*)\}", LUA_SOURCE)
        self.assertIsNotNone(modes)
        assert modes is not None
        wanted |= {f"switch_mode.{mode}" for mode in re.findall(r'"([a-z_]+)"', modes.group(1))}
        self.assertEqual(sorted(wanted - english), [])
        self.assertEqual(sorted(wanted - russian), [])


if __name__ == "__main__":
    unittest.main()
