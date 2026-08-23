# Resolve Track Visualizer

[Русская документация](docs/README.ru.md)

[![CI](https://github.com/denprog5/resolve-track-visualizer/actions/workflows/ci.yml/badge.svg)](https://github.com/denprog5/resolve-track-visualizer/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)

Resolve Track Visualizer creates track cards for music timelines in DaVinci Resolve. A Lua menu script reads the active timeline, a bundled engine prepares metadata and artwork, and Resolve renders live time/progress elements in Fusion. Legacy alpha MOV rendering remains a fallback.

## Features

- Classic, Minimal, and Portrait Glass skins with independent settings and palettes.
- Live Fusion time/progress animation with per-clip alpha MOV fallback.
- Bounded immutable helper timelines for safe repeated updates of long playlists.
- MP3, WAV, FLAC, M4A, AAC, and OGG metadata and embedded artwork.
- Russian and English UI with a future-language-ready catalog.
- Native preview artifacts for Windows x64, Linux x64, macOS arm64, and macOS Intel.

## Status

Version `0.1.0` is a preview. It has been verified only with **DaVinci Resolve Studio 20.2.1 on Windows x64**. Compatibility with Resolve Free, Resolve 19 or older, Resolve 21, and Resolve hosts on macOS/Linux has not yet been certified. See the [compatibility matrix](docs/compatibility.md).

Native packaging targets Windows x64, Linux x64, macOS arm64, and macOS Intel. These are build targets, not claims that the product has been verified in Resolve on every platform; see [Release process](docs/releasing.md).

Preview artifacts are **not code-signed or notarized**. Verify the published `SHA256SUMS` file before running an artifact.

## Languages

On the first launch, **Auto (system)** chooses Russian for a Russian system UI language and English for every other language. Existing settings created by the former Russian-only version remain Russian after migration.

The language can be changed under **Advanced -> Style actions -> Language**. Close and reopen Track Visualizer after changing it; theme and style values are preserved. The installer also accepts `--language auto`, `--language en`, or `--language ru`.

## Install And Run

The currently verified installation flow uses `TrackVisualizerSetup-0.1.0-windows-x64.exe`. It installs the engine under `%LOCALAPPDATA%\DavinciTrackVisualizer\` and the Resolve menu script under:

```text
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Track Visualizer.lua
```

Restart Resolve, then open:

```text
Workspace -> Scripts -> Utility -> Track Visualizer
```

Unsigned preview installers are also built for:

| Target | Artifact | Application data |
| --- | --- | --- |
| Windows x64 | `.exe` and `.zip` | `%LOCALAPPDATA%\DavinciTrackVisualizer` |
| Linux x64 | executable in `.tar.gz` | `$XDG_DATA_HOME/DavinciTrackVisualizer` or `~/.local/share/DavinciTrackVisualizer` |
| macOS arm64 | executable in `.tar.gz` | `~/Library/Application Support/DavinciTrackVisualizer` |
| macOS Intel | executable in `.tar.gz` | `~/Library/Application Support/DavinciTrackVisualizer` |

macOS artifacts are not notarized. Linux requires glibc 2.28 or later. These packages receive native package smoke tests, but Resolve integration has currently been verified only on Windows x64.

Basic workflow:

1. Put music clips on audio tracks such as `A1`, `A2`, and `A3`.
2. Open Track Visualizer and choose the audio tracks and destination video track.
3. Select a skin and palette.
4. Choose **Create / update visualizers**.

The default live mode creates static RGBA cards and lightweight Fusion nodes for time and progress. If a live carrier cannot be created, the affected clip can fall back to a rendered alpha MOV.

## Development

Python 3.12 is used in CI.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Parse the Resolve Lua script without executing it:

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; from luaparser import ast; ast.parse(Path(r'resolve_scripts/Track Visualizer.lua').read_text(encoding='utf-8'))"
```

Native release builds require a matching, redistributable `ffmpeg` and `ffprobe` pair on `PATH`:

```powershell
.\.venv\Scripts\python scripts\build_release.py
```

GitHub release builds do not trust runner-provided FFmpeg binaries. They build a minimal pinned FFmpeg 9.0.1 from its verified official source archive. Four native targets run in parallel; normal pull requests use one small Linux CI job and do not compile FFmpeg or run PyInstaller.

## Project Policy

- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Release process](docs/releasing.md)
- [Compatibility](docs/compatibility.md)

Copyright (C) 2026 denprog5. Licensed under the [GNU General Public License, version 3 or later](LICENSE), SPDX identifier `GPL-3.0-or-later`.

DaVinci Resolve is a trademark of Blackmagic Design Pty Ltd. This project is independent and is not affiliated with or endorsed by Blackmagic Design.
