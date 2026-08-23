from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
BUILD_SCRIPT = ROOT / "packaging" / "scripts" / "build_ffmpeg.sh"
PYTHON_BUILD_SCRIPT = ROOT / "packaging" / "scripts" / "build_python.sh"
RELEASE_LOCK = ROOT / "requirements-release.txt"
BASH = shutil.which("bash")
if BASH is None:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    BASH = str(git_bash) if git_bash.is_file() else None


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
        cls.python_build_script = PYTHON_BUILD_SCRIPT.read_text(encoding="utf-8")
        cls.release_lock = RELEASE_LOCK.read_text(encoding="utf-8")

    def test_all_actions_are_pinned_to_full_commit_shas(self) -> None:
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", self.workflow, flags=re.MULTILINE)
        self.assertGreater(len(uses), 0)
        invalid = [value for value in uses if not re.fullmatch(r"[^@]+@[0-9a-f]{40}", value)]
        self.assertEqual(invalid, [])

    def test_four_native_targets_and_current_explicit_runner_labels_remain(self) -> None:
        targets = re.findall(r"^\s*- target: (\S+)$", self.workflow, flags=re.MULTILINE)
        self.assertEqual(targets, ["windows-x64", "linux-x64", "macos-arm64", "macos-x64"])
        for runner in ("windows-2025", "ubuntu-24.04", "macos-15", "macos-15-intel"):
            self.assertIn(f"runner: {runner}", self.workflow)

    def test_dependency_sources_build_cache_and_corresponding_sources_are_pinned(self) -> None:
        self.assertIn('FFMPEG_VERSION: "9.0.1"', self.workflow)
        self.assertIn("https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz", self.workflow)
        self.assertIn(
            "cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635",
            self.workflow,
        )
        self.assertNotIn("7.1.1", self.workflow)
        self.assertNotIn("zlib", self.workflow.lower())
        self.assertIn("Restore unsigned FFmpeg build", self.workflow)
        self.assertIn("Restore shared CPython build", self.workflow)
        self.assertEqual(self.workflow.count("uses: actions/cache@"), 2)
        self.assertNotIn("cache: pip", self.workflow)
        self.assertIn("hashFiles('packaging/scripts/build_ffmpeg.sh')", self.workflow)
        self.assertIn("hashFiles('packaging/scripts/build_python.sh')", self.workflow)
        self.assertNotIn("restore-keys:", self.workflow)
        self.assertEqual(self.workflow.count("--verify-prefix"), 2)
        self.assertIn("Verify cached or freshly built FFmpeg", self.workflow)
        self.assertIn("Upload exact dependency corresponding source", self.workflow)
        self.assertIn("name: native-dependency-sources", self.workflow)
        self.assertIn("path: artifacts/source", self.workflow)
        self.assertIn("mutagen-1.47.0.tar.gz", self.workflow)
        self.assertIn(
            "719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99",
            self.workflow,
        )
        self.assertIn("Python-3.12.13.tar.xz", self.workflow)
        self.assertIn(
            "c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684",
            self.workflow,
        )
        self.assertIn("libffi-3.4.8.tar.gz", self.workflow)
        self.assertIn(
            "bc9842a18898bfacb0ed1252c4febcc7e78fa139fd27fdc7a3e30d9d9356119b",
            self.workflow,
        )
        self.assertNotIn("Verify external build tools", self.workflow)

    def test_ffmpeg_cache_has_explicit_per_target_toolchain_revisions(self) -> None:
        revisions = (
            "msys2-20260611-gcc-16.1.0-5",
            "manylinux-2_28-2026.05.01-1-1d3ecb1a",
            "xcode-16.4-16F6-macos15.5-r1",
        )
        for revision in revisions:
            self.assertIn(f"toolchain_revision: {revision}", self.workflow)
        self.assertEqual(self.workflow.count("toolchain_revision:"), 4)
        self.assertEqual(
            self.workflow.count("toolchain_revision: xcode-16.4-16F6-macos15.5-r1"),
            2,
        )
        self.assertIn("${{ matrix.toolchain_revision }}", self.workflow)
        self.assertIn("/Applications/Xcode_16.4.app/Contents/Developer", self.workflow)
        self.assertIn("Build version 16F6", self.workflow)

    def test_windows_and_linux_build_environments_are_immutable_and_gated(self) -> None:
        self.assertIn(
            "msys2/setup-msys2@66cd2cce69caa17b53920067426061ca1de3a884",
            self.workflow,
        )
        self.assertIn("mingw-w64-ucrt-x86_64-gcc 16.1.0-5", self.workflow)
        self.assertIn("manylinux_2_28_x86_64:2026.05.01-1@sha256:", self.workflow)
        self.assertIn('version != "2.28"', self.workflow)

    def test_matrix_uses_direct_empty_or_pinned_container_images(self) -> None:
        self.assertEqual(self.workflow.count('container_image: ""'), 3)
        self.assertIn(
            "container_image: quay.io/pypa/manylinux_2_28_x86_64:2026.05.01-1@sha256:",
            self.workflow,
        )
        self.assertIn("container: ${{ matrix.container_image }}", self.workflow)
        self.assertNotIn("fromJSON", self.workflow)
        self.assertNotIn('container_config: "null"', self.workflow)

    def test_python_runtime_is_exactly_pinned_and_verified(self) -> None:
        self.assertIn('python-version: "3.12.13"', self.ci_workflow)
        self.assertNotIn('python-version: "3.12"', self.ci_workflow)
        self.assertEqual(self.workflow.count('python-version: "3.12.13"'), 3)
        self.assertEqual(self.workflow.count("expected='3.12.13'"), 4)
        self.assertEqual(self.workflow.count('python_version: "3.12.10"'), 3)
        self.assertEqual(self.workflow.count('python_version: "3.12.13"'), 1)
        self.assertIn("python-version: ${{ matrix.python_version }}", self.workflow)
        self.assertIn("TVIZ_PYTHON_VERSION: ${{ matrix.python_version }}", self.workflow)
        self.assertIn("expected=os.environ['TVIZ_PYTHON_VERSION']", self.workflow)
        self.assertIn("/opt/python/cp312-cp312/bin/python", self.workflow)
        self.assertIn("Build shared CPython for Linux packaging", self.workflow)
        self.assertIn("--target \"$TVIZ_PYTHON_PREFIX/lib/python3.12/site-packages\"", self.workflow)
        self.assertIn("--enable-shared", self.python_build_script)
        self.assertIn("--without-static-libpython", self.python_build_script)
        self.assertIn("--without-ensurepip", self.python_build_script)
        self.assertIn("LIBFFI_CFLAGS", self.python_build_script)
        self.assertIn("LIBFFI_LIBS", self.python_build_script)
        self.assertIn("--disable-shared", self.python_build_script)
        self.assertIn("--enable-static", self.python_build_script)
        self.assertIn("import ctypes", self.python_build_script)
        self.assertIn("[[:space:]]+PY_VERSION[[:space:]]+", self.python_build_script)
        self.assertIn("Py_ENABLE_SHARED", self.python_build_script)

    @unittest.skipUnless(BASH, "bash is required for build script syntax tests")
    def test_dependency_build_scripts_parse_as_bash(self) -> None:
        result = subprocess.run(
            [str(BASH), "-n", str(BUILD_SCRIPT), str(PYTHON_BUILD_SCRIPT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_release_version_pattern_accepts_zero_major_semver(self) -> None:
        match = re.search(r'version_pattern = r"([^"]+)"', self.workflow)
        self.assertIsNotNone(match)
        pattern = re.compile(match.group(1))
        for version in ("0.1.0", "1.0.0", "12.34.56-preview.1"):
            self.assertIsNotNone(pattern.fullmatch(version), version)
        for version in ("0", "0.1", "01.2.3", "1.02.3", "v1.2.3"):
            self.assertIsNone(pattern.fullmatch(version), version)

    def test_syft_is_downloaded_from_checksum_pinned_official_archives(self) -> None:
        self.assertNotIn("anchore/sbom-action@", self.workflow)
        self.assertNotIn("raw.githubusercontent.com/anchore/syft", self.workflow)
        self.assertIn("scripts/generate_release_sbom.py", self.workflow)
        self.assertIn("syft_1.42.3_checksums.txt", self.workflow)
        for digest in (
            "3c4a66ddb6e0689fac2be19247064f6053e2a2746035dfbcef8609baa9088f92",
            "e1b9f4945aa64c2b34970bec617623d7f803d0661b48a50b966768b363322e2d",
            "0d6be741479eddd2c8644a288990c04f3df0d609bbc1599a005532a9dff63509",
            "d71ee7db2be0fe2e96f679fd9d69ef04274cc86c8604707797080a21070b3f32",
            "c00d01b7c43504708c8922d643d1cbaefa62ca8876baa4d2c2cf4c3be43707a9",
        ):
            self.assertIn(digest, self.workflow)

    def test_release_dependencies_are_wheel_only_and_fully_hash_locked(self) -> None:
        self.assertIn("--only-binary=:all:", self.release_lock)
        self.assertIn("--require-hashes", self.release_lock)
        self.assertEqual(self.release_lock.count("--hash=sha256:"), 15)
        for package in (
            "altgraph==0.17.5",
            "macholib==1.16.3",
            "mutagen==1.47.0",
            "packaging==26.3",
            "pefile==2024.8.26",
            "Pillow==12.2.0",
            "PyInstaller==6.20.0",
            "pyinstaller-hooks-contrib==2026.6",
            "pywin32-ctypes==0.2.3",
            "setuptools==84.0.0",
        ):
            self.assertIn(package, self.release_lock)
        self.assertIn(
            "--only-binary=:all: --require-hashes -r requirements-release.txt",
            self.workflow,
        )
        self.assertNotIn("-r requirements-build.txt", self.workflow)

    def test_ffmpeg_recipe_uses_only_required_static_components_and_is_offline(self) -> None:
        for option in (
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
            "--extra-ldflags=-static",
        ):
            self.assertIn(option, self.build_script)
        self.assertNotIn("--enable-nonfree", self.build_script)
        self.assertNotRegex(self.build_script, r"--enable-lib[\w-]+")
        self.assertNotIn("zlib", self.build_script.lower())
        self.assertNotIn("png", self.build_script.lower())
        self.assertNotRegex(self.build_script, r"\b(?:curl|wget|git clone)\b")
        self.assertIn("objdump -p", self.build_script)
        self.assertIn("otool -L", self.build_script)
        self.assertIn("ldd", self.build_script)
        self.assertIn("--verify-dependencies", self.build_script)
        self.assertIn("Unexpected non-system runtime dependencies", self.build_script)

    @unittest.skipUnless(BASH, "bash is required for dependency allowlist tests")
    def test_ffmpeg_runtime_dependency_allowlists_reject_non_system_libraries(self) -> None:
        cases = (
            ("windows", "DLL Name: KERNEL32.dll\r\nDLL Name: api-ms-win-crt-runtime-l1-1-0.dll\r\n", True),
            ("windows", "DLL Name: KERNEL32.dll\nDLL Name: libwinpthread-1.dll\n", False),
            (
                "macos",
                "/tmp/ffmpeg:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n",
                True,
            ),
            (
                "macos",
                "/tmp/ffmpeg:\n\t/opt/homebrew/opt/zlib/lib/libz.1.dylib (compatibility version 1.0.0)\n",
                False,
            ),
            ("linux", "libm.so.6 => /lib64/libm.so.6 (0x1)\n/lib64/ld-linux-x86-64.so.2 (0x2)\n", True),
            ("linux", "libz.so.1 => /lib64/libz.so.1 (0x1)\n", False),
            ("linux", "unexpected ldd output\n", False),
        )
        for platform, dependencies, accepted in cases:
            with self.subTest(platform=platform, accepted=accepted):
                result = subprocess.run(
                    [str(BASH), str(BUILD_SCRIPT), "--verify-dependencies", platform],
                    input=dependencies,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_release_output_is_isolated_and_exactly_validated_after_sbom(self) -> None:
        self.assertIn(
            "TVIZ_RELEASE_DIR: ${{ github.workspace }}/build/release-output-",
            self.workflow,
        )
        self.assertNotIn("Clean release output", self.workflow)
        self.assertNotIn("shutil.rmtree('release'", self.workflow)
        self.assertNotIn("path: release/*", self.workflow)
        self.assertIn("Validate exact release artifact set", self.workflow)
        self.assertIn("actual != expected", self.workflow)
        self.assertLess(
            self.workflow.index("name: Generate SPDX SBOM"),
            self.workflow.index("name: Validate exact release artifact set"),
        )
        self.assertLess(
            self.workflow.index("name: Validate exact release artifact set"),
            self.workflow.index("name: Upload target artifacts"),
        )

    def test_publication_is_draft_first_exact_and_attestation_gated(self) -> None:
        self.assertNotIn("softprops/action-gh-release@", self.workflow)
        self.assertIn("name: Gate release publication", self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn('ATTEST_RESULT: ${{ needs.attest.result }}', self.workflow)
        self.assertIn("needs.release-gate.result == 'success'", self.workflow)
        self.assertIn("subject-path: release-assets/**/*", self.workflow)
        self.assertIn("Fail closed if a release already exists", self.workflow)
        self.assertIn('gh release create "${{ github.ref_name }}"', self.workflow)
        self.assertIn("--draft", self.workflow)
        self.assertIn("Validate exact remote draft asset names", self.workflow)
        self.assertIn("actual != expected", self.workflow)
        self.assertIn("-F draft=false", self.workflow)
        self.assertLess(
            self.workflow.index("name: Validate exact remote draft asset names"),
            self.workflow.index("name: Publish validated prerelease draft"),
        )


if __name__ == "__main__":
    unittest.main()
