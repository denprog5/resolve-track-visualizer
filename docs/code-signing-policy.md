# Code Signing Policy

Resolve Track Visualizer applies for free code signing for open-source projects through the [SignPath Foundation](https://signpath.org). Until a certificate is issued, Windows executables are published unsigned and Windows SmartScreen may warn on first launch.

Once approved: free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

## What Is Signed

Only first-party Windows executables built from this repository by the `Windows release` GitHub Actions workflow:

- `TrackVisualizerSetup-<version>-windows-x64.exe` (installer)
- `TrackVisualizerEngine.exe` and `TrackVisualizerRunner.exe` (bundled inside the installer and the portable archive)

Third-party binaries are built from verified upstream sources (FFmpeg, CPython) and are never signed with the project certificate as if they were project code.

## Build And Release Integrity

- Every release is built on GitHub-hosted runners from a commit on `main`, by the manually started `.github/workflows/release.yml`. The pipeline is defined in this repository; see [Release process](releasing.md).
- Build inputs are pinned: Actions by commit SHA, Python packages by hash in `requirements-release.txt`, FFmpeg and CPython sources by SHA-256.
- Each release attaches an SPDX SBOM, `SHA256SUMS`, and the corresponding source archives of bundled third-party components.
- Automatic updates are accepted only with a valid Ed25519 signature from the project's update key, independent of Authenticode.

## Team Roles

| Role | Members |
| --- | --- |
| Committers and reviewers | [denprog5](https://github.com/denprog5) |
| Approvers (approve each signing request) | [denprog5](https://github.com/denprog5) |

All maintainers with signing roles use multi-factor authentication for GitHub and SignPath.

## Privacy

This program does not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it, with one exception: **automatic updates**. When the Track Visualizer panel opens (at most every six hours) or the user selects **Check for updates**, it requests the latest release manifest and, when a newer version exists, its installer from `github.com` and GitHub's release-asset hosts. No user data, project data, or identifier other than what any HTTPS request to GitHub carries is sent. Automatic updates can be turned off in **Service → Updates**. GitHub's privacy statement applies to these requests.

## Applying (Maintainer Checklist)

1. Make sure the repository is public, has an OSI-approved license (GPL-3.0-or-later), and has at least one published release.
2. Apply at <https://signpath.org/apply> with the repository URL and this policy.
3. After approval, add the SignPath GitHub Actions integration to the `publish` job so the installer is signed before `update.json` is generated (the manifest hashes the signed installer), and update `tests/test_release_workflow.py`.
