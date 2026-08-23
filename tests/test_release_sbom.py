from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from scripts.generate_release_sbom import (
    extract_member,
    require_digest,
    validate_spdx,
    verify_checksum_manifest,
)


class ReleaseSbomTests(unittest.TestCase):
    def test_checksum_manifest_and_archive_digest_must_both_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = root / "syft_1.42.3_linux_amd64.tar.gz"
            archive.write_bytes(b"archive")
            digest = hashlib.sha256(b"archive").hexdigest()
            manifest = root / "checksums.txt"
            manifest.write_text(f"{digest}  {archive.name}\n", encoding="ascii")

            require_digest(archive, digest, "Syft archive")
            verify_checksum_manifest(manifest, archive.name, digest)
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                require_digest(archive, "0" * 64, "Syft archive")
            with self.assertRaisesRegex(RuntimeError, "Official checksum manifest"):
                verify_checksum_manifest(manifest, archive.name, "0" * 64)

    def test_exact_tool_member_is_extracted_from_zip_and_tar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            zip_path = root / "syft.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("syft.exe", b"windows-tool")
                archive.writestr("README.md", b"ignored")
            zip_output = root / "zip-bin" / "syft.exe"
            extract_member(zip_path, "syft.exe", zip_output)
            self.assertEqual(zip_output.read_bytes(), b"windows-tool")

            tar_path = root / "syft.tar.gz"
            with tarfile.open(tar_path, "w:gz") as archive:
                info = tarfile.TarInfo("syft")
                info.size = len(b"unix-tool")
                archive.addfile(info, BytesIO(b"unix-tool"))
            tar_output = root / "tar-bin" / "syft"
            extract_member(tar_path, "syft", tar_output)
            self.assertEqual(tar_output.read_bytes(), b"unix-tool")

    def test_spdx_output_is_structurally_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "release.spdx.json"
            output.write_text(
                json.dumps(
                    {
                        "spdxVersion": "SPDX-2.3",
                        "SPDXID": "SPDXRef-DOCUMENT",
                        "packages": [],
                    }
                ),
                encoding="utf-8",
            )
            validate_spdx(output)
            output.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "spdxVersion"):
                validate_spdx(output)


if __name__ == "__main__":
    unittest.main()
