# Compatibility

Resolve Track Visualizer relies on the Resolve scripting API, UIManager, Media Pool timeline insertion, and Fusion compositions. Packaging success alone cannot certify those host APIs.

| Environment | Status | Notes |
| --- | --- | --- |
| DaVinci Resolve Studio 20.2.1, Windows x64 | Verified | Redesigned panel in Russian and English, five skins, palette and preset workflow, 48-clip overlapping mix placement, project save/reload, panel relaunch. Tested with a development install; the packaged installer has not been re-run since the redesign. |
| DaVinci Resolve Free 20/21 | Not supported by the current UI | Blackmagic restricts the UIManager interface used by this plugin to Resolve Studio. Free support requires a separate UI architecture. |
| DaVinci Resolve 20 versions older than 20.2.1 | Not supported yet | No compatibility claim until host probes pass on the exact version. |
| DaVinci Resolve 21 | Testing deferred | Resolve 21 validation is outside the current release scope; no compatibility claim is made. |
| DaVinci Resolve 19 and older | Not supported | No test coverage and no compatibility promise. |
| Linux Resolve hosts | Not verified | A manual unpublished Linux x64 packaging canary exists, but Resolve integration testing is deferred. |
| macOS Resolve hosts | Unsupported and unbuilt | macOS is outside the current platform and release scope; no native workflow or artifact exists. |

Only DaVinci Resolve Studio 20.2.1 on Windows x64 is currently verified. A successful unit test, Lua parse, or PyInstaller build does not change this matrix.

For a new supported host, create players in a disposable project on a short timeline and on a long overlapping mix (48+ clips across two or more audio tracks), check exported stills against the expected time readouts, save and reload the project, and check the panel in English and Russian before updating this document.
