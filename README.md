# Resolve Track Visualizer

[Русская документация](docs/README.ru.md)

[![CI](https://github.com/denprog5/resolve-track-visualizer/actions/workflows/ci.yml/badge.svg)](https://github.com/denprog5/resolve-track-visualizer/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)

Resolve Track Visualizer creates music player overlays for the audio clips of a DaVinci Resolve timeline. A Lua menu script reads the active timeline, a bundled engine prepares cover art, metadata, waveform and the static player layers, and each player is a lightweight Fusion composition whose time readout and progress are driven by expressions.

## Features

- Five skins: Classic, Minimal, Portrait Glass, Compact and Wave, each with its own settings and default palette.
- Fourteen built-in palettes, plus your own saved palettes that work with every skin.
- Player presets: save the complete style (skin, layout, elements, colors, fonts) under a name, apply it later, rename, delete, and export/import it as a `.tviz-preset.json` file.
- DJ-mix aware placement: tracks split across several audio tracks and overlapping in crossfades get one continuous row of players. The switch point is selectable (middle of the crossfade, start of the next track, or end of the current one), and a clip that plays entirely inside another track does not get its own player.
- Trims on either side are respected: the time readout and progress start from the clip's source offset, and progress can show the position in the whole track or in the clip.
- Non-blocking panel: look, timeline and a large preview on one page; fine-tuning on **Look**, presets and palettes in **Library**, log and language in **Service**.
- MP3, WAV, FLAC, M4A, AAC and OGG metadata and embedded artwork; waveform analysis with loudness-aware scaling.
- Russian and English UI.
- Private Windows x64 release-candidate builds and a separate manual Linux x64 packaging canary.

## Status

Version `0.1.0` is a preview. It has been verified only with **DaVinci Resolve Studio 20.2.1 on Windows x64**. Resolve 21 testing is deferred. The current UIManager interface requires Resolve Studio, so Resolve Free is not supported. Resolve 19 or older, Resolve 21, and Linux Resolve hosts have not been certified. See the [compatibility matrix](docs/compatibility.md).

Windows x64 is the only release-candidate target. Linux x64 is an independently triggered, unpublished canary build and is not part of release-candidate publication. macOS is unsupported, unbuilt, and outside the current release scope. These are packaging targets, not additional Resolve compatibility claims; see [Release process](docs/releasing.md).

Native artifacts are **not code-signed**. Immediately before every upload, the workflow re-queries repository visibility through the GitHub API and fails unless it is private. Artifacts have one-day retention, and no workflow creates or publishes a GitHub Release. Before changing repository visibility, maintainers must delete all retained native artifacts and their workflow runs because a workflow cannot protect data retained after the run finishes. The assembled private artifact extracts to `artifacts/`, `source/`, and a root `SHA256SUMS`. From that extracted root, verify every relative path before running anything:

```bash
sha256sum -c SHA256SUMS
```

## Languages

On the first launch, **Auto (system)** chooses Russian for a Russian system UI language and English for every other language. Existing settings created by the former Russian-only version remain Russian after migration.

The language can be changed on the **Service** tab under **Language**. Close and reopen Track Visualizer after changing it; theme and style values are preserved. The installer also accepts `--language auto`, `--language en`, or `--language ru`.

## Install And Run

The currently verified installation flow uses `TrackVisualizerSetup-0.1.0-windows-x64.exe`. It installs the engine under `%LOCALAPPDATA%\DavinciTrackVisualizer\` and the Resolve menu script under:

```text
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Track Visualizer.lua
```

Restart Resolve, then open:

```text
Workspace -> Scripts -> Utility -> Track Visualizer
```

The Windows release-candidate workflow produces:

| Target | Artifact | Application data |
| --- | --- | --- |
| Windows x64 | `.exe` and `.zip` | `%LOCALAPPDATA%\DavinciTrackVisualizer` |

The separate manual Linux x64 canary produces an executable in a `.tar.gz` and uses `$XDG_DATA_HOME/DavinciTrackVisualizer` or `~/.local/share/DavinciTrackVisualizer`. It requires glibc 2.28 or later, remains unpublished, and is not a release candidate. Both native builds receive package smoke tests, but Resolve integration is verified only on Windows x64.

The same setup executable supports a non-destructive uninstall:

```powershell
.\TrackVisualizerSetup-0.1.0-windows-x64.exe --uninstall --no-pause
```

Uninstall removes only managed runtime files and the Resolve menu script. User settings, logs, tasks, temporary work, rendered outputs, and unknown files are preserved so they can be recovered or removed manually.

Basic workflow:

1. Put music clips on audio tracks such as `A1`, `A2` and `A3`; overlapping crossfades and trims are fine.
2. Open Track Visualizer. On **Players**, pick a skin, palette or saved preset; the preview updates immediately.
3. Set the audio tracks (for example `1-3`), the video track for the players, and how overlapping tracks switch.
4. Choose **Create players**. Running it again replaces the players on that video track; **Remove players** deletes them.

Players are placed only on an empty range of the chosen video track. The plugin keeps its carrier clip and layers in a `Track Visualizer` Media Pool bin and never creates helper timelines. **Remove old helper timelines** on the **Service** tab cleans up timelines left by earlier preview versions.

## Development

CI uses Python 3.12.13 on Linux and Python 3.12.10 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The skin catalog embedded in the Lua script is generated from `davinci_track_visualizer/skins.py`. After changing skins or palettes run `python scripts/sync_lua_catalog.py` (CI-style check: `--check`).

Parse the Resolve Lua script without executing it:

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; from luaparser import ast; ast.parse(Path(r'resolve_scripts/Track Visualizer.lua').read_text(encoding='utf-8'))"
```

The supported reproducible release path is the manually dispatched GitHub Actions workflow in the private repository. A direct `scripts/build_release.py` invocation is an advanced equivalent: it requires exactly Python 3.12.10 on Windows or 3.12.13 on Linux, a verified matching FFmpeg/FFprobe pair, and explicit `--ffmpeg-license`, `--ffmpeg-version`, `--ffmpeg-source-url`, and `--ffmpeg-source-sha256` values. Finding FFmpeg on `PATH` alone is insufficient. On Windows, also pass verified files through `--windows-libffi-license` and `--windows-openssl-license`; the script also enforces Python user-site isolation.

Native Actions builds do not trust runner-provided FFmpeg binaries. They build a minimal pinned FFmpeg 9.0.1 from its verified official source archive. Windows packaging also downloads the official Python 3.12.10 x64 installer, verifies its exact digest and Python Software Foundation Authenticode signer, and installs it into runner-temporary storage instead of using the hosted toolcache. The Windows release candidate and Linux canary are separate manual runs. Pull requests and pushes to `main` run tests and Lua parsing on Windows and Linux without compiling FFmpeg or running PyInstaller.

## Project Policy

- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Release process](docs/releasing.md)
- [Compatibility](docs/compatibility.md)

Copyright (C) 2026 denprog5. Licensed under the [GNU General Public License, version 3 or later](LICENSE), SPDX identifier `GPL-3.0-or-later`.

DaVinci Resolve is a trademark of Blackmagic Design Pty Ltd. This project is independent and is not affiliated with or endorsed by Blackmagic Design.
