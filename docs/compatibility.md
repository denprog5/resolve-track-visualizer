# Compatibility

Resolve Track Visualizer relies on the Resolve scripting API, UIManager, Media Pool timeline insertion, and Fusion compositions. Packaging success alone cannot certify those host APIs.

| Environment | Status | Notes |
| --- | --- | --- |
| DaVinci Resolve Studio 20.2.1, Windows x64 | Verified | UI, 49-track production probe, helper sharding, three skins, project save/reload, and installed runtime tested. |
| DaVinci Resolve Free 20/21 | Not supported by the current UI | Blackmagic restricts the UIManager interface used by this plugin to Resolve Studio. Free support requires a separate UI architecture. |
| DaVinci Resolve 20 versions older than 20.2.1 | Not supported yet | No compatibility claim until host probes pass on the exact version. |
| DaVinci Resolve 21 | Testing deferred | Resolve 21 validation is outside the current release scope; no compatibility claim is made. |
| DaVinci Resolve 19 and older | Not supported | No test coverage and no compatibility promise. |
| Linux Resolve hosts | Not verified | A manual unpublished Linux x64 packaging canary exists, but Resolve integration testing is deferred. |
| macOS Resolve hosts | Unsupported and unbuilt | macOS is outside the current platform and release scope; no native workflow or artifact exists. |

Only DaVinci Resolve Studio 20.2.1 on Windows x64 is currently verified. A successful unit test, Lua parse, or PyInstaller build does not change this matrix.

For a new supported host, run the UI localization probe in English and Russian, the live Fusion host probe, and the 49-track production/reload probe before updating this document.
