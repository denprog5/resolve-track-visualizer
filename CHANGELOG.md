# Changelog

All notable changes are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning for release tags.

## [0.1.0] - Unreleased

### Added

- Music player overlays for timeline audio clips with Classic, Minimal, Portrait Glass, Compact and Wave skins.
- Fourteen built-in palettes, including Lavender (the Portrait Glass default), plus user palettes that work with every skin.
- Player preset library: save, apply, rename, delete, export and import complete styles (`.tviz-preset.json`).
- DJ-mix handling: overlapping clips across audio tracks form one row of players with a selectable switch point (middle of the crossfade, next track start, current track end); clips that play entirely inside another track are skipped.
- Time and progress follow trims on either side; progress can show the position in the whole track or in the clip.
- Non-blocking panel: skin, palette and preset are chosen on the main Players page next to a large preview and apply immediately; Look holds fine-tuning with color swatches, Library holds presets and palettes, Service holds the log and language. Live progress, Cancel while running and two-click player removal.
- Cleanup of helper timelines left by earlier preview builds.
- Automatic Russian/English UI selection on first launch and a persisted language selector.
- Private Windows x64 release-candidate packaging and a separate unpublished Linux x64 canary.
- Reproducible minimal FFmpeg source builds with checksums and SBOMs.
- Localized non-destructive uninstall support and atomic runtime upgrades.
- Consistent Windows product and version metadata for first-party executables.

### Changed

- Players are placed from one plugin-owned transparent carrier clip with one imported Fusion composition per clip; time and progress are expressions instead of per-second keyframes.
- Waveforms use streamed decoding with percentile normalization, perceptual scaling and smoothing.
- Multiple artists separated by `/` are shown as a comma-separated list.
- A track the engine cannot read is reported in the log instead of failing the whole run.

### Security

- Fusion comps for users with non-ASCII profile paths are staged in the 8.3 short form of their own folder and never in a shared folder such as ProgramData.

### Removed

- The legacy alpha MOV renderer and its automatic fallback.
- Helper and nested timelines for player placement.

### Fixed

- Resolve could close while players were being created on long timelines.
- The panel froze for the whole run and could not be cancelled.
- Reopening the panel after closing it could fail with a stray UI event error.
- Existing players were deleted before a conflict on the target video track was detected.
- Player size drift between timeline resolutions.
- Installer preservation of nested dependency license files.
- PowerShell color-picker launch no longer overrides the configured execution policy.
