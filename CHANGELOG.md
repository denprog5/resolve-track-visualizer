# Changelog

All notable changes are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning for release tags.

## [0.1.0] - Unreleased

### Added

- Preview implementation of timeline track cards with Classic, Minimal, and Portrait Glass skins.
- Live Fusion time/progress rendering with per-clip legacy alpha MOV fallback.
- Automatic Russian/English UI selection on first launch and a persisted language selector.
- Immutable, generation-scoped helper timelines split into bounded shards.
- Private Windows x64 release-candidate packaging and a separate unpublished Linux x64 canary.
- Reproducible minimal FFmpeg source builds with checksums and SBOMs.
- Localized non-destructive uninstall support and atomic runtime upgrades.
- Consistent Windows product and version metadata for first-party executables.

### Fixed

- Repeated cards and first-track MOV fallback after repeated long playlist updates.
- Player size drift between timeline resolutions and live/legacy render paths.
- Installer preservation of nested dependency license files.
- PowerShell color-picker launch no longer overrides the configured execution policy.
