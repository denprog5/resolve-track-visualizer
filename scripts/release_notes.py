"""Write GitHub Release notes for one version from CHANGELOG.md.

The release fails when CHANGELOG.md has no section for the version, so every published release
documents its user-visible changes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FOOTER = """
---

**Install:** download `TrackVisualizerSetup-{version}-windows-x64.exe` and run it, then restart DaVinci Resolve and open Workspace → Scripts → Utility → Track Visualizer.

**Updates:** installed copies update themselves. The panel checks for a new release when it opens (at most every six hours), verifies the signed `update.json` and the installer's SHA-256, and installs while it is idle. Turn this off in Service → Updates.

`SHA256SUMS` lists checksums for every file; the `*.tar.*` files are the corresponding sources of the bundled third-party components.
"""


def section(changelog: str, version: str) -> str:
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None or not match.group("body").strip():
        raise SystemExit(f"CHANGELOG.md has no entries for version {version}")
    return match.group("body").strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    body = section(args.changelog.read_text(encoding="utf-8"), args.version)
    args.out.write_text(body + FOOTER.format(version=args.version), encoding="utf-8")
    print(f"Release notes for {args.version}: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
