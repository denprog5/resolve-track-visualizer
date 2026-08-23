from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from installer import track_visualizer_installer as installer


class InstallerLocalizationTests(unittest.TestCase):
    def _resource_tree(self, root: Path) -> None:
        for resource in installer.required_resources(root):
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(b"test")

    def _dry_run(self, language: str) -> tuple[str, Path, Path]:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        source = root / "source"
        install_root = root / "installed"
        script_directory = root / "resolve-scripts"
        self._resource_tree(source)

        output = io.StringIO()
        with (
            patch.object(installer, "resource_root", return_value=source),
            contextlib.redirect_stdout(output),
        ):
            result = installer.main(
                [
                    "--language",
                    language,
                    "--dry-run",
                    "--no-pause",
                    "--install-root",
                    str(install_root),
                    "--resolve-script-dir",
                    str(script_directory),
                ]
            )

        self.assertEqual(result, 0)
        self.assertFalse(install_root.exists())
        self.assertFalse(script_directory.exists())
        return output.getvalue(), install_root.resolve(), script_directory.resolve()

    def test_locale_normalization_selects_russian_only_for_russian_locale(self) -> None:
        russian_locales = ("ru", "ru-RU", "ru_RU.UTF-8", "ru@cyrillic", "Russian_Russia.1251")
        for locale_name in russian_locales:
            with self.subTest(locale_name=locale_name):
                self.assertEqual(installer.normalize_locale_name(locale_name), "ru")

        other_locales = (None, "", "C", "POSIX", "en_US.UTF-8", "uk_UA", "be_BY", "de-DE")
        for locale_name in other_locales:
            with self.subTest(locale_name=locale_name):
                self.assertEqual(installer.normalize_locale_name(locale_name), "en")

    def test_forced_override_applies_only_when_cli_language_is_auto(self) -> None:
        environment = {"TVIZ_UI_LANG": "ru", "LANG": "en_US.UTF-8"}
        self.assertEqual(
            installer.resolve_language("auto", system="Linux", environ=environment),
            "ru",
        )
        self.assertEqual(
            installer.resolve_language("en", system="Linux", environ=environment),
            "en",
        )

    def test_system_locale_detection_uses_platform_ui_sources(self) -> None:
        self.assertEqual(
            installer.detect_system_ui_locale(
                system="Linux", environ={"LANGUAGE": "ru_RU:en_US", "LANG": "en_US.UTF-8"}
            ),
            "ru_RU:en_US",
        )
        with patch.object(installer, "_windows_ui_locale", return_value="ru_RU"):
            self.assertEqual(
                installer.detect_system_ui_locale(system="Windows", environ={}),
                "ru_RU",
            )
        with patch.object(installer, "_macos_ui_locale", return_value="ru-RU"):
            self.assertEqual(
                installer.detect_system_ui_locale(system="Darwin", environ={}),
                "ru-RU",
            )

    def test_catalogs_have_identical_stable_keys_and_english_fallback(self) -> None:
        english_keys = set(installer.MESSAGE_CATALOGS["en"])
        self.assertEqual(set(installer.MESSAGE_CATALOGS["ru"]), english_keys)
        self.assertEqual(
            installer.message("install_complete", "unsupported"),
            installer.MESSAGE_CATALOGS["en"]["install_complete"],
        )

    def test_english_help_and_dry_run_output(self) -> None:
        help_text = installer.build_parser("en").format_help()
        self.assertIn("Install DaVinci Track Visualizer for the current user", help_text)
        self.assertIn("Installer language", help_text)

        output, install_root, script_directory = self._dry_run("en")
        self.assertIn("Installing DaVinci Track Visualizer...", output)
        self.assertIn(f"Application directory: {install_root}", output)
        self.assertIn(f"Resolve script directory: {script_directory}", output)
        self.assertIn("Dry run complete", output)
        self.assertNotIn("Установка", output)

    def test_russian_help_and_dry_run_output(self) -> None:
        help_text = installer.build_parser("ru").format_help()
        self.assertIn("Установить DaVinci Track Visualizer", help_text)
        self.assertIn("Язык установщика", help_text)

        output, install_root, script_directory = self._dry_run("ru")
        self.assertIn("Установка DaVinci Track Visualizer...", output)
        self.assertIn(f"Каталог приложения: {install_root}", output)
        self.assertIn(f"Каталог скриптов Resolve: {script_directory}", output)
        self.assertIn("Проверка завершена", output)
        self.assertNotIn("Installing", output)

    def test_missing_resource_error_is_localized_without_translating_path(self) -> None:
        missing_root = Path("missing-installer-root")
        with self.assertRaises(FileNotFoundError) as raised:
            installer.validate_resources(missing_root, language="ru")
        error = str(raised.exception)
        self.assertIn("Отсутствуют ресурсы установщика", error)
        self.assertIn(str(missing_root / installer.BIN_DIRECTORY / installer.ENGINE_NAME), error)


if __name__ == "__main__":
    unittest.main()
