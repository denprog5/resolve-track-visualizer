from __future__ import annotations

import hashlib
import json
import re
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from davinci_track_visualizer.platform_paths import platform_name
from installer import track_visualizer_installer
from scripts.build_release import (
    PILLOW_LICENSE_PATH,
    BuildTarget,
    RuntimeFiles,
    _pillow_notice_files,
    binary_architectures,
    create_tar_archive,
    python_license_file,
    require_empty_release_directory,
    stage_package,
    validate_ffmpeg_capabilities,
    validate_ffmpeg_configuration,
    validate_ffmpeg_pair,
    validate_native_binary,
    validate_python_runtime,
)


class ReleaseStagingTests(unittest.TestCase):
    def _source_tree(self, root: Path) -> RuntimeFiles:
        (root / "resolve_scripts").mkdir(parents=True)
        (root / "packaging").mkdir()
        (root / "packaging" / "scripts").mkdir()
        (root / "resolve_scripts" / "Track Visualizer.lua").write_text(
            "local root = [[__INSTALL_ROOT__]]\n", encoding="utf-8"
        )
        (root / "packaging" / "THIRD_PARTY_NOTICES.txt").write_text("Notices\n", encoding="utf-8")
        (root / "packaging" / "scripts" / "build_ffmpeg.sh").write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )
        (root / "ffmpeg-license.txt").write_text("GPL version 3 or later\n", encoding="utf-8")
        (root / "LICENSE").write_text("GPL-3.0-or-later\n", encoding="utf-8")
        (root / "aplus.png").write_bytes(b"png")
        binaries = {}
        for role in ("engine", "runner", "ffmpeg", "ffprobe"):
            path = root / f"source-{role}"
            path.write_bytes(role.encode("ascii"))
            binaries[role] = path
        return RuntimeFiles(**binaries)

    def _dependency_licenses(self, root: Path) -> dict[str, Path]:
        python_license = root / "python-license.txt"
        python_license.write_text("PSF license\n", encoding="utf-8")
        pillow_license = root / "pillow-license.txt"
        pillow_license.write_text("Pillow and bundled libraries\n", encoding="utf-8")
        return {
            "Python-LICENSE.txt": python_license,
            f"Pillow/{PILLOW_LICENSE_PATH}": pillow_license,
        }

    def test_stage_contains_resources_notices_hash_manifest_and_native_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "source"
            root.mkdir()
            runtime = self._source_tree(root)
            stage = Path(temporary_dir) / "DavinciTrackVisualizer-1.2.3-linux-x86_64"

            manifest_path = stage_package(
                stage,
                runtime,
                BuildTarget("linux", "x86_64"),
                root=root,
                version="1.2.3",
                epoch=1_704_067_200,
                ffmpeg_build_info="ffmpeg version test\nGPL version 3",
                ffmpeg_license=root / "ffmpeg-license.txt",
                ffmpeg_version="9.0.1",
                ffmpeg_source_url="https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz",
                ffmpeg_source_sha256="9" * 64,
                ffmpeg_build_script=root / "packaging" / "scripts" / "build_ffmpeg.sh",
                dependency_licenses=self._dependency_licenses(root),
                runtime_baseline="glibc 2.28 or later",
            )

            self.assertTrue((stage / "bin" / "TrackVisualizerEngine").is_file())
            self.assertTrue((stage / "bin" / "TrackVisualizerRunner").is_file())
            self.assertTrue((stage / "resources" / "Track Visualizer.lua").is_file())
            self.assertTrue((stage / "resources" / "aplus.png").is_file())
            self.assertTrue((stage / "THIRD_PARTY_NOTICES.txt").is_file())
            self.assertTrue((stage / "LICENSE").is_file())
            self.assertTrue((stage / "licenses" / "FFMPEG_BUILD_INFO.txt").is_file())
            self.assertTrue((stage / "licenses" / "FFMPEG_BUILD_SCRIPT.sh").is_file())
            self.assertTrue((stage / "licenses" / "FFMPEG_LICENSE.txt").is_file())
            self.assertTrue((stage / "licenses" / "FFMPEG_SOURCE_OFFER.txt").is_file())
            self.assertTrue((stage / "licenses" / "MUTAGEN_SOURCE_OFFER.txt").is_file())
            self.assertTrue((stage / "licenses" / "Python-LICENSE.txt").is_file())
            pillow_notice = stage / "licenses" / "Pillow" / PILLOW_LICENSE_PATH
            self.assertTrue(pillow_notice.is_file())
            source_offer = (stage / "licenses" / "FFMPEG_SOURCE_OFFER.txt").read_text(encoding="utf-8")
            self.assertIn("ffmpeg-9.0.1.tar.xz", source_offer)
            self.assertIn("9" * 64, source_offer)
            self.assertNotIn("zlib", source_offer.lower())
            mutagen_offer = (stage / "licenses" / "MUTAGEN_SOURCE_OFFER.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("mutagen-1.47.0.tar.gz", mutagen_offer)
            self.assertIn(
                "719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99",
                mutagen_offer,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "1.2.3")
            self.assertEqual(manifest["target"], {"architecture": "x86_64", "os": "linux"})
            self.assertEqual(manifest["ffmpeg_version"], "9.0.1")
            self.assertNotIn("zlib_version", manifest)
            self.assertEqual(manifest["runtime_baseline"], "glibc 2.28 or later")
            paths = [record["path"] for record in manifest["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertNotIn("manifest.json", paths)
            self.assertIn("licenses/Python-LICENSE.txt", paths)
            self.assertIn(f"licenses/Pillow/{PILLOW_LICENSE_PATH}", paths)
            engine_record = next(record for record in manifest["files"] if record["path"].endswith("Engine"))
            self.assertEqual(engine_record["mode"], "0755")
            self.assertEqual(len(engine_record["sha256"]), 64)

    def test_tar_archive_is_deterministic_and_preserves_executable_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "source"
            root.mkdir()
            runtime = self._source_tree(root)
            stage = Path(temporary_dir) / "DavinciTrackVisualizer-1.2.3-linux-x86_64"
            epoch = 1_704_067_200
            stage_package(
                stage,
                runtime,
                BuildTarget("linux", "x86_64"),
                root=root,
                version="1.2.3",
                epoch=epoch,
                dependency_licenses=self._dependency_licenses(root),
            )
            first = Path(temporary_dir) / "first.tar.gz"
            second = Path(temporary_dir) / "second.tar.gz"
            create_tar_archive(stage, first, epoch)
            create_tar_archive(stage, second, epoch)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first, "r:gz") as archive:
                engine = archive.getmember(f"{stage.name}/bin/TrackVisualizerEngine")
                notice = archive.getmember(f"{stage.name}/THIRD_PARTY_NOTICES.txt")
                archive.getmember(f"{stage.name}/licenses/Python-LICENSE.txt")
                archive.getmember(f"{stage.name}/licenses/Pillow/{PILLOW_LICENSE_PATH}")
                self.assertEqual(stat.S_IMODE(engine.mode), 0o755)
                self.assertEqual(stat.S_IMODE(notice.mode), 0o644)
                self.assertEqual(engine.mtime, epoch)

    def test_native_binary_architecture_is_read_from_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            pe = bytearray(128)
            pe[:2] = b"MZ"
            pe[60:64] = (64).to_bytes(4, "little")
            pe[64:68] = b"PE\0\0"
            pe[68:70] = (0x8664).to_bytes(2, "little")
            pe_path = root / "windows.exe"
            pe_path.write_bytes(pe)
            self.assertEqual(binary_architectures(pe_path), {"x86_64"})
            validate_native_binary(pe_path, BuildTarget("windows", "x86_64"), "test")

            elf = bytearray(64)
            elf[:6] = b"\x7fELF\x02\x01"
            elf[18:20] = (183).to_bytes(2, "little")
            elf_path = root / "linux-arm64"
            elf_path.write_bytes(elf)
            self.assertEqual(binary_architectures(elf_path), {"arm64"})
            with self.assertRaisesRegex(RuntimeError, "not native"):
                validate_native_binary(elf_path, BuildTarget("linux", "x86_64"), "test")

    def test_ffmpeg_release_configuration_requires_exact_minimal_recipe(self) -> None:
        configuration = " ".join(
            [
                "--prefix=/build/ffmpeg/prefix",
                "--enable-gpl",
                "--enable-version3",
                "--enable-static",
                "--disable-shared",
                "--disable-autodetect",
                "--disable-everything",
                "--disable-network",
                "--disable-ffplay",
                "--disable-doc",
                "--disable-debug",
                "--disable-x86asm",
                "--pkg-config=false",
                "--enable-ffmpeg",
                "--enable-ffprobe",
                "--enable-decoder=aac,alac,flac,mp3float,opus,pcm_s16be,pcm_s16le,rawvideo,vorbis",
                "--enable-encoder=pcm_s16le,prores_ks,qtrle",
                "--enable-demuxer=aac,aiff,flac,mov,mp3,ogg,rawvideo,wav",
                "--enable-muxer=mov,s16le",
                "--enable-parser=aac,flac,mpegaudio,opus,vorbis",
                "--enable-protocol=file,pipe",
                "--enable-filter=abuffer,abuffersink,aformat,aresample,buffer,buffersink,format,scale",
            ]
        )
        license_text = (
            "GNU General Public License; either version 3 of the License, "
            "or (at your option) any later version"
        )
        linux_target = BuildTarget("linux", "x86_64")
        validate_ffmpeg_configuration(configuration, license_text, linux_target)
        quoted_configuration = re.sub(
            r"(--enable-(?:decoder|encoder|demuxer|muxer|parser|protocol|filter)=)(\S+)",
            r"\1'\2'",
            configuration,
        ).replace(" --", "\n  --")
        validate_ffmpeg_configuration(
            f"configuration:\n  {quoted_configuration}", license_text, linux_target
        )

        windows_target = BuildTarget("windows", "x86_64")
        with self.assertRaisesRegex(RuntimeError, "extra-ldflags"):
            validate_ffmpeg_configuration(configuration, license_text, windows_target)
        validate_ffmpeg_configuration(
            configuration + " --extra-ldflags=-static", license_text, windows_target
        )

        with self.assertRaisesRegex(RuntimeError, "exact release recipe"):
            validate_ffmpeg_configuration(
                configuration + " --enable-libx264", license_text, linux_target
            )
        with self.assertRaisesRegex(RuntimeError, "required release configuration"):
            validate_ffmpeg_configuration(
                configuration.replace("--disable-everything", ""), license_text, linux_target
            )
        with self.assertRaisesRegex(RuntimeError, "required release configuration"):
            validate_ffmpeg_configuration(
                configuration.replace(
                    "--enable-encoder=pcm_s16le,prores_ks,qtrle",
                    "--enable-encoder=png,pcm_s16le,prores_ks,qtrle",
                ),
                license_text,
                linux_target,
            )

    def test_ffmpeg_capability_listing_requires_media_features_and_no_network(self) -> None:
        listings = {
            "-encoders": " A..... pcm_s16le\n V..... prores_ks\n V..... qtrle\n",
            "-decoders": (
                " A..... aac\n A..... alac\n A..... flac\n A..... mp3float\n A..... opus\n"
                " A..... pcm_s16be\n A..... pcm_s16le\n V..... rawvideo\n A..... vorbis\n"
            ),
            "-demuxers": " D aac\n D aiff\n D flac\n D mov,mp4,m4a\n D mp3\n D ogg\n D rawvideo\n D wav\n",
            "-muxers": " E mov\n E s16le\n",
            "-parsers": "aac\nflac\nmpegaudio\nopus\nvorbis\n",
            "-filters": (
                " ... abuffer A->A\n ... abuffersink A->A\n ... aformat A->A\n ... aresample A->A\n"
                " ... buffer V->V\n ... buffersink V->V\n ... format V->V\n ... scale V->V\n"
            ),
            "-protocols": "Input:\nfile\npipe\nOutput:\nfile\npipe\n",
        }

        with patch("scripts.build_release.tool_information", side_effect=lambda _path, flag: listings[flag]):
            validate_ffmpeg_capabilities(Path("ffmpeg"))

        listings["-protocols"] += "http\n"
        with patch("scripts.build_release.tool_information", side_effect=lambda _path, flag: listings[flag]):
            with self.assertRaisesRegex(RuntimeError, "network protocols"):
                validate_ffmpeg_capabilities(Path("ffmpeg"))

    def test_ffmpeg_pair_requires_exact_version_and_matching_configuration(self) -> None:
        configuration = " ".join(
            [
                "--prefix=/build/ffmpeg/prefix",
                "--enable-gpl",
                "--enable-version3",
                "--enable-static",
                "--disable-shared",
                "--disable-autodetect",
                "--disable-everything",
                "--disable-network",
                "--disable-ffplay",
                "--disable-doc",
                "--disable-debug",
                "--disable-x86asm",
                "--pkg-config=false",
                "--enable-ffmpeg",
                "--enable-ffprobe",
                "--enable-decoder=aac,alac,flac,mp3float,opus,pcm_s16be,pcm_s16le,rawvideo,vorbis",
                "--enable-encoder=pcm_s16le,prores_ks,qtrle",
                "--enable-demuxer=aac,aiff,flac,mov,mp3,ogg,rawvideo,wav",
                "--enable-muxer=mov,s16le",
                "--enable-parser=aac,flac,mpegaudio,opus,vorbis",
                "--enable-protocol=file,pipe",
                "--enable-filter=abuffer,abuffersink,aformat,aresample,buffer,buffersink,format,scale",
            ]
        )
        license_text = (
            "GNU General Public License; either version 3 of the License, "
            "or (at your option) any later version"
        )
        versions = {
            "ffmpeg": f"ffmpeg version 9.0.1\nconfiguration: {configuration}",
            "ffprobe": f"ffprobe version 9.0.1\nconfiguration: {configuration}",
        }

        def information(path: Path, flag: str) -> str:
            if flag == "-version":
                return versions[path.name]
            if flag == "-buildconf":
                return configuration
            if flag == "-L":
                return license_text
            raise AssertionError(flag)

        with patch("scripts.build_release.tool_information", side_effect=information):
            validate_ffmpeg_pair(
                Path("ffmpeg"), Path("ffprobe"), "9.0.1", BuildTarget("linux", "x86_64")
            )

        versions["ffprobe"] += " --enable-small"
        with patch("scripts.build_release.tool_information", side_effect=information):
            with self.assertRaisesRegex(RuntimeError, "same recorded build configuration"):
                validate_ffmpeg_pair(
                    Path("ffmpeg"),
                    Path("ffprobe"),
                    "9.0.1",
                    BuildTarget("linux", "x86_64"),
                )

    def test_release_output_fails_closed_without_deleting_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "release-output"
            require_empty_release_directory(output)
            self.assertTrue(output.is_dir())

            stale = output / "stale-user-artifact.zip"
            stale.write_bytes(b"user data")
            with self.assertRaisesRegex(RuntimeError, "refusing to remove"):
                require_empty_release_directory(output)
            self.assertEqual(stale.read_bytes(), b"user data")

    def test_release_python_runtime_must_match_exact_patch(self) -> None:
        expected_versions = {
            BuildTarget("windows", "x86_64"): "3.12.10",
            BuildTarget("linux", "x86_64"): "3.12.13",
            BuildTarget("macos", "arm64"): "3.12.10",
            BuildTarget("macos", "x86_64"): "3.12.10",
        }
        for target, expected in expected_versions.items():
            with self.subTest(target=target.tag):
                with patch("scripts.build_release.platform.python_version", return_value=expected):
                    validate_python_runtime(target)
        with patch("scripts.build_release.platform.python_version", return_value="3.12.12"):
            with self.assertRaisesRegex(RuntimeError, "require Python 3.12.10"):
                validate_python_runtime(BuildTarget("windows", "x86_64"))

    def test_python_license_is_found_in_all_release_runtime_layouts(self) -> None:
        layouts = {
            "windows-x64": Path("LICENSE.txt"),
            "linux-x64-manylinux": Path("lib/python3.12/LICENSE.txt"),
            "macos-arm64": Path("LICENSE"),
            "macos-x64": Path("Lib/LICENSE.txt"),
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for target, relative in layouts.items():
                with self.subTest(target=target):
                    prefix = root / target
                    license_path = prefix / relative
                    license_path.parent.mkdir(parents=True)
                    license_path.write_text(
                        "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n"
                        "This LICENSE AGREEMENT is between the Python Software Foundation\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(python_license_file((prefix,)), license_path)

            missing = root / "missing"
            missing.mkdir()
            (missing / "LICENSE.txt").write_text("not the PSF license\n", encoding="utf-8")
            with self.assertRaisesRegex(FileNotFoundError, "CPython 3.12 PSF license"):
                python_license_file((missing,))

    def test_pillow_notice_collection_preserves_layout_and_fails_closed(self) -> None:
        class FakeDistribution:
            version = "12.2.0"

            def __init__(self, root: Path, files: list[Path]) -> None:
                self.root = root
                self.files = files

            def locate_file(self, entry: Path) -> Path:
                return self.root / entry

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            license_path = root / PILLOW_LICENSE_PATH
            extra_relative = Path("PIL/LICENSES/native/BSD")
            extra_path = root / extra_relative
            license_path.parent.mkdir(parents=True)
            extra_path.parent.mkdir(parents=True)
            license_content = b"exact wheel notices\n"
            license_path.write_bytes(license_content)
            extra_path.write_text("native library notice\n", encoding="utf-8")
            distribution = FakeDistribution(
                root,
                [Path(PILLOW_LICENSE_PATH), extra_relative, Path("PIL/README")],
            )
            accepted = frozenset({hashlib.sha256(license_content).hexdigest()})

            with patch("scripts.build_release.PILLOW_LICENSE_SHA256S", accepted):
                notices = _pillow_notice_files(distribution)
            self.assertEqual(
                set(notices),
                {PILLOW_LICENSE_PATH, extra_relative.as_posix()},
            )

            distribution.files = [extra_relative]
            with self.assertRaisesRegex(RuntimeError, "missing its expected wheel notice"):
                _pillow_notice_files(distribution)

            distribution.files = [Path(PILLOW_LICENSE_PATH), extra_relative]
            with self.assertRaisesRegex(RuntimeError, "unrecognized license payload"):
                _pillow_notice_files(distribution)

            distribution.version = "12.1.1"
            with self.assertRaisesRegex(RuntimeError, "requires Pillow 12.2.0"):
                _pillow_notice_files(distribution)

    def test_installer_dry_run_validates_staged_package_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "source"
            root.mkdir()
            runtime = self._source_tree(root)
            native_system = platform_name()
            stage = Path(temporary_dir) / f"DavinciTrackVisualizer-1.2.3-{native_system}-x64"
            stage_package(
                stage,
                runtime,
                BuildTarget(native_system, "x86_64"),
                root=root,
                version="1.2.3",
            )
            install_root = Path(temporary_dir) / "installed"
            script_dir = Path(temporary_dir) / "resolve-scripts"

            with patch.object(track_visualizer_installer, "resource_root", return_value=stage):
                result = track_visualizer_installer.main(
                    [
                        "--dry-run",
                        "--no-pause",
                        "--install-root",
                        str(install_root),
                        "--resolve-script-dir",
                        str(script_dir),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertFalse(install_root.exists())
            self.assertFalse(script_dir.exists())


if __name__ == "__main__":
    unittest.main()
