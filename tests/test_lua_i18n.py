from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LUA_SOURCE = (ROOT / "resolve_scripts" / "Track Visualizer.lua").read_text(encoding="utf-8")


def _catalog(name: str, following: str) -> str:
    start = LUA_SOURCE.index(f"    {name} = {{")
    end = LUA_SOURCE.index(f"\n    {following}", start)
    return LUA_SOURCE[start:end]


class LuaLocalizationTests(unittest.TestCase):
    def test_catalogs_have_matching_stable_keys(self) -> None:
        english = _catalog("en", "ru = {")
        russian = _catalog("ru", "},\n}")
        pattern = re.compile(r'^\s*\["([^"]+)"\]\s*=', re.MULTILINE)
        english_keys = set(pattern.findall(english))
        russian_keys = set(pattern.findall(russian))
        self.assertGreaterEqual(len(english_keys), 200)
        self.assertEqual(russian_keys, english_keys)

    def test_every_translation_reference_has_an_english_fallback(self) -> None:
        english = _catalog("en", "ru = {")
        defined = set(re.findall(r'^\s*\["([^"]+)"\]\s*=', english, re.MULTILINE))
        used = set(re.findall(r'\btr\("([^"]+)"', LUA_SOURCE))
        used -= {"skin.", "palette."}
        self.assertEqual(sorted(used - defined), [])

    def test_first_launch_and_manual_language_modes_are_stable(self) -> None:
        self.assertIn('local LANGUAGE_MODES = { "auto", "en", "ru" }', LUA_SOURCE)
        self.assertIn('language_mode = existing_settings and "ru" or "auto"', LUA_SOURCE)
        self.assertIn('settings_version = 1', LUA_SOURCE)
        self.assertIn('os.getenv("TVIZ_UI_LANG")', LUA_SOURCE)
        self.assertIn('GetUserPreferredUILanguages', LUA_SOURCE)
        self.assertIn('CFLocaleCopyPreferredLanguages', LUA_SOURCE)
        self.assertIn('"LC_MESSAGES"', LUA_SOURCE)

    def test_windows_wide_launch_failure_is_localized(self) -> None:
        entries = re.findall(r'\["error\.windows_wide_launch"\]\s*=\s*"([^"]+)"', LUA_SOURCE)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all("{details}" in entry for entry in entries))
        self.assertIn('tr("error.windows_wide_launch"', LUA_SOURCE)


if __name__ == "__main__":
    unittest.main()
