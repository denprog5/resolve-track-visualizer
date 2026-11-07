from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from davinci_track_visualizer import platform_paths
from davinci_track_visualizer.platform_paths import comp_staging_dir


class CompStagingWindowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.preferred = self.root / "Пользователь" / "comps"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ascii_path_is_used_as_is(self) -> None:
        ascii_path = self.root / "comps"
        self.assertEqual(comp_staging_dir(ascii_path, system="Windows", environ={}), ascii_path)

    def test_short_path_keeps_comps_in_the_user_folder(self) -> None:
        with patch.object(platform_paths, "_windows_short_path", return_value=r"C:\Users\0434~1\comps"):
            result = comp_staging_dir(self.preferred, system="Windows", environ={"ProgramData": r"C:\ProgramData"})
        self.assertEqual(result, Path(r"C:\Users\0434~1\comps"))

    def test_shared_roots_are_never_used(self) -> None:
        with patch.object(platform_paths, "_windows_short_path", return_value=None):
            result = comp_staging_dir(
                self.preferred, system="Windows", environ={"ProgramData": r"C:\ProgramData", "PUBLIC": r"C:\Users\Public"}
            )
        self.assertEqual(result, self.preferred)


@unittest.skipUnless(hasattr(os, "getuid"), "POSIX ownership checks")
class CompStagingPosixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_new_directory_is_private(self) -> None:
        target = platform_paths._posix_private_dir(self.root / "comps")
        self.assertIsNotNone(target)
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o700)

    def test_shared_or_linked_directories_are_rejected(self) -> None:
        shared = self.root / "shared"
        shared.mkdir()
        os.chmod(shared, 0o777)
        self.assertIsNone(platform_paths._posix_private_dir(shared))
        link = self.root / "link"
        link.symlink_to(self.root / "elsewhere")
        (self.root / "elsewhere").mkdir(mode=0o700)
        self.assertIsNone(platform_paths._posix_private_dir(link))


if __name__ == "__main__":
    unittest.main()
