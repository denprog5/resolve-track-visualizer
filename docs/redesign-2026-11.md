# Audit and Redesign — November 2026

Reported problem: Resolve sometimes exits (whole application closes) while Track Visualizer
creates the player overlays. No Windows Error Reporting entries or crash dumps for
Resolve.exe were retained on the development machine, so the root cause is inferred from a
code audit, not from a stack trace.

## Audit findings

### Stability (highest risk first)

1. **Per-second Fusion keyframes.** `build_live_fusion_comp` wrote one `StyledText`
   keyframe per second of every track via `SetInput` on an unlocked composition attached to a
   live timeline item (≈3600 calls for a one-hour mix, multiplied by tracks). Every call
   notifies the Edit-page viewer and the undo stack. No `comp:Lock()`/`StartUndo()` was used.
2. **Helper-timeline carrier machinery.** Each run created brand-new helper timelines, imported
   the card PNG, appended it hundreds of times in batches of 256 to cover the track length,
   switched the project's current timeline back and forth, appended the helper timelines into
   the target as nested clips and then attached a Fusion comp to each nested clip. Helper
   timelines and PNG media were never removed, so every run grew the Media Pool.
3. **All Resolve work ran synchronously inside the button handler.** The UIManager callback
   blocked for the entire run (engine process, timeline edits, Fusion edits), polling with
   `bmd.wait` and `win:Repaint()`. There was no cancellation and the UI stayed frozen.
4. **Automatic legacy fallback.** When a live clip failed, the script switched mid-run to
   rendering a full-length alpha MOV per track with ffmpeg — a second, much heavier pipeline with
   its own failure modes.
5. A CPU busy-spin `while os.clock() < target do end` remained as the last-resort wait.

### Maintainability

- A single 5,300-line Lua file mixing Win32 FFI, JSON, settings, UI, Resolve placement and Fusion
  construction.
- Two renderer pipelines (live + legacy) with separate manifests and validation.
- Settings mixed per-skin profiles and palettes without a user-preset concept.

### Engine / analysis

- Waveform bars were plain RMS over equal windows, normalized to the single loudest window.
  One transient flattens the rest of the track; there was no perceptual scaling or smoothing.
- The whole file was decoded into memory before reducing to ~56 numbers.

## Redesign decisions (approved 2026-11-07)

1. **Rewrite placement.** A single plugin-owned transparent carrier clip, generated once per
   frame rate and imported once, is appended directly onto the target timeline with explicit
   `startFrame/endFrame/recordFrame`. No helper or nested timelines and no current-timeline
   switching. Each clip gets one Fusion comp built under `Lock()`: a Loader for the card PNG and
   expression-driven progress and time (no per-second keyframes).
2. **Remove the legacy MOV renderer** entirely, including the automatic fallback.
3. **Non-blocking UI.** The pipeline runs as a `ui:Timer`-driven state machine with progress and
   a Cancel button. Failed placement removes only the clips created in that run.
4. **Visuals.** Keep the existing skins (Classic, Minimal, Portrait Glass), polish them toward
   the reference look and add new ones. Improve waveform analysis (percentile normalization,
   perceptual scaling, smoothing).
5. **User preset library.** Users can save, rename, delete, import and export their own palettes
   and complete player presets (skin + layout + palette + typography) and reuse them later.
6. Host verification in disposable `TVIZ Test …` projects through `fuscript` is approved. The
   user's own projects are never modified by tests.

## Host findings — Resolve Studio 20.2.1.6, Windows, 2026-11-07

Run in the disposable project `TVIZ Test Exp 20261107-154516` through `fuscript`.

| Question | Result |
| --- | --- |
| Can a PNG still be appended longer than the still duration? | No. `AppendToTimeline` with `endFrame` 900/4500/9100 always produced 150 frames (5 s). |
| Does the generated Animation (`rle `) carrier import? | Yes: `Animation`, 30 fps, 108000 frames; 16×16 file 432 KB, 1920×1080 file 521 KB (all samples share one encoded frame). |
| Exact placement of carrier ranges | `startFrame=0,endFrame=N` gives exactly N frames at `recordFrame`, including N=108000. |
| Composition time origin | `RenderStart=0`, `RenderEnd=N-1`: Fusion `time` 0 is the clip's first frame. |
| Composition frame format | Equals the carrier resolution, so the carrier must be generated at timeline resolution. |
| Expressions instead of keyframes | `StyledText` expression `Text(string.format(...time...))` and `Point(...)`/numeric expressions on masks evaluate per frame. |
| Loader with a single PNG | Holds the still for the whole composition range. |
| `comp:Lock()`/`Unlock()` | **Breaks Edit-page output**: the Edit viewer and `ExportCurrentFrameAsStill` stay empty although the Fusion page renders. Not used. |
| `comp:Paste(table)` from an external script | Returns `false`, even for one Background. Not used. |
| `comp:AddTool("Loader")` | Can open a modal *Open File* dialog that blocks the whole scripting API. Not used. |
| `TimelineItem:ImportFusionComp(path)` | Works: one call per clip, correct Edit-page output, render range adapts to clip length; 20 clips in ~1 s. **Chosen.** |
| Generated comp without `MediaIn` | Works. Loader (card PNG) → Merge with `RectangleMask` effect mask (played layer reveal) → Transform with `Center` expression (knob) → TextPlus readouts → `MediaOut1 = Saver { Index = "0" }`. Positions match within 1 px. |
| `ImportFusionComp` with a non-ASCII comp path | **Fails** (returns nil) for UTF-8 and ANSI (cp1251) encodings. Loader `Filename`s inside the comp and `MediaPool:ImportMedia` accept UTF-8 Unicode paths. Comp files are therefore staged in an ASCII-only directory. A later re-test returned a comp for a Cyrillic folder, so the behaviour is not consistent; staging stays. The 8.3 short form of the user's own folder (`GetShortPathNameW`) imports and renders correctly and is preferred. Shared roots (ProgramData, `/tmp`) are used only as fresh private directories, because comps contain expressions Resolve evaluates. |
| TextPlus geometry | `HorizontalLeftCenterRight` −1/0/1 anchors the line left/centre/right at `Center.X`; `VerticalTopCenterBottom` 0 + `VerticalJustificationNew` 3 centres the line on `Center.Y`. `Size × frame width ≈ 1.70 ×` Pillow em size for Segoe UI (regular and bold). |

## UIManager findings (same host)

| Question | Result |
| --- | --- |
| QSS `#ID` selectors in a window `StyleSheet` | Do not match: UIManager `ID`s are not Qt object names. Per-widget `StyleSheet` is used for the primary button, preview and error label. |
| Global QSS `min-height` vs `MinimumSize` | QSS wins, so sizes that must differ per widget are not set globally. |
| UTF-8 block characters (`█`, `░`) in a `Label` | Render garbled; the progress bar is a `Label` with a `qlineargradient` background instead. |
| `TextEdit` log updates | `PlainText` + `MoveCursor` leaves the text looking selected; `Append()` does not. |
| Reopening the panel after closing it | A stale event from the previous window could reach the new dispatcher (`table index is nil` inside `RunLoop`). Fixed by a per-launch timer ID, clearing `On.Timeout` on close, and a bounded guarded `RunLoop` retry. |
| Loader PNGs inside imported comps | Resolve adds them to the *current* Media Pool folder. Placement makes the `Track Visualizer` bin current and restores the user's folder afterwards. |

## Mix handling

DJ mixes usually alternate tracks across two or three audio tracks with overlapping crossfades and
trims on either side. `resolve_overlap_jobs` sorts clips by start and builds one non-overlapping row:

- the switch point is the middle of the overlap (default), the next clip's start, or the current
  clip's end;
- a clip that starts later than its record start because of the switch keeps a correct readout:
  the skipped frames are added to its source start time;
- a clip entirely inside another clip (an overlay or effect layer) gets no player;
- clips starting on the same frame keep the one on the higher audio track.

Time and progress use the clip's source offset (`GetSourceStartTime()`), so a left trim shows the
real position in the track.

## Verification run (2026-11-07)

- 4-clip timeline: players placed in about 10 s; stills match the expected readouts, including a
  left-trimmed clip; re-running replaces the players.
- Three-track mix with an overlay: three players with switches in the crossfade middles; the overlay
  clip was skipped.
- 48 clips alternating A1/A2 with 8 s crossfades and varied trims (21:44 timeline): 48 players
  in under 10 s, no gaps or overlaps on V2, switch points at the crossfade middles, stills match the
  trim arithmetic. After save, switching projects and reloading, all 48 players and their output
  were unchanged.
- `scripts/probe_plugin_ui.lua` passed in Russian and English.
