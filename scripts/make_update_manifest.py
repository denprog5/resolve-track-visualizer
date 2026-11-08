"""Write the signed update.json for a Windows release.

The Ed25519 secret key is read as 64 hex characters from an environment variable (by default
TVIZ_UPDATE_SIGNING_KEY). The script refuses to write a manifest that the shipped public key would
not accept, so a wrong or rotated secret fails the release instead of breaking self-update.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from davinci_track_visualizer import __version__  # noqa: E402
from davinci_track_visualizer.updater import (  # noqa: E402
    PLATFORM,
    PRODUCT,
    REPOSITORY,
    UPDATE_SCHEMA,
    sign_manifest,
    verify_manifest,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_payload(installer: Path, version: str) -> dict:
    tag = f"v{version}"
    return {
        "schema": UPDATE_SCHEMA,
        "product": PRODUCT,
        "platform": PLATFORM,
        "version": version,
        "notes_url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
        "installer": {
            "name": installer.name,
            "url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{installer.name}",
            "size": installer.stat().st_size,
            "sha256": _sha256(installer),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--key-env", default="TVIZ_UPDATE_SIGNING_KEY")
    args = parser.parse_args(argv)

    if args.version != __version__:
        parser.error(f"--version {args.version} does not match the package version {__version__}")
    secret_hex = os.environ.get(args.key_env, "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", secret_hex) is None:
        parser.error(f"{args.key_env} must hold a 32-byte Ed25519 secret key as 64 hex characters")
    if not args.installer.is_file():
        parser.error(f"Installer not found: {args.installer}")

    document = sign_manifest(build_payload(args.installer, args.version), bytes.fromhex(secret_hex))
    info = verify_manifest(document)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"update.json for {info.version}: {info.installer_name} {info.installer_size} bytes sha256 {info.installer_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
