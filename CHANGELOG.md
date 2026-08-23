# Changelog

All notable changes are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning for release tags.

## [0.1.0] - Unreleased

### Added

- Preview implementation of timeline track cards with Classic, Minimal, and Portrait Glass skins.
- Live Fusion time/progress rendering with per-clip legacy alpha MOV fallback.
- Automatic Russian/English UI selection on first launch and a persisted language selector.
- Immutable, generation-scoped helper timelines split into bounded shards.
- Native preview packaging for Windows x64, Linux x64, macOS arm64, and macOS Intel.
- Reproducible minimal FFmpeg source builds with checksums, SBOMs, and release provenance.

### Fixed

- Repeated cards and first-track MOV fallback after repeated long playlist updates.
- Player size drift between timeline resolutions and live/legacy render paths.

[0.1.0]: https://github.com/denprog5/resolve-track-visualizer/releases/tag/v0.1.0
