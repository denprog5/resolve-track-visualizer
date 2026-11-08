from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOW_DIR / "native-build.yml"
RELEASE_WORKFLOW = WORKFLOW_DIR / "release.yml"
LINUX_CANARY_WORKFLOW = WORKFLOW_DIR / "linux-canary.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
BUILD_SCRIPT = ROOT / "packaging" / "scripts" / "build_ffmpeg.sh"
PYTHON_BUILD_SCRIPT = ROOT / "packaging" / "scripts" / "build_python.sh"
RELEASE_LOCK = ROOT / "requirements-release.txt"
BASH = shutil.which("bash")
if BASH is None:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    BASH = str(git_bash) if git_bash.is_file() else None


def workflow_job(workflow: str, job_id: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_id)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Workflow job not found: {job_id}")
    return match.group("body")


def workflow_python_step(workflow: str, step_name: str) -> str:
    step = re.search(
        rf"^      - name: {re.escape(step_name)}\n(?P<body>.*?)(?=^      - name: |^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    if step is None:
        raise AssertionError(f"Workflow step not found: {step_name}")
    script = re.search(
        r"^[ ]+python - <<'PY'\n(?P<body>.*?)[ ]+PY$",
        step.group("body"),
        flags=re.MULTILINE | re.DOTALL,
    )
    if script is None:
        raise AssertionError(f"Python heredoc not found in workflow step: {step_name}")
    return textwrap.dedent(script.group("body"))


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        cls.linux_canary_workflow = LINUX_CANARY_WORKFLOW.read_text(encoding="utf-8")
        cls.ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.workflows = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(WORKFLOW_DIR.glob("*.yml"))
        }
        cls.all_workflows = "\n".join(cls.workflows.values())
        cls.build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
        cls.python_build_script = PYTHON_BUILD_SCRIPT.read_text(encoding="utf-8")
        cls.release_lock = RELEASE_LOCK.read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.releasing_docs = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
        cls.compatibility_docs = (ROOT / "docs" / "compatibility.md").read_text(encoding="utf-8")
        cls.third_party_notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        cls.packaged_notices = (ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt").read_text(
            encoding="utf-8"
        )
        cls.release_builder = (ROOT / "scripts" / "build_release.py").read_text(encoding="utf-8")

    def test_all_actions_are_pinned_to_full_commit_shas(self) -> None:
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", self.all_workflows, flags=re.MULTILINE)
        self.assertGreater(len(uses), 0)
        invalid = [
            value
            for value in uses
            if not value.startswith("./") and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", value)
        ]
        self.assertEqual(invalid, [])

    def test_windows_candidate_and_linux_canary_are_separate_manual_entry_points(self) -> None:
        self.assertIn("workflow_dispatch:", self.release_workflow)
        self.assertIn("target: windows-x64", self.release_workflow)
        self.assertIn("channel: release-candidate", self.release_workflow)
        self.assertNotIn("linux-x64", self.release_workflow)
        self.assertNotIn("push:", self.release_workflow)

        self.assertIn("workflow_dispatch:", self.linux_canary_workflow)
        self.assertIn("target: linux-x64", self.linux_canary_workflow)
        self.assertIn("channel: canary", self.linux_canary_workflow)
        self.assertNotIn("release-candidate", self.linux_canary_workflow)
        self.assertNotIn("push:", self.linux_canary_workflow)

        for caller in (self.release_workflow, self.linux_canary_workflow):
            caller_job = workflow_job(caller, "build")
            self.assertIn("actions: write", caller_job)
            self.assertIn("contents: read", caller_job)
            self.assertLess(caller_job.index("actions: write"), caller_job.index("uses:"))

        self.assertIn("workflow_call:", self.workflow)
        self.assertNotIn("workflow_dispatch:", self.workflow)
        self.assertIn('(\"windows-x64\", \"release-candidate\")', self.workflow)
        self.assertIn('(\"linux-x64\", \"canary\")', self.workflow)
        self.assertIn("'windows-2025'", self.workflow)
        self.assertIn("'ubuntu-24.04'", self.workflow)
        self.assertNotRegex(self.all_workflows, r"(?i)macos")

    def test_ci_runs_meaningful_windows_and_fast_linux_jobs_on_push_and_pr(self) -> None:
        self.assertIn("pull_request:", self.ci_workflow)
        self.assertIn("push:", self.ci_workflow)
        linux_job = workflow_job(self.ci_workflow, "linux-test")
        windows_job = workflow_job(self.ci_workflow, "windows-test")
        self.assertIn("runs-on: ubuntu-24.04", linux_job)
        self.assertIn('python-version: "3.12.13"', linux_job)
        self.assertIn("expected='3.12.13'", linux_job)
        self.assertNotIn('python-version: "3.12.10"', linux_job)
        self.assertIn("python -m unittest discover -s tests -v", linux_job)
        self.assertIn("Parse Resolve Lua script", linux_job)
        self.assertIn("runs-on: windows-2025", windows_job)
        self.assertIn('python-version: "3.12.10"', windows_job)
        self.assertIn('expected = "3.12.10"', windows_job)
        self.assertNotIn('python-version: "3.12.13"', windows_job)
        self.assertIn("python -m unittest discover -s tests -v", windows_job)
        self.assertIn("Parse Resolve Lua script", windows_job)
        self.assertIn('PYTHONNOUSERSITE: "1"', windows_job)
        self.assertLess(
            windows_job.index('PYTHONNOUSERSITE: "1"'),
            windows_job.index("uses: actions/setup-python@"),
        )
        self.assertIn('os.environ.get("PYTHONNOUSERSITE") != "1"', windows_job)
        self.assertIn("site.ENABLE_USER_SITE is not False", windows_job)
        self.assertIn("site.getusersitepackages()", windows_job)
        self.assertIn("user_site in effective_path", windows_job)
        self.assertLess(
            windows_job.index("Windows CI Python user site is disabled"),
            windows_job.index("name: Install test dependencies"),
        )

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
        self.assertIn("hashFiles('requirements-release.txt')", self.workflow)
        self.assertIn("Clean shared Linux target packages", self.workflow)
        self.assertIn('rm -rf -- "$site_packages"', self.workflow)
        self.assertNotIn("restore-keys:", self.workflow)
        self.assertEqual(self.workflow.count("--verify-prefix"), 2)
        self.assertIn("Verify cached or freshly built FFmpeg", self.workflow)
        self.assertIn("Upload internal dependency corresponding sources", self.workflow)
        self.assertIn("Validate exact dependency source set", self.workflow)
        self.assertIn(
            "name: internal-native-sources-${{ github.run_id }}-${{ github.run_attempt }}-${{ inputs.target }}",
            self.workflow,
        )
        self.assertIn("path: release-bundle/source", self.workflow)
        self.assertIn("mutagen-1.47.0.tar.gz", self.workflow)
        self.assertIn(
            "719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99",
            self.workflow,
        )
        self.assertIn("Python-${{ env.PYTHON_SOURCE_VERSION }}.tar.xz", self.workflow)
        self.assertIn("https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tar.xz", self.workflow)
        self.assertIn(
            "07ab697474595e06f06647417d3c7fa97ded07afc1a7e4454c5639919b46eaea",
            self.workflow,
        )
        self.assertIn(
            "c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684",
            self.workflow,
        )
        self.assertIn("libffi-3.4.8.tar.gz", self.workflow)
        self.assertIn(
            "bc9842a18898bfacb0ed1252c4febcc7e78fa139fd27fdc7a3e30d9d9356119b",
            self.workflow,
        )
        self.assertRegex(
            self.workflow,
            r"Download and verify exact libffi source\n\s+if: inputs\.target == 'linux-x64'",
        )
        self.assertIn('expected.add("libffi-3.4.8.tar.gz")', self.workflow)
        windows_sources = (
            (
                "https://github.com/python/cpython-source-deps/archive/refs/tags/libffi-3.4.4.tar.gz",
                "9d802681adfea27d84cae0487a785fb9caa925bdad44c401b364c59ab2b8edda",
                "cpython-source-deps-libffi-3.4.4",
                "--required-file LICENSE",
            ),
            (
                "https://github.com/python/cpython-source-deps/archive/refs/tags/openssl-3.0.16.tar.gz",
                "6bb739ecddbd2cfb6d255eb5898437a9b5739277dee931338d3275bac5d96ba2",
                "cpython-source-deps-openssl-3.0.16",
                "--required-file LICENSE.txt",
            ),
        )
        for url, digest, archive_root, required_file in windows_sources:
            self.assertIn(url, self.workflow)
            self.assertIn(digest, self.workflow)
            self.assertGreaterEqual(self.workflow.count(f"--archive-root {archive_root}"), 2)
            self.assertIn(required_file, self.workflow)
            self.assertIn(f'"{archive_root}.tar.gz"', self.workflow)
        self.assertRegex(
            self.workflow,
            r"Download and verify exact Windows bundled libffi source\n"
            r"\s+if: inputs\.target == 'windows-x64'",
        )
        self.assertRegex(
            self.workflow,
            r"Download and verify exact Windows bundled OpenSSL source\n"
            r"\s+if: inputs\.target == 'windows-x64'",
        )
        self.assertIn("--windows-libffi-license", self.workflow)
        self.assertIn("--windows-openssl-license", self.workflow)
        self.assertNotIn("Verify external build tools", self.workflow)

    def test_dependency_source_validation_rejects_unexpected_non_files(self) -> None:
        script = workflow_python_step(self.workflow, "Validate exact dependency source set")
        self.assertIn("actual = {path.name for path in entries}", script)
        self.assertIn("path.is_symlink() or not path.is_file()", script)
        self.assertIn("if invalid or actual != expected:", script)
        self.assertNotIn("if path.is_file()", script)

        expected = {
            "ffmpeg-9.0.1.tar.xz",
            "mutagen-1.47.0.tar.gz",
            "Python-3.12.10.tar.xz",
            "cpython-source-deps-libffi-3.4.4.tar.gz",
            "cpython-source-deps-openssl-3.0.16.tar.gz",
        }
        environment = {"TARGET": "windows-x64", "PYTHON_SOURCE_VERSION": "3.12.10"}
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "build" / "dependency-source"
            source.mkdir(parents=True)
            for name in expected:
                (source / name).write_bytes(name.encode("ascii"))
            (source / "unexpected-directory").mkdir()
            with contextlib.chdir(root), patch.dict(os.environ, environment, clear=False):
                with self.assertRaisesRegex(SystemExit, "unexpected-directory"):
                    exec(compile(script, "native-build-source-validation", "exec"), {})
            self.assertFalse((source / "INTERNAL_SHA256SUMS").exists())

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "build" / "dependency-source"
            source.mkdir(parents=True)
            for name in expected:
                (source / name).write_bytes(name.encode("ascii"))
            with contextlib.chdir(root), patch.dict(os.environ, environment, clear=False):
                exec(compile(script, "native-build-source-validation", "exec"), {})
            records = (source / "INTERNAL_SHA256SUMS").read_text(encoding="ascii").splitlines()
            self.assertEqual(
                records,
                [
                    f"{hashlib.sha256(name.encode('ascii')).hexdigest()}  {name}"
                    for name in sorted(expected)
                ],
            )

    def test_ffmpeg_cache_has_explicit_per_target_toolchain_revisions(self) -> None:
        revisions = (
            "msys2-20260611-gcc-16.1.0-5",
            "manylinux-2_28-2026.05.01-1-1d3ecb1a",
        )
        for revision in revisions:
            self.assertIn(revision, self.workflow)
        self.assertIn("${{ env.TVIZ_TOOLCHAIN_REVISION }}", self.workflow)
        self.assertNotIn("Xcode", self.workflow)

    def test_windows_and_linux_build_environments_are_immutable_and_gated(self) -> None:
        self.assertIn(
            "msys2/setup-msys2@66cd2cce69caa17b53920067426061ca1de3a884",
            self.workflow,
        )
        self.assertIn("mingw-w64-ucrt-x86_64-gcc 16.1.0-5", self.workflow)
        self.assertIn("manylinux_2_28_x86_64:2026.05.01-1@sha256:", self.workflow)
        self.assertIn('version != "2.28"', self.workflow)

    def test_linux_uses_digest_pinned_container_and_windows_uses_no_container(self) -> None:
        self.assertIn(
            "quay.io/pypa/manylinux_2_28_x86_64:2026.05.01-1@sha256:",
            self.workflow,
        )
        self.assertIn("container: ${{ inputs.target == 'linux-x64'", self.workflow)
        self.assertNotIn("fromJSON", self.workflow)

    def test_python_runtime_is_exactly_pinned_and_verified(self) -> None:
        prepare_job = workflow_job(self.workflow, "prepare")
        build_job = workflow_job(self.workflow, "build")
        assemble_job = workflow_job(self.workflow, "assemble")
        self.assertIn('python-version: "3.12.13"', prepare_job)
        self.assertIn('python-version: "3.12.13"', assemble_job)
        self.assertNotIn("uses: actions/setup-python@", build_job)
        self.assertIn("TVIZ_PYTHON_VERSION: ${{ inputs.target == 'windows-x64'", self.workflow)
        self.assertIn("expected=os.environ['TVIZ_PYTHON_VERSION']", self.workflow)
        self.assertIn("/opt/python/cp312-cp312/bin/python", self.workflow)
        self.assertIn("Build shared CPython for Linux packaging", self.workflow)
        self.assertIn("--target \"$TVIZ_PYTHON_PREFIX/lib/python3.12/site-packages\"", self.workflow)
        self.assertIn("workspace=$(pwd -P)", self.workflow)
        self.assertIn("TVIZ_RELEASE_DIR=$workspace/build/release-output-$GITHUB_RUN_ID-", self.workflow)
        self.assertIn("path: build/python/linux-x64/prefix", self.workflow)
        self.assertIn("/opt/python/cp312-cp312/bin/python scripts/generate_release_sbom.py", self.workflow)
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

    def test_windows_native_python_installer_and_runtime_are_fully_verified(self) -> None:
        build_job = workflow_job(self.workflow, "build")
        self.assertIn(
            "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",
            self.workflow,
        )
        self.assertIn(
            "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb",
            self.workflow,
        )
        self.assertIn("Get-FileHash -LiteralPath $installer -Algorithm SHA256", build_job)
        self.assertIn("Get-AuthenticodeSignature -LiteralPath $installer", build_job)
        self.assertIn("Get-AuthenticodeSignature -LiteralPath $env:TVIZ_WINDOWS_PYTHON", build_job)
        self.assertEqual(build_job.count('$signer -ne "Python Software Foundation"'), 2)
        self.assertIn('"/quiet"', build_job)
        self.assertIn('"TargetDir=$target"', build_job)
        self.assertIn('"TVIZ_WINDOWS_PYTHON=$python" >> $env:GITHUB_ENV', build_job)
        self.assertIn('"PYTHONNOUSERSITE=1" >> $env:GITHUB_ENV', build_job)
        self.assertLess(
            build_job.index('"PYTHONNOUSERSITE=1" >> $env:GITHUB_ENV'),
            build_job.index("name: Install pinned Windows Python into runner temp"),
        )
        self.assertIn('expected = "3.12.10"', build_job)
        self.assertIn('struct.calcsize("P") * 8 != 64', build_job)
        self.assertIn('platform.machine().lower() not in {"amd64", "x86_64"}', build_job)
        self.assertIn('os.environ.get("PYTHONNOUSERSITE") != "1"', build_job)
        self.assertIn("site.ENABLE_USER_SITE is not False", build_job)
        self.assertIn("site.getusersitepackages()", build_job)
        self.assertIn("user_site in effective_path", build_job)
        self.assertLess(
            build_job.index("Official Windows Python user site is disabled"),
            build_job.index("name: Install build dependencies"),
        )
        for command in (
            "& $env:TVIZ_WINDOWS_PYTHON packaging/scripts/prepare_dependency_source.py",
            "& $env:TVIZ_WINDOWS_PYTHON -m pip install",
            "& $env:TVIZ_WINDOWS_PYTHON scripts/build_release.py",
            "& $env:TVIZ_WINDOWS_PYTHON scripts/generate_release_sbom.py",
            "'@ | & $env:TVIZ_WINDOWS_PYTHON -",
        ):
            self.assertIn(command, build_job)

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
        ):
            self.assertIn(digest, self.workflow)

    def test_release_dependencies_are_wheel_only_and_fully_hash_locked(self) -> None:
        self.assertIn("--only-binary=:all:", self.release_lock)
        self.assertIn("--require-hashes", self.release_lock)
        self.assertEqual(self.release_lock.count("--hash=sha256:"), 14)
        for package in (
            "altgraph==0.17.5",
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
        self.assertIn("Validate exact release artifact set on Linux", self.workflow)
        self.assertIn("Validate exact release artifact set on Windows", self.workflow)
        self.assertIn("actual != expected", self.workflow)
        for target in ("Linux", "Windows"):
            self.assertLess(
                self.workflow.index(f"name: Generate SPDX SBOM on {target}"),
                self.workflow.index(f"name: Validate exact release artifact set on {target}"),
            )
            self.assertLess(
                self.workflow.index(f"name: Validate exact release artifact set on {target}"),
                self.workflow.index(
                    f"name: Re-query live repository visibility before {target} target upload"
                ),
            )
            self.assertLess(
                self.workflow.index(
                    f"name: Re-query live repository visibility before {target} target upload"
                ),
                self.workflow.index(f"name: Upload internal {target} target transfer artifact"),
            )

    def test_internal_transfer_and_final_bundle_are_directly_checksum_verifiable(self) -> None:
        self.assertIn('manifest = root / "INTERNAL_SHA256SUMS"', self.workflow)
        self.assertIn("Verify internal dependency source checksum manifest", self.workflow)
        self.assertIn("working-directory: build/dependency-source", self.workflow)
        self.assertIn("Verify internal dependency source transfer checksums", self.workflow)
        self.assertIn('source_root = Path("release-bundle/source")', self.workflow)
        self.assertIn("Internal source transfer set mismatch", self.workflow)
        self.assertIn('manifest = output / "INTERNAL_SHA256SUMS"', self.workflow)
        self.assertEqual(self.workflow.count('manifest = output / "INTERNAL_SHA256SUMS"'), 2)
        self.assertIn(
            "name: internal-native-transfer-${{ github.run_id }}-${{ github.run_attempt }}-${{ inputs.target }}",
            self.workflow,
        )
        self.assertNotIn("name: native-${{ inputs.channel }}-${{ inputs.target }}", self.workflow)
        self.assertIn("Verify internal transfer checksums and assemble target artifacts", self.workflow)
        self.assertIn("actual != set(records)", self.workflow)
        self.assertIn("actual_digest != expected_digest", self.workflow)
        self.assertIn('destination = Path("release-bundle/artifacts")', self.workflow)
        self.assertIn('relative = path.relative_to(bundle).as_posix()', self.workflow)
        self.assertIn('(path for path in entries if path.is_file())', self.workflow)
        self.assertIn('manifest = bundle / "SHA256SUMS"', self.workflow)
        self.assertIn("working-directory: release-bundle", self.workflow)
        self.assertIn("run: sha256sum -c SHA256SUMS", self.workflow)
        self.assertIn("name: Delete internal transfer artifacts", self.workflow)
        self.assertIn("actions: write", workflow_job(self.workflow, "assemble"))
        self.assertIn("INTERNAL_SOURCE_ARTIFACT: internal-native-sources-", self.workflow)
        self.assertIn("INTERNAL_TARGET_ARTIFACT: internal-native-transfer-", self.workflow)
        self.assertNotIn("resolve-track-visualizer-${{ needs.prepare.outputs.version }}-${{ inputs.channel }}-${{ inputs.target }}\" or", self.workflow)
        self.assertRegex(
            self.workflow,
            r"(?s)name: Upload assembled release bundle.*?\n\s+path: release-bundle\n",
            msg="The final upload must contain only the assembled bundle directory",
        )
        self.assertIn("sha256sum -c SHA256SUMS", self.readme)
        self.assertIn("`artifacts/`, `source/`, and a root `SHA256SUMS`", self.readme)

    def test_only_the_release_publish_job_publishes_and_the_canary_stays_private(self) -> None:
        never = ("id-token: write", "attestations: write", "actions/attest@", "softprops/action-gh-release@", "actions/create-release@", "tags:")
        for value in never:
            self.assertNotIn(value, self.all_workflows)
        for name, workflow in self.workflows.items():
            if name != "release.yml":
                self.assertNotIn("contents: write", workflow, name)
                self.assertNotIn("gh release", workflow, name)
        publish = workflow_job(self.release_workflow, "publish")
        build = workflow_job(self.release_workflow, "build")
        self.assertNotIn("contents: write", build)
        self.assertNotIn("gh release", build)
        self.assertEqual(self.release_workflow.count("contents: write"), 1)
        for fragment in (
            "needs: build",
            "if: ${{ inputs.publish }}",
            "contents: write",
            "name: resolve-track-visualizer-${{ inputs.version }}-release-candidate-windows-x64",
            "sha256sum -c SHA256SUMS",
            "TVIZ_UPDATE_SIGNING_KEY: ${{ secrets.TVIZ_UPDATE_SIGNING_KEY }}",
            "python scripts/make_update_manifest.py",
            "--out release-bundle/artifacts/update.json",
            "python scripts/release_notes.py",
            'gh release create "v${VERSION}"',
            '--target "$GITHUB_SHA"',
            "release-bundle/source/*",
        ):
            self.assertIn(fragment, publish)
        self.assertLess(publish.index("sha256sum -c SHA256SUMS"), publish.index("make_update_manifest.py"))
        self.assertLess(publish.index("make_update_manifest.py"), publish.index("gh release create"))
        self.assertIn("default: false", self.release_workflow)
        self.assertIn("persist-credentials: false", publish)

        uploads = self.workflow.count("uses: actions/upload-artifact@")
        self.assertEqual(uploads, 4)
        self.assertEqual(re.findall(r"retention-days:\s*(\d+)", self.workflow), ["1"] * uploads)
        self.assertIn('REPOSITORY_VISIBILITY: ${{ github.repository_visibility }}', self.workflow)
        self.assertIn(
            'if os.environ["REPOSITORY_VISIBILITY"] != "private" and os.environ["CHANNEL"] != "release-candidate":',
            self.workflow,
        )
        self.assertIn("Unpublished canary artifacts may be built only in a private repository", self.workflow)
        self.assertLess(
            self.workflow.index("name: Validate build request"),
            self.workflow.index("uses: actions/upload-artifact@"),
        )
        self.assertEqual(
            self.workflow.count(
                'allowed = {"private", "public"} if os.environ["CHANNEL"] == "release-candidate" else {"private"}'
            ),
            uploads,
        )
        self.assertEqual(self.workflow.count('if repository.get("visibility") not in allowed:'), uploads)
        self.assertEqual(self.workflow.count("CHANNEL: ${{ inputs.channel }}"), uploads + 1)
        self.assertEqual(self.workflow.count('"Authorization": f"Bearer'), uploads)
        self.assertEqual(self.workflow.count('"Accept": "application/vnd.github+json"'), uploads)
        self.assertEqual(self.workflow.count('"X-GitHub-Api-Version": "2022-11-28"'), uploads)
        step_names = re.findall(r"^      - name: (.+)$", self.workflow, flags=re.MULTILINE)
        adjacent_steps = (
            (
                "Re-query live repository visibility before source upload",
                "Upload internal dependency corresponding sources",
            ),
            (
                "Re-query live repository visibility before Windows target upload",
                "Upload internal Windows target transfer artifact",
            ),
            (
                "Re-query live repository visibility before Linux target upload",
                "Upload internal Linux target transfer artifact",
            ),
            (
                "Re-query live repository visibility before assembled bundle upload",
                "Upload assembled release bundle",
            ),
        )
        for gate, upload in adjacent_steps:
            self.assertEqual(step_names.index(upload), step_names.index(gate) + 1)
        self.assertIn(
            "name: internal-native-transfer-${{ github.run_id }}-${{ github.run_attempt }}-${{ inputs.target }}",
            self.workflow,
        )
        self.assertIn(
            "name: resolve-track-visualizer-${{ needs.prepare.outputs.version }}-${{ inputs.channel }}-${{ inputs.target }}",
            self.workflow,
        )

    def test_release_docs_cover_retention_visibility_cleanup_and_macos_scope(self) -> None:
        self.assertIn("Workflow artifacts have one-day retention", self.readme)
        self.assertIn("delete all retained native artifacts and their workflow runs", self.readme)
        self.assertIn("macOS is unsupported, unbuilt", self.readme)
        self.assertIn("one-day retention", self.releasing_docs)
        self.assertIn("GET /repos/{owner}/{repo}", self.releasing_docs)
        self.assertIn("delete every retained native artifact", self.releasing_docs)
        self.assertIn("no workflow can protect artifacts or logs retained", self.releasing_docs)
        self.assertIn("macOS is unsupported, no macOS build is produced", self.releasing_docs)
        self.assertIn("macOS Resolve hosts", self.compatibility_docs)
        self.assertIn("Unsupported and unbuilt", self.compatibility_docs)
        self.assertIn("Only DaVinci Resolve Studio 20.2.1 on Windows x64", self.compatibility_docs)
        self.assertIn("Resolve 21 | Testing deferred", self.compatibility_docs)

    def test_windows_cpython_dependency_provenance_is_documented(self) -> None:
        for text in (
            self.releasing_docs,
            self.third_party_notices,
            self.packaged_notices,
        ):
            self.assertIn("libffi 3.4.4", text)
            self.assertIn("OpenSSL 3.0.16", text)
            self.assertIn("cpython-source-deps", text)
            self.assertIn(
                "9d802681adfea27d84cae0487a785fb9caa925bdad44c401b364c59ab2b8edda",
                text,
            )
            self.assertIn(
                "6bb739ecddbd2cfb6d255eb5898437a9b5739277dee931338d3275bac5d96ba2",
                text,
            )
        self.assertIn("licenses/OpenSSL-LICENSE.txt", self.third_party_notices)
        self.assertIn("licenses/OpenSSL-LICENSE.txt", self.packaged_notices)
        self.assertNotIn("libffi 3.4.8 (Linux) |", self.third_party_notices)

    def test_source_availability_text_matches_private_actions_bundle(self) -> None:
        texts = (
            self.release_builder,
            self.third_party_notices,
            self.packaged_notices,
            self.releasing_docs,
        )
        for text in texts:
            self.assertRegex(text, r"assembled (Windows )?release bundle")
            self.assertNotRegex(text.lower(), r"publish\w*[^.\n]*beside")
        self.assertNotIn("Each target verifies its inputs again", self.releasing_docs)
        self.assertIn("The build job re-verifies archives before extracting them", self.releasing_docs)


if __name__ == "__main__":
    unittest.main()
