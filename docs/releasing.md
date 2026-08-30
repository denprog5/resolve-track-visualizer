# Release Process

Native artifacts are unsigned internal validation builds. The workflows do not create or update Git tags, GitHub Releases, release drafts, attestations, or any other public distribution channel.

## Triggers And Publication Policy

- `.github/workflows/release.yml` is manual-only and requests the Windows x64 release-candidate build.
- `.github/workflows/linux-canary.yml` is a separate manual-only Linux x64 canary build. It is not a release candidate and is never included in Windows release-candidate artifacts.
- `.github/workflows/native-build.yml` is reusable only through `workflow_call` and accepts exactly `windows-x64`/`release-candidate` or `linux-x64`/`canary`.
- No native workflow has a tag trigger or write permission. Unsigned output is stored only as GitHub Actions artifacts with one-day retention.

The reusable workflow validates the target/channel and requested version before building. Immediately before every artifact upload, it queries `GET /repos/{owner}/{repo}` with the read-only workflow token and fails unless the live `visibility` response is exactly `private`. An API failure, missing field, `public`, or `internal` response fails closed.

Creating a public release remains disabled until an approved signing and publication process is implemented. A maintainer must not manually republish these unsigned workflow artifacts.

Before changing repository visibility, maintainers must delete every retained native artifact and the workflow runs that produced them. The live pre-upload gate can prevent new exposure, but no workflow can protect artifacts or logs retained after a completed run if repository visibility later changes.

## Native Targets

| Channel | Product target | GitHub-hosted runner | Native build environment | Recorded runtime baseline |
| --- | --- | --- | --- | --- |
| Release candidate | Windows x64 | `windows-2025` | MSYS2 UCRT64 20260611, GCC 16.1.0-5 | Windows x64 with Universal CRT |
| Manual unpublished canary | Linux x64 | `ubuntu-24.04` | pinned `manylinux_2_28_x86_64` container | glibc 2.28 or later |

Windows x64 is the only release-candidate target. Linux x64 exists only as an independently requested canary for packaging feedback; it is not assembled with, promoted to, or published as a release candidate.

macOS is unsupported, no macOS build is produced, and it is outside the current platform and release scope.

The Linux container is `quay.io/pypa/manylinux_2_28_x86_64:2026.05.01-1@sha256:1d3ecb1a3e411f58bc3fd36668d2976db869d64bceaf3486ef2541b0105d2d31`. The job fails unless libc reports exactly 2.28. Because the image's wheel-building Python does not provide the shared library required by PyInstaller, the job verifies and builds official CPython 3.12.13 plus libffi 3.4.8 in the pinned container. The canary requires a working `_ctypes` extension without a dynamic libffi dependency. This supports a glibc 2.28 minimum claim; it does not make the binaries libc-independent or compatible with musl.

Utility jobs use CPython 3.12.13. Windows native packaging does not trust the hosted toolcache: it downloads `python-3.12.10-amd64.exe` from python.org, verifies SHA-256 `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb`, requires a valid Python Software Foundation Authenticode signer, and installs silently under the runner temporary directory. `PYTHONNOUSERSITE=1` is set before installation and remains set through dependency installation, PyInstaller builds, staging, and SBOM generation. Before `pip` runs, the workflow fails unless the installed runtime has user-site loading disabled and the normalized user-site directory is absent from effective `sys.path`; `scripts/build_release.py` repeats this fail-closed requirement. The workflow also verifies the installed runtime's version, 64-bit architecture, and Authenticode signer. The Windows CI job likewise sets `PYTHONNOUSERSITE=1` at job scope before `setup-python` and performs the same user-site checks before installing test dependencies. Linux native packaging uses CPython 3.12.13 in the pinned Linux environment. Release dependencies come only from wheels selected by `requirements-release.txt`; direct and transitive versions and exact wheels for the two build targets are SHA-256 locked.

## CI Coverage

Pushes to `main` and pull requests run the test suite and parse the Resolve Lua script with Python 3.12.10 on `windows-2025` and Python 3.12.13 on `ubuntu-24.04`. The Windows lane exercises the currently supported release platform; the Linux lane remains a fast cross-platform regression check. CI does not compile FFmpeg, package installers, or upload native artifacts.

Native package smoke tests do not establish compatibility with an untested Resolve host. Only DaVinci Resolve Studio 20.2.1 on Windows x64 is currently verified. Resolve 21 testing is explicitly deferred and no Resolve 21 compatibility claim is made. The current UIManager interface requires Resolve Studio; Free support needs a separate UI architecture.

## Packaged Dependency Provenance

The build uses the unmodified official FFmpeg 9.0.1 source archive:

- URL: `https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz`
- SHA-256: `cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`
- Build recipe: `packaging/scripts/build_ffmpeg.sh`

The prepare job downloads and verifies the FFmpeg source plus exact corresponding source archives for Mutagen and the target's CPython runtime, then rejects any unexpected source file before internal transfer. The build job re-verifies archives before extracting them: FFmpeg on both targets, the bundled libffi/OpenSSL sources on Windows, and CPython/libffi on Linux when rebuilding the cached runtime. Mutagen and Windows CPython source archives are corresponding-source payloads rather than build inputs, so their exact prepare-job verification and artifact transfer integrity are retained without a redundant build-job extraction. Windows receives `Python-3.12.10.tar.xz` with SHA-256 `07ab697474595e06f06647417d3c7fa97ded07afc1a7e4454c5639919b46eaea`. It also receives the `python/cpython-source-deps` libffi 3.4.4 tag archive from `https://github.com/python/cpython-source-deps/archive/refs/tags/libffi-3.4.4.tar.gz` with SHA-256 `9d802681adfea27d84cae0487a785fb9caa925bdad44c401b364c59ab2b8edda`, and the OpenSSL 3.0.16 tag archive from `https://github.com/python/cpython-source-deps/archive/refs/tags/openssl-3.0.16.tar.gz` with SHA-256 `6bb739ecddbd2cfb6d255eb5898437a9b5739277dee931338d3275bac5d96ba2`; these versions and sources correspond to the official Python 3.12.10 installer SBOM. Their required archive roots are `cpython-source-deps-libffi-3.4.4` and `cpython-source-deps-openssl-3.0.16`. Before staging, the extracted libffi `LICENSE` and OpenSSL `LICENSE.txt` must match SHA-256 `2c9c2acb9743e6b007b91350475308aee44691d96aa20eacef8e199988c8c388` and `7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a`, respectively. Linux receives CPython 3.12.13 and libffi 3.4.8 source. These sources are included under `source/` in the assembled private Actions artifact; no source or binary artifact is publicly published.

The recipe enables GPL and version-3 terms and builds the FFmpeg libraries statically into `ffmpeg` and `ffprobe`. It starts with `--disable-everything` and enables only the codecs, formats, filters, and local `file`/`pipe` protocols needed by the application. Shared libraries, autodetected optional libraries, network protocols, `ffplay`, x86 assembly dependencies, PNG, and zlib are disabled. Windows uses static linker flags so MinGW runtime DLLs are not redistributed; operating-system runtime libraries such as the Universal CRT and Linux libc remain dynamic platform dependencies.

After every build or cache restore, `packaging/scripts/build_ffmpeg.sh` rejects runtime dependencies outside the target's system-library allowlist. `scripts/build_release.py` rejects the wrong version, architecture, license/configuration, unexpected FFmpeg options, missing local protocols, or exposed network protocols. It also runs WAV decoding, alpha overlay encoding, and `ffprobe` capability tests based on application command shapes.

Packages contain `FFMPEG_BUILD_INFO.txt`, FFmpeg's GPLv3 license text, corresponding-source offers, dependency license texts, and the exact FFmpeg build script. Windows packages include the verified CPython-bundled libffi and OpenSSL notices as `licenses/libffi-LICENSE.txt` and `licenses/OpenSSL-LICENSE.txt`; Linux packages include the verified libffi notice. The manifest records the FFmpeg version, source URL and digest, and runtime baseline.

## Cache And Build Policy

Only unsigned dependency build prefixes are cached. Cache keys include source versions and digests, target, explicit toolchain revision, configuration revision, build-script hashes, and, for the Linux CPython prefix, the `requirements-release.txt` hash; no broad restore keys are used. The Linux job deletes and recreates the target `site-packages` directory before reinstalling the current hash-locked requirements, so cached dependencies cannot override the lock. Windows verifies the exact MSYS2 GCC package, and Linux runs in the digest-pinned manylinux image. Sources are verified on every run, restored binaries are revalidated and exercised, and final product artifacts are never restored from cache.

The builder derives the product version from `davinci_track_visualizer.__version__`, detects the native host and architecture, and rejects unsupported or non-64-bit hosts. The workflow uses a run-specific output directory under `build/` and validates the exact target-specific artifact set after SBOM generation.

Windows output consists of the portable `.zip`, native `.exe` installer, and SPDX JSON SBOM. Linux canary output consists of the portable `.tar.gz`, native installer, mode-preserving installer `.tar.gz`, and SPDX JSON SBOM. The executable-bearing cross-job artifact is explicitly named as an internal transfer and contains `INTERNAL_SHA256SUMS`; assembly verifies that manifest covers its exact relative file set before copying files. The final private artifact contains one extracted-root layout: `artifacts/` for target outputs, `source/` for corresponding sources, and `SHA256SUMS` at the root. Final checksum records use paths relative to that root and are verified before upload.

Package smoke testing installs into an isolated temporary directory, checks the staged runtime and nested notices, then runs `--uninstall`. The lifecycle check must preserve a user-data marker while removing installer-managed files and the Resolve menu script. It never installs into the runner account's real Resolve directories.

## Remaining Limitations

- All native artifacts are unsigned and restricted to short-lived private Actions storage.
- No automated or tag-driven public release path exists.
- macOS is unsupported, unbuilt, and outside the current release scope.
- FFmpeg omits x86 assembly and optional codecs, which improves provenance and portability at the cost of performance and unsupported formats.
- Hosted runner images can change under fixed labels, so complete bit-for-bit reproducibility across future image revisions is not claimed.
- Linux requires glibc 2.28 or later and does not support musl.
- Native smoke tests validate packaged behavior, not integration with DaVinci Resolve.
- Resolve 21 validation is deferred.
