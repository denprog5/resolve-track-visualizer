# Release Process

Release artifacts are preview builds and are not code-signed or notarized. The workflow does not create placeholder signatures.

## Triggers

`.github/workflows/release.yml` supports:

- Manual runs, which build and retain workflow artifacts without creating a GitHub Release.
- Tags matching `v*.*.*`, which build artifacts and publish a GitHub prerelease.

The requested version must exactly match `davinci_track_visualizer.__version__`. For version `0.1.0`, the release tag is `v0.1.0`.

## Native Targets

| Product target | GitHub-hosted runner | Native build environment | Recorded runtime baseline |
| --- | --- | --- | --- |
| Windows x64 | `windows-2025` | MSYS2 UCRT64 20260611, GCC 16.1.0-5 | Windows x64 with Universal CRT |
| Linux x64 | `ubuntu-24.04` | pinned `manylinux_2_28_x86_64` container | glibc 2.28 or later |
| macOS arm64 | `macos-15` | Xcode 16.4, build 16F6 | macOS 15 arm64 |
| macOS Intel | `macos-15-intel` | Xcode 16.4, build 16F6 | macOS 15 x86_64 |

The Linux container is `quay.io/pypa/manylinux_2_28_x86_64:2026.05.01-1@sha256:1d3ecb1a3e411f58bc3fd36668d2976db869d64bceaf3486ef2541b0105d2d31`. The job fails unless the running libc reports exactly 2.28, and the packaged engine, runner, installer, FFmpeg, and smoke tests all run inside that environment. This supports a glibc 2.28 minimum claim; it does not make the binaries libc-independent or compatible with musl.

CI and every release Python step use CPython 3.12.13. Release dependencies come only from wheels selected by `requirements-release.txt`; all direct and transitive versions and the exact wheels for the four native targets are SHA-256 locked.

The matrix is intentionally separate from PR CI because native packaging is comparatively expensive. A successful native build and smoke test does not establish compatibility with an untested Resolve host; only DaVinci Resolve Studio 20.2.1 has been verified.

## Packaged Dependency Provenance

The release uses the unmodified official FFmpeg 9.0.1 source archive:

- URL: `https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz`
- SHA-256: `cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`
- Build recipe: `packaging/scripts/build_ffmpeg.sh`

The prepare job downloads the archive and verifies its digest. Each target downloads that workflow artifact, verifies the digest again, extracts it, and builds natively. The exact archive is included in the assembled workflow bundle and published as a separate GitHub Release asset for tag builds, so corresponding source is distributed beside the binaries rather than relying only on an upstream link.

The bundled Mutagen library is GPL-2.0-or-later. The prepare job also downloads the exact PyPI `mutagen-1.47.0.tar.gz` source archive from `https://files.pythonhosted.org/packages/81/e6/64bc71b74eef4b68e61eb921dcf72dabd9e4ec4af1e11891bbd312ccbb77/mutagen-1.47.0.tar.gz` and verifies SHA-256 `719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99`. That archive is published beside the binaries and recorded in each package as `MUTAGEN_SOURCE_OFFER.txt`.

The recipe enables GPL and version-3 terms, builds the FFmpeg libraries statically into `ffmpeg` and `ffprobe`, and uses `--disable-everything` before enabling only the application allowlist. That allowlist covers AAC, ALAC, FLAC, MP3, Opus, Vorbis, and 16-bit PCM input decoding; AAC, AIFF, FLAC, MOV/M4A, MP3, Ogg, rawvideo, and WAV demuxing; mono `s16le` output; qtrle and `prores_ks` MOV overlay output; required conversion filters and parsers; and only `file`/`pipe` protocols. Shared libraries, autodetected optional libraries, network protocols, `ffplay`, and x86 assembly dependencies are disabled. PNG is handled by Pillow and is not enabled in FFmpeg, so the release FFmpeg has no zlib dependency. Operating-system runtime libraries such as libc, the Universal CRT, and macOS system libraries remain dynamic platform dependencies.

After every build or cache restore, `packaging/scripts/build_ffmpeg.sh` rejects runtime dependencies outside platform system-library allowlists. In particular, Windows MinGW runtime DLLs, non-system macOS paths such as Homebrew, missing Linux libraries, and Linux libraries outside the glibc/GCC runtime allowlist fail the build. `scripts/build_release.py` rejects the wrong version, architecture, license/configuration, any configure option outside the exact recipe, missing local protocols, or exposed network protocols. It also executes capability tests based on the application command shapes:

- WAV input decoded and resampled to mono `s16le` on stdout;
- RGBA rawvideo stdin and qtrle alpha MOV output;
- RGBA rawvideo input and `prores_ks` 4444 alpha MOV output;
- duration and tag JSON queries through `ffprobe`.

Packages contain `FFMPEG_BUILD_INFO.txt`, FFmpeg's GPLv3 license text, `FFMPEG_SOURCE_OFFER.txt`, `MUTAGEN_SOURCE_OFFER.txt`, dependency license texts, and the exact FFmpeg build script. The release manifest records the FFmpeg version, source URL and digest, plus the runtime baseline.

## Cache Policy

Only the unsigned installed FFmpeg prefix is cached. The key includes the FFmpeg version and official source digest, configuration revision, target, explicit per-target toolchain revision, and the build-script hash; there are no broad restore keys. Windows verifies the exact MSYS2 GCC package, Linux runs in the digest-pinned manylinux image, and both macOS targets select and verify Xcode 16.4 build 16F6 before cache access. The toolchain revision is bumped whenever those inputs or the runner baseline change. Source is downloaded and verified on every workflow run, restored binaries are always revalidated and exercised, and final product artifacts are never restored from this cache.

Expected hosted-runner timings are approximate and vary with repository visibility and runner allocation:

| Run | Per-target work | Expected end-to-end wall time with four parallel targets |
| --- | --- | --- |
| Cold cache | FFmpeg 9-27 minutes, packaging/SBOM 5-10 minutes | about 20-42 minutes |
| Warm cache | source verification under 1 minute, packaging/SBOM 5-10 minutes | about 8-15 minutes |

Windows is normally the slowest cold target. Cache eviction, a recipe/source/toolchain change, or target-specific cache isolation causes a cold rebuild.

## Builder Interface

The workflow passes exact dependency inputs to the builder:

```text
python scripts/build_release.py \
  --ffmpeg <target-prefix>/bin/ffmpeg \
  --ffprobe <target-prefix>/bin/ffprobe \
  --ffmpeg-license <ffmpeg-source>/COPYING.GPLv3 \
  --ffmpeg-version 9.0.1 \
  --ffmpeg-source-url https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz \
  --ffmpeg-source-sha256 cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635 \
  --runtime-baseline <target-baseline> \
  --release-dir release
```

The builder derives the product version from `davinci_track_visualizer.__version__`, detects the native host/architecture, and rejects unsupported or non-64-bit hosts. The license, exact FFmpeg version, source URL, and source digest are mandatory. It also refuses to build into a nonempty output directory and never deletes stale user artifacts. The workflow uses a run-specific directory under `runner.temp` and, after generating the SBOM, requires the exact target-specific artifact set before upload.

The builder produces:

- a target-specific portable `.zip` on Windows or `.tar.gz` on Linux/macOS;
- a target-specific native installer executable;
- an additional `.tar.gz` around the installer on Linux/macOS so executable mode is preserved.

The builder runs native engine, runner, installer dry-run, and FFmpeg capability smoke tests before output is accepted. The workflow generates SPDX JSON with official Syft 1.42.3 binaries. Each target archive is verified against a hardcoded SHA-256 and Anchore's checksum manifest; the manifest itself is pinned by SHA-256. No mutable installer script is executed. The workflow uploads per-target artifacts and creates `SHA256SUMS` over the assembled binaries plus exact FFmpeg and Mutagen sources. Duplicate filenames fail assembly because GitHub Release assets have a flat filename namespace.

Tag publication fails if any release, including a draft, already exists for the tag. A new prerelease remains a draft while all current assets are uploaded and its remote asset names are compared with the assembled local set. Only that validated draft is published, so failed uploads cannot expose a partial release and reruns cannot retain stale assets.

## Remaining Limitations

- Builds are unsigned and macOS artifacts are not notarized.
- FFmpeg is configured without x86 assembly, PNG/zlib, or optional external codec libraries. This improves provenance and portability at the cost of encoding/decoding performance and formats outside the application allowlist.
- Runner operating-system images can change under fixed GitHub labels. The FFmpeg source/configuration, Linux/Windows dependency environments, and selected macOS Xcode build are pinned, but complete bit-for-bit reproducibility of PyInstaller output across future hosted-runner image revisions is not claimed.
- The Windows UCRT and macOS system libraries are not statically linked. Linux requires glibc 2.28 or later and does not support musl.
- Native smoke tests validate packaged behavior, not actual DaVinci Resolve integration on every target.
- `macos-15-intel` is GitHub's final Intel label and is currently scheduled only through August 2027; the target needs another builder after that service ends.

## Attestations

Build provenance attestations cover the complete assembled release bundle, including corresponding source archives and `SHA256SUMS`. They run automatically for public repositories and publication is gated on their success. GitHub currently requires GitHub Enterprise Cloud for attestations from private repositories; an eligible private repository can set the repository variable `ENABLE_PRIVATE_ATTESTATIONS=true`. Private repositories without that setting intentionally skip attestation, and a separate gate allows publication only for that explicit skip. Attestations are not a substitute for code signing.
