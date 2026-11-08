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
    WINDOWS_EXECUTABLE_DESCRIPTIONS,
    WINDOWS_LIBFFI_LICENSE_SHA256,
    WINDOWS_OPENSSL_LICENSE_SHA256,
    BuildTarget,
    RuntimeFiles,
    _installer_smoke_required_files,
    _pillow_notice_files,
    binary_architectures,
    create_tar_archive,
    libffi_license_file,
    pyinstaller_command,
    python_license_file,
    require_empty_release_directory,
    stage_package,
    validate_ffmpeg_capabilities,
    validate_ffmpeg_configuration,
    validate_ffmpeg_pair,
    validate_native_binary,
    validate_python_runtime,
    validate_windows_user_site_isolation,
    validate_windows_version_metadata,
    windows_runtime_license_files,
    windows_numeric_version,
    windows_version_metadata,
    write_windows_version_file,
)


class ReleaseStagingTests(unittest.TestCase):
    def _source_tree(self, root: Path) -> RuntimeFiles:
        (root / "resolve_scripts").mkdir(parents=True)
        (root / "packaging").mkdir()
        (root / "packaging" / "scripts").mkdir()
        (root / "resolve_scripts" / "Track Visualizer.lua").write_text(
            "local root = [[__INSTALL_ROOT__]]\n"
            "local engine = [[__ENGINE_EXECUTABLE__]]\n"
            "local runner = [[__RUNNER_EXECUTABLE__]]\n"
            "local ffmpeg = [[__FFMPEG_EXECUTABLE__]]\n"
            "local ffprobe = [[__FFPROBE_EXECUTABLE__]]\n",
            encoding="utf-8",
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
            self.assertIn("assembled release bundle", source_offer)
            self.assertIn("GitHub Release of this version attaches it", source_offer)
            self.assertNotIn("publishes", source_offer)
            self.assertNotIn("zlib", source_offer.lower())
            mutagen_offer = (stage / "licenses" / "MUTAGEN_SOURCE_OFFER.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("mutagen-1.47.0.tar.gz", mutagen_offer)
            self.assertIn("assembled release bundle", mutagen_offer)
            self.assertNotIn("publishes", mutagen_offer)
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

    def test_windows_version_resources_are_deterministic_and_executable_specific(self) -> None:
        descriptions = {
            "TrackVisualizerEngine": "DaVinci Track Visualizer rendering engine",
            "TrackVisualizerRunner": "DaVinci Track Visualizer background task runner",
            "TrackVisualizerSetup": "DaVinci Track Visualizer setup",
        }
        self.assertEqual(WINDOWS_EXECUTABLE_DESCRIPTIONS, descriptions)
        self.assertEqual(windows_numeric_version("12.34.56-preview.7"), (12, 34, 56, 0))
        with self.assertRaisesRegex(ValueError, "must not exceed 65535"):
            windows_numeric_version("65536.0.0")

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for executable_name, description in descriptions.items():
                with self.subTest(executable=executable_name):
                    version_file = root / f"{executable_name}.txt"
                    write_windows_version_file(
                        version_file,
                        "1.2.3-preview.4",
                        executable_name,
                        epoch=1_704_067_200,
                    )
                    first = version_file.read_bytes()
                    write_windows_version_file(
                        version_file,
                        "1.2.3-preview.4",
                        executable_name,
                        epoch=1_704_067_200,
                    )
                    self.assertEqual(version_file.read_bytes(), first)
                    self.assertNotIn(b"\r", first)
                    content = first.decode("utf-8")
                    compile(content, str(version_file), "eval")
                    self.assertIn("filevers=(1, 2, 3, 0)", content)
                    self.assertIn("prodvers=(1, 2, 3, 0)", content)
                    self.assertEqual(
                        windows_version_metadata("1.2.3-preview.4", executable_name),
                        {
                            "CompanyName": "denprog5",
                            "FileDescription": description,
                            "FileVersion": "1.2.3-preview.4",
                            "InternalName": executable_name,
                            "LegalCopyright": "Copyright (C) 2026 denprog5",
                            "OriginalFilename": f"{executable_name}.exe",
                            "ProductName": "DaVinci Track Visualizer",
                            "ProductVersion": "1.2.3-preview.4",
                        },
                    )

    def test_pyinstaller_version_file_wiring_is_windows_only_and_fail_closed(self) -> None:
        arguments = (
            Path("scripts/engine_entry.py"),
            "TrackVisualizerEngine",
            Path("dist"),
            Path("work"),
            Path("spec"),
        )
        version_file = Path("build/version-info/TrackVisualizerEngine.txt")
        windows_command = pyinstaller_command(
            *arguments,
            target=BuildTarget("windows", "x86_64"),
            version_file=version_file,
        )
        option_index = windows_command.index("--version-file")
        self.assertEqual(windows_command[option_index + 1], str(version_file))
        self.assertEqual(windows_command.count("--version-file"), 1)

        linux_command = pyinstaller_command(
            *arguments,
            target=BuildTarget("linux", "x86_64"),
        )
        self.assertNotIn("--version-file", linux_command)
        with self.assertRaisesRegex(ValueError, "required"):
            pyinstaller_command(*arguments, target=BuildTarget("windows", "x86_64"))
        with self.assertRaisesRegex(ValueError, "cannot be used"):
            pyinstaller_command(
                *arguments,
                target=BuildTarget("linux", "x86_64"),
                version_file=version_file,
            )

    def test_windows_post_build_metadata_validation_fails_on_mismatch(self) -> None:
        version = "1.2.3-preview.4"
        expected = {
            **windows_version_metadata(version, "TrackVisualizerEngine"),
            "VS_FIXEDFILEINFO.FileVersion": (1, 2, 3, 0),
            "VS_FIXEDFILEINFO.ProductVersion": (1, 2, 3, 0),
        }
        with patch("scripts.build_release._read_windows_version_metadata", return_value=expected):
            validate_windows_version_metadata(
                Path("TrackVisualizerEngine.exe"),
                version,
                "TrackVisualizerEngine",
            )

        invalid = dict(expected)
        invalid["ProductName"] = "Unexpected product"
        with patch("scripts.build_release._read_windows_version_metadata", return_value=invalid):
            with self.assertRaisesRegex(RuntimeError, "ProductName"):
                validate_windows_version_metadata(
                    Path("TrackVisualizerEngine.exe"),
                    version,
                    "TrackVisualizerEngine",
                )

        for field in ("VS_FIXEDFILEINFO.FileVersion", "VS_FIXEDFILEINFO.ProductVersion"):
            with self.subTest(field=field):
                invalid = dict(expected)
                invalid[field] = (1, 2, 4, 0)
                with patch(
                    "scripts.build_release._read_windows_version_metadata",
                    return_value=invalid,
                ):
                    with self.assertRaisesRegex(RuntimeError, re.escape(field)):
                        validate_windows_version_metadata(
                            Path("TrackVisualizerEngine.exe"),
                            version,
                            "TrackVisualizerEngine",
                        )

    def test_installer_smoke_required_set_uses_verified_stage_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "source"
            root.mkdir()
            runtime = self._source_tree(root)
            stage = Path(temporary_dir) / "DavinciTrackVisualizer-1.2.3-linux-x64"
            manifest_path = stage_package(
                stage,
                runtime,
                BuildTarget("linux", "x86_64"),
                root=root,
                version="1.2.3",
                dependency_licenses=self._dependency_licenses(root),
            )
            staged_runtime = RuntimeFiles(
                engine=stage / "bin" / "TrackVisualizerEngine",
                runner=stage / "bin" / "TrackVisualizerRunner",
                ffmpeg=stage / "bin" / "ffmpeg",
                ffprobe=stage / "bin" / "ffprobe",
            )
            install_root = Path(temporary_dir) / "temporary-install"
            script_root = Path(temporary_dir) / "temporary-resolve-scripts"

            required = set(
                _installer_smoke_required_files(
                    staged_runtime, stage, install_root, script_root
                )
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            packaged_licenses = {
                install_root.joinpath(*Path(record["path"]).parts)
                for record in manifest["files"]
                if record["path"].startswith("licenses/")
            }
            expected = packaged_licenses | {
                install_root / "TrackVisualizerEngine",
                install_root / "TrackVisualizerRunner",
                install_root / "ffmpeg",
                install_root / "ffprobe",
                install_root / "aplus.png",
                install_root / "THIRD_PARTY_NOTICES.txt",
                install_root / "LICENSE",
                install_root / "manifest.json",
                install_root / "install-state.json",
                script_root / "Track Visualizer.lua",
            }
            self.assertEqual(required, expected)

            manifest["files"][0]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "record does not match"):
                _installer_smoke_required_files(
                    staged_runtime, stage, install_root, script_root
                )

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
                "--enable-muxer=mov,pcm_s16le",
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
                "--enable-muxer=mov,pcm_s16le",
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
        }
        for target, expected in expected_versions.items():
            with self.subTest(target=target.tag):
                with patch("scripts.build_release.platform.python_version", return_value=expected):
                    validate_python_runtime(target)
        with patch("scripts.build_release.platform.python_version", return_value="3.12.12"):
            with self.assertRaisesRegex(RuntimeError, "require Python 3.12.10"):
                validate_python_runtime(BuildTarget("windows", "x86_64"))

    def test_windows_python_user_site_isolation_fails_closed(self) -> None:
        user_site = str(Path(tempfile.gettempdir()) / "tviz-user-site")
        isolated_path = (str(Path(tempfile.gettempdir()) / "official-python"),)
        with patch("scripts.build_release.site.ENABLE_USER_SITE", False):
            validate_windows_user_site_isolation(
                {"PYTHONNOUSERSITE": "1"},
                isolated_path,
                user_site,
            )
            with self.assertRaisesRegex(RuntimeError, "PYTHONNOUSERSITE=1"):
                validate_windows_user_site_isolation({}, isolated_path, user_site)
            with self.assertRaisesRegex(RuntimeError, "present on sys.path"):
                validate_windows_user_site_isolation(
                    {"PYTHONNOUSERSITE": "1"},
                    (user_site,),
                    user_site,
                )
        with patch("scripts.build_release.site.ENABLE_USER_SITE", True):
            with self.assertRaisesRegex(RuntimeError, "user site is not disabled"):
                validate_windows_user_site_isolation(
                    {"PYTHONNOUSERSITE": "1"},
                    isolated_path,
                    user_site,
                )

    def test_python_license_is_found_in_all_release_runtime_layouts(self) -> None:
        layouts = {
            "windows-x64": Path("LICENSE.txt"),
            "linux-x64-manylinux": Path("lib/python3.12/LICENSE.txt"),
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

    def test_libffi_license_is_hash_verified_from_linux_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            prefix = Path(temporary_dir)
            license_path = prefix / "lib" / "python3.12" / "libffi-LICENSE.txt"
            license_path.parent.mkdir(parents=True)
            content = b"libffi license\n"
            license_path.write_bytes(content)
            with patch(
                "scripts.build_release.LIBFFI_LICENSE_SHA256",
                hashlib.sha256(content).hexdigest(),
            ):
                self.assertEqual(libffi_license_file(prefix), license_path)
            with self.assertRaisesRegex(RuntimeError, "unrecognized license payload"):
                libffi_license_file(prefix)

    def test_windows_cpython_dependency_licenses_are_hash_verified_and_staged(self) -> None:
        self.assertEqual(
            WINDOWS_LIBFFI_LICENSE_SHA256,
            "2c9c2acb9743e6b007b91350475308aee44691d96aa20eacef8e199988c8c388",
        )
        self.assertEqual(
            WINDOWS_OPENSSL_LICENSE_SHA256,
            "7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a",
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "source"
            root.mkdir()
            libffi_license = root / "libffi" / "LICENSE"
            openssl_license = root / "openssl" / "LICENSE.txt"
            libffi_content = b"libffi 3.4.4 license\n"
            openssl_content = b"OpenSSL 3.0.16 license\n"
            libffi_license.parent.mkdir()
            openssl_license.parent.mkdir()
            libffi_license.write_bytes(libffi_content)
            openssl_license.write_bytes(openssl_content)

            with (
                patch(
                    "scripts.build_release.WINDOWS_LIBFFI_LICENSE_SHA256",
                    hashlib.sha256(libffi_content).hexdigest(),
                ),
                patch(
                    "scripts.build_release.WINDOWS_OPENSSL_LICENSE_SHA256",
                    hashlib.sha256(openssl_content).hexdigest(),
                ),
            ):
                licenses = windows_runtime_license_files(libffi_license, openssl_license)
                runtime = self._source_tree(root)
                stage = Path(temporary_dir) / "DavinciTrackVisualizer-1.2.3-windows-x64"
                stage_package(
                    stage,
                    runtime,
                    BuildTarget("windows", "x86_64"),
                    root=root,
                    version="1.2.3",
                    dependency_licenses=licenses,
                )

            self.assertEqual(
                (stage / "licenses" / "libffi-LICENSE.txt").read_bytes(),
                libffi_content,
            )
            self.assertEqual(
                (stage / "licenses" / "OpenSSL-LICENSE.txt").read_bytes(),
                openssl_content,
            )
            openssl_license.write_bytes(b"changed\n")
            with (
                patch(
                    "scripts.build_release.WINDOWS_LIBFFI_LICENSE_SHA256",
                    hashlib.sha256(libffi_content).hexdigest(),
                ),
                patch(
                    "scripts.build_release.WINDOWS_OPENSSL_LICENSE_SHA256",
                    hashlib.sha256(openssl_content).hexdigest(),
                ),
                self.assertRaisesRegex(RuntimeError, "OpenSSL 3.0.16"),
            ):
                windows_runtime_license_files(libffi_license, openssl_license)

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

    def test_installer_lifecycle_uses_temporary_roots_and_preserves_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "source"
            root.mkdir()
            runtime = self._source_tree(root)
            target = BuildTarget(platform_name(), "x86_64")
            stage = Path(temporary_dir) / f"DavinciTrackVisualizer-1.2.3-{target.tag}"
            stage_package(
                stage,
                runtime,
                target,
                root=root,
                version="1.2.3",
                dependency_licenses=self._dependency_licenses(root),
            )
            staged_runtime = RuntimeFiles(
                engine=stage / "bin" / target.executable_name("TrackVisualizerEngine"),
                runner=stage / "bin" / target.executable_name("TrackVisualizerRunner"),
                ffmpeg=stage / "bin" / target.executable_name("ffmpeg"),
                ffprobe=stage / "bin" / target.executable_name("ffprobe"),
            )
            install_root = Path(temporary_dir) / "temporary-install"
            script_dir = Path(temporary_dir) / "temporary-resolve-scripts"
            install_state = install_root / "install-state.json"
            common_arguments = [
                "--language",
                "en",
                "--no-pause",
                "--install-root",
                str(install_root),
                "--resolve-script-dir",
                str(script_dir),
            ]

            with (
                patch.object(track_visualizer_installer, "resource_root", return_value=stage),
                patch.object(track_visualizer_installer, "stop_existing_processes"),
                patch.object(track_visualizer_installer, "unregister_runner_autostart"),
            ):
                self.assertEqual(track_visualizer_installer.main(common_arguments), 0)

                required = _installer_smoke_required_files(
                    staged_runtime, stage, install_root, script_dir
                )
                self.assertIn(install_state, required)
                self.assertTrue(all(path.is_file() for path in required))
                installed_script = script_dir / "Track Visualizer.lua"
                script_text = installed_script.read_text(encoding="utf-8")
                replacements = {
                    "__INSTALL_ROOT__": str(install_root),
                    "__ENGINE_EXECUTABLE__": str(install_root / staged_runtime.engine.name),
                    "__RUNNER_EXECUTABLE__": str(install_root / staged_runtime.runner.name),
                    "__FFMPEG_EXECUTABLE__": str(install_root / staged_runtime.ffmpeg.name),
                    "__FFPROBE_EXECUTABLE__": str(install_root / staged_runtime.ffprobe.name),
                }
                for marker, replacement in replacements.items():
                    self.assertNotIn(marker, script_text)
                    self.assertIn(replacement, script_text)

                preserved = {
                    install_root / "settings.json": "settings\n",
                    install_root / "outputs" / "mix.mp4": "output\n",
                    install_root / "tasks" / "pending.json": "task\n",
                    install_root / "tmp" / "working.txt": "temporary\n",
                    install_root / "logs" / "engine.log": "log\n",
                    install_root / "custom.dat": "unknown\n",
                    install_root / "licenses" / "custom" / "USER.txt": "user notice\n",
                    script_dir / "Another Utility.lua": "other script\n",
                }
                for path, content in preserved.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")

                self.assertEqual(
                    track_visualizer_installer.main(["--uninstall", *common_arguments]), 0
                )

            self.assertTrue(all(not path.exists() for path in required))
            self.assertFalse(install_state.exists())
            for path, content in preserved.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
