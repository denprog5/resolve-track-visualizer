# Compatibility

Resolve Track Visualizer relies on the Resolve scripting API, UIManager, Media Pool timeline insertion, and Fusion compositions. Packaging success alone cannot certify those host APIs.

| Environment | Status | Notes |
| --- | --- | --- |
| DaVinci Resolve Studio 20.2.1, Windows x64 | Verified | UI, 49-track production probe, helper sharding, three skins, project save/reload, and installed runtime tested. |
| DaVinci Resolve Free 20.2.1 | Not yet verified | The menu-script architecture is intended to avoid Workflow Integration requirements, but no release certification has been run. |
| DaVinci Resolve 20 versions older than 20.2.1 | Not supported yet | No compatibility claim until host probes pass on the exact version. |
| DaVinci Resolve 21 | Not yet verified | Must pass UI and production probes before it is added to the supported matrix. |
| DaVinci Resolve 19 and older | Not supported | No test coverage and no compatibility promise. |
| macOS and Linux Resolve hosts | Packaging preview | Native artifacts are built and package-smoke-tested, but Resolve integration still needs manual host certification. |

Both Resolve Studio and Free status must be reported separately. A successful unit test, Lua parse, or PyInstaller build does not change this matrix.

For a new supported host, run the UI localization probe in English and Russian, the live Fusion host probe, and the 49-track production/reload probe before updating this document.
