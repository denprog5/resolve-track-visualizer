from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire and verify a pinned official dependency source archive")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--required-file", required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--extract-to", type=Path)
    args = parser.parse_args()

    archive = args.archive.resolve()
    if args.download:
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_name(archive.name + ".part")
        temporary.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(args.url, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            os.replace(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)

    if not archive.is_file():
        raise FileNotFoundError(archive)
    actual_digest = sha256(archive)
    if actual_digest != args.sha256:
        raise RuntimeError(f"Dependency source SHA-256 mismatch: expected {args.sha256}, found {actual_digest}")
    print(f"Verified {archive.name}: {actual_digest}")

    if args.extract_to is not None:
        extraction_root = args.extract_to.resolve()
        source_dir = extraction_root / args.archive_root
        if source_dir.exists():
            shutil.rmtree(source_dir)
        extraction_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:*") as source:
            names = {Path(member.name).parts[0] for member in source.getmembers() if Path(member.name).parts}
            if names != {args.archive_root}:
                raise RuntimeError(f"Unexpected dependency archive roots: {sorted(names)}")
            source.extractall(extraction_root, filter="data")
        if not (source_dir / args.required_file).is_file():
            raise RuntimeError(f"Dependency source archive did not produce {source_dir / args.required_file}")
        print(f"Extracted {source_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
