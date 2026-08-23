from __future__ import annotations

import unittest
from pathlib import Path

from davinci_track_visualizer.platform_paths import executable_name, install_root, resolve_scripts_dir
from scripts.build_release import BuildTarget, validate_release_environment


class PlatformPathTests(unittest.TestCase):
    def test_windows_paths_use_local_and_roaming_appdata(self) -> None:
        env = {
            "LOCALAPPDATA": r"C:\Users\Alice\AppData\Local",
            "APPDATA": r"C:\Users\Alice\AppData\Roaming",
        }
        self.assertEqual(
            install_root(system="Windows", environ=env, home=r"C:\Users\Alice"),
            Path(env["LOCALAPPDATA"]) / "DavinciTrackVisualizer",
        )
        self.assertEqual(
            resolve_scripts_dir(system="Windows", environ=env, home=r"C:\Users\Alice"),
            Path(env["APPDATA"])
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Fusion"
            / "Scripts"
            / "Utility",
        )

    def test_linux_paths_honor_xdg_data_home(self) -> None:
        home = Path("/home/alice")
        env = {"XDG_DATA_HOME": "/data/alice"}
        self.assertEqual(
            install_root(system="Linux", environ=env, home=home),
            Path("/data/alice") / "DavinciTrackVisualizer",
        )
        self.assertEqual(
            resolve_scripts_dir(system="Linux", environ=env, home=home),
            home / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Scripts" / "Utility",
        )

    def test_macos_paths_use_application_support(self) -> None:
        home = Path("/Users/alice")
        self.assertEqual(
            install_root(system="Darwin", environ={}, home=home),
            home / "Library" / "Application Support" / "DavinciTrackVisualizer",
        )
        self.assertEqual(
            resolve_scripts_dir(system="Darwin", environ={}, home=home),
            home
            / "Library"
            / "Application Support"
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Fusion"
            / "Scripts"
            / "Utility",
        )

    def test_explicit_path_overrides_are_cross_platform(self) -> None:
        env = {
            "DAVINCI_TRACK_VISUALIZER_HOME": "/custom/application",
            "DAVINCI_TRACK_VISUALIZER_RESOLVE_SCRIPTS": "/custom/scripts",
        }
        self.assertEqual(install_root(system="Linux", environ=env), Path("/custom/application"))
        self.assertEqual(resolve_scripts_dir(system="Linux", environ=env), Path("/custom/scripts"))

    def test_native_executable_suffix(self) -> None:
        self.assertEqual(executable_name("TrackVisualizerRunner", "Windows"), "TrackVisualizerRunner.exe")
        self.assertEqual(executable_name("TrackVisualizerRunner", "Linux"), "TrackVisualizerRunner")
        self.assertEqual(executable_name("TrackVisualizerRunner", "Darwin"), "TrackVisualizerRunner")

    def test_release_target_labels_and_environment_must_match_native_host(self) -> None:
        target = BuildTarget("windows", "x86_64")
        self.assertEqual(target.tag, "windows-x64")
        validate_release_environment(
            target,
            "1.2.3",
            {"TVIZ_VERSION": "1.2.3", "TVIZ_TARGET": "windows-x64"},
        )
        with self.assertRaisesRegex(RuntimeError, "TVIZ_VERSION"):
            validate_release_environment(target, "1.2.3", {"TVIZ_VERSION": "1.2.4"})
        with self.assertRaisesRegex(RuntimeError, "TVIZ_TARGET"):
            validate_release_environment(target, "1.2.3", {"TVIZ_TARGET": "linux-x64"})


if __name__ == "__main__":
    unittest.main()
