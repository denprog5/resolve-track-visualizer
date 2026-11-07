# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Resolve Track Visualizer: a DaVinci Resolve Studio menu script (Lua) that builds track cards for music timelines, backed by a bundled Python engine. Version 0.1.0 preview. The only verified host is **Resolve Studio 20.2.1 on Windows x64**. Keep compatibility claims limited to what was actually tested (see `docs/compatibility.md`). Licensed GPL-3.0-or-later. New bundled dependencies need a compatible license and an entry in `THIRD_PARTY_NOTICES.md`. Update `CHANGELOG.md` (Keep a Changelog format) for user-visible changes.

## Commands

The local venv is `.venv`. CI uses Python 3.12.13 on Linux and 3.12.10 on Windows.

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -v        # full suite (same as CI)
.\.venv\Scripts\python -m unittest tests.test_skins -v          # one module
.\.venv\Scripts\python -m unittest tests.test_lua_i18n.LuaLocalizationTests.test_catalogs_have_matching_stable_keys
```

Parse the Lua script (the CI check; it does not execute it):

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; from luaparser import ast; ast.parse(Path(r'resolve_scripts/Track Visualizer.lua').read_text(encoding='utf-8'))"
```

Run the engine directly: `python -m davinci_track_visualizer <prepare|scan|preview-style|catalog> ...` (see `build_parser()` in `davinci_track_visualizer/cli.py`).

Dev install into Resolve: `python scripts/install_resolve_script.py [--target DIR]` copies the Lua script into the Resolve Utility scripts folder and substitutes its `__INSTALL_ROOT__` / `__ENGINE_EXECUTABLE__` / `__RUNNER_EXECUTABLE__` / `__FFMPEG_EXECUTABLE__` / `__FFPROBE_EXECUTABLE__` placeholders. It points them at `dist/TrackVisualizerEngine[.exe]`, `dist/TrackVisualizerRunner[.exe]` and an ffmpeg/ffprobe in the repo root or on PATH.

The `SKIN_CATALOG` table in the Lua script is generated from `davinci_track_visualizer/skins.py`: run `python scripts/sync_lua_catalog.py` after changing skins or palettes (`--check` verifies; `tests/test_lua_catalog.py` enforces it).

Unit tests and Lua parsing do not validate behavior inside Resolve. Document manual Resolve testing separately.

## Architecture

There are three processes, linked by files on disk rather than pipes:

1. **`resolve_scripts/Track Visualizer.lua`** (~5k lines, single file) runs inside Resolve under LuaJIT. It owns the UIManager UI (tabs Players/Look/Library/Service, widget IDs `PageCreate`/`PageStyle`/`PagePresets`/`PageLog`), settings (`<install_root>/settings.json`, including user presets and palettes), timeline inspection and mix overlap resolution (`resolve_overlap_jobs`, `SWITCH_MODES`), writing the jobs JSON, and placement. The pipeline is a `ui:Timer`-driven state machine (scan → engine → place) so the UI never blocks and can be cancelled. UIManager delivers change events for programmatic updates after any suppress flag is cleared, so every change handler must be idempotent (compare with the current value before acting) or it can loop forever. Windows-specific behavior goes through LuaJIT FFI wide-char APIs, which are centralized in the script and enforced by `tests/test_lua_portability.py`.
2. **Runner** (`scripts/runner_entry.py` → `TrackVisualizerRunner`) is a file-queue executor. Lua writes `runner_launch_<stem>.json` into `<install_root>/tmp/` with `{command, env, cwd, stdout_path, done_path, mode}`, launches the runner, polls asynchronously for the claim, tails `stdout_path` for progress lines, and then reads the `done_path` completion JSON (`{returncode, error}`, written atomically). The runner exists so that Resolve never spawns the engine with a visible console. On Windows Lua only uses the native launch; on POSIX it launches the runner detached.
3. **Engine** (`scripts/engine_entry.py` → `davinci_track_visualizer.cli.main` → `TrackVisualizerEngine`) reads tags and artwork (`metadata.py`, mutagen), probes audio (`audio.py`, ffprobe), analyses waveforms (`waveform.py`), draws player layers with Pillow (`render.py`, skins in `skins.py`), writes one Fusion `.comp` per track (`fusion_comp.py`) and a transparent carrier `.mov` at timeline resolution (`carrier.py`).

Placement: `prepare` writes card/played/knob PNGs, comps (in an ASCII-only staging dir, because `ImportFusionComp` fails on non-ASCII paths) and a manifest (`tviz.manifest` v4, with `failed` entries for tracks that could not be read). Lua imports the carrier once into the `Track Visualizer` Media Pool bin, appends ranges of it to the target video track, calls `TimelineItem:ImportFusionComp`, and names items `TVIZ__<id>`. Time and progress are Fusion expressions using the clip's source offset, so trims on either side stay correct. There are no helper timelines and no MOV renderer; do not reintroduce `comp:Lock()`, `comp:Paste()` or `comp:AddTool("Loader")` (see `docs/redesign-2026-11.md` for why).

Skins (`classic`, `minimal`, `portrait_glass`, `compact`, `wave`) are defined in `skins.py` (`SUPPORTED_SKINS`, `default_design`, `PALETTES`, `DEFAULT_PALETTES`) and drawn in `render.py`. Each skin has independent settings and a default palette.

`platform_paths.py` defines install roots and the Resolve scripts dir per OS. The overrides are `DAVINCI_TRACK_VISUALIZER_HOME` and `DAVINCI_TRACK_VISUALIZER_RESOLVE_SCRIPTS`. The Lua script reimplements the same logic, and `test_lua_portability.py` checks that the two stay in agreement.

## Localization

All UI strings live in the `I18N` table in the Lua script, in `en` and `ru` catalogs, and are accessed via `tr("key", {placeholders})`. Tests require:
- identical key sets in both catalogs;
- every `tr("...")` key exists in `en`;
- no raw Cyrillic text outside the `ru` catalog.

The installer (`installer/track_visualizer_installer.py`) has its own localization, covered by `tests/test_installer_localization.py`.

## Installer and release

- `installer/track_visualizer_installer.py` becomes `TrackVisualizerSetup-<ver>-windows-x64.exe`. Flags: `--language auto|en|ru`, `--install-root`, `--resolve-script-dir`, `--uninstall`, `--dry-run`, `--no-pause`. Uninstall is deliberately non-destructive: it removes only managed runtime files and the menu script, and keeps settings, logs, tasks and outputs. Upgrades are atomic.
- `scripts/build_release.py` drives the PyInstaller `--onefile` builds, staging, smoke tests, deterministic archives, and the SBOM (`scripts/generate_release_sbom.py`). It enforces an exact Python version (3.12.10 on Windows, 3.12.13 on Linux), `PYTHONNOUSERSITE=1`, and explicitly verified FFmpeg inputs (`--ffmpeg-*` flags or `TVIZ_*` env vars). Finding ffmpeg on PATH alone is rejected. Release deps are hash-pinned in `requirements-release.txt`.
- GitHub Actions: `ci.yml` (tests and Lua parsing on Windows and Linux), `release.yml` (manual Windows x64 release candidate), and `linux-canary.yml` (manual, unpublished Linux canary). Both manual workflows call the reusable `native-build.yml`, which builds a pinned FFmpeg from source (`packaging/scripts/build_ffmpeg.sh`) and, on Linux, CPython (`build_python.sh`).
- Artifacts are unsigned, kept for one day, and gated on a live check that the repo is private. No workflow creates tags or GitHub Releases. Keep it that way unless a signing/publication process is approved. See `docs/releasing.md`.
- **`tests/test_release_workflow.py` and `tests/test_release_staging.py` assert on the exact contents of the workflow YAML, the build scripts and the release lock.** Changing any of those usually requires updating these tests.

## Repo hygiene

Do not commit generated output (`build/`, `dist/`, `release/`, `outputs/`, `ffbuild/`), media, installers/binaries, or diagnostic logs; `.gitignore` covers these. `PLAN.md`, `s1-3.png` and `.agents/` are local-only.
