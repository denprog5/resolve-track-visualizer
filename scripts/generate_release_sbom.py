from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output, length=1024 * 1024)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def require_digest(path: Path, expected: str, label: str) -> None:
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: expected {expected}, found {actual}")


def verify_checksum_manifest(
    manifest: Path,
    archive_name: str,
    archive_sha256: str,
) -> None:
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line.strip())
        if match:
            entries[match.group(2)] = match.group(1)
    recorded = entries.get(archive_name)
    if recorded != archive_sha256:
        raise RuntimeError(
            f"Official checksum manifest does not record {archive_name} as {archive_sha256}"
        )


def extract_member(archive: Path, member_name: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        if zipfile.is_zipfile(archive):
            with (
                zipfile.ZipFile(archive) as source,
                source.open(member_name) as member,
                temporary.open("wb") as target,
            ):
                shutil.copyfileobj(member, target, length=1024 * 1024)
        else:
            with tarfile.open(archive, "r:*") as source:
                member_info = source.getmember(member_name)
                if not member_info.isfile():
                    raise RuntimeError(
                        f"Release tool archive member is not a file: {member_name}"
                    )
                member = source.extractfile(member_info)
                if member is None:
                    raise RuntimeError(f"Could not extract release tool archive member: {member_name}")
                with member, temporary.open("wb") as target:
                    shutil.copyfileobj(member, target, length=1024 * 1024)
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def validate_spdx(path: Path) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Syft did not produce valid SPDX JSON: {path}") from exc
    if not isinstance(document, dict):
        raise RuntimeError("SPDX output must be a JSON object")
    if not re.fullmatch(r"SPDX-\d+\.\d+", str(document.get("spdxVersion", ""))):
        raise RuntimeError("SPDX output is missing a valid spdxVersion")
    if document.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise RuntimeError("SPDX output is missing the document SPDX identifier")
    if not isinstance(document.get("packages"), list):
        raise RuntimeError("SPDX output is missing the packages list")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate SPDX JSON with a checksum-pinned Syft binary"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--checksums-url", required=True)
    parser.add_argument("--checksums-sha256", required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    archive = args.archive.resolve()
    checksums = args.checksums.resolve()
    if args.download:
        download(args.url, archive)
        download(args.checksums_url, checksums)
    if not archive.is_file():
        raise FileNotFoundError(archive)
    if not checksums.is_file():
        raise FileNotFoundError(checksums)
    require_digest(archive, args.sha256, "Syft archive")
    require_digest(checksums, args.checksums_sha256, "Syft checksum manifest")
    verify_checksum_manifest(checksums, archive.name, args.sha256)

    tool = archive.parent / "syft-bin" / Path(args.member).name
    if tool.parent.exists():
        shutil.rmtree(tool.parent)
    extract_member(archive, args.member, tool)
    environment = os.environ.copy()
    environment["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
    version_result = subprocess.run(
        [str(tool), "version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    version_text = f"{version_result.stdout}\n{version_result.stderr}"
    if not re.search(rf"\b{re.escape(args.version)}\b", version_text):
        raise RuntimeError(f"Expected Syft {args.version}, got: {version_text.strip()}")

    scan_root = args.scan.resolve()
    if not scan_root.is_dir():
        raise FileNotFoundError(scan_root)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open("wb") as stdout:
            subprocess.run(
                [str(tool), "scan", f"dir:{scan_root}", "-o", "spdx-json"],
                check=True,
                stdout=stdout,
                env=environment,
            )
        validate_spdx(temporary)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Generated {output} with checksum-verified Syft {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
