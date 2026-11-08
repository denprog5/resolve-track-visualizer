"""Signed self-update for installed Windows builds.

The release workflow publishes ``update.json`` next to the installer on the latest GitHub
Release. Its payload names the newest version and the installer's size and SHA-256, and it is
signed with an Ed25519 key that only the release workflow holds. The engine accepts an update only
when the signature verifies against :data:`PUBLIC_KEY_HEX`, the payload names this product and
platform, the version is newer than the installed one, and the downloaded installer matches the
signed size and digest. Running the installer is left to the Resolve panel.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import __version__, ed25519

PRODUCT = "DavinciTrackVisualizer"
PLATFORM = "windows-x64"
UPDATE_SCHEMA = "tviz.update.v1"
REPOSITORY = "denprog5/resolve-track-visualizer"
UPDATE_URL = f"https://github.com/{REPOSITORY}/releases/latest/download/update.json"
PUBLIC_KEY_HEX = "d25c316c18bff9e37bcec300d6cd341d0a56aada2c812d78dcad91941a7c5b55"
INSTALL_MANIFEST_SCHEMA = "davinci-track-visualizer.release.v1"
ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
INSTALLER_PATH_PREFIX = f"/{REPOSITORY}/releases/download/"
INSTALLER_NAME = re.compile(r"TrackVisualizerSetup-[0-9A-Za-z.+-]{1,40}-windows-x64\.exe")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 256 * 1024 * 1024
UPDATES_DIR = "updates"
TIMEOUT_SECONDS = 30

_SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    installer_name: str
    installer_url: str
    installer_size: int
    installer_sha256: str
    notes_url: str


def parse_version(value: str) -> tuple[tuple[int, int, int], tuple[tuple[int, int | str], ...] | None]:
    match = _SEMVER.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is None:
        raise UpdateError(f"Not a semantic version: {value!r}")
    core = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    prerelease = None
    if match.group(4):
        prerelease = tuple((0, int(part)) if part.isdigit() else (1, part) for part in match.group(4).split("."))
    return core, prerelease


def is_newer(candidate: str, current: str) -> bool:
    new_core, new_pre = parse_version(candidate)
    old_core, old_pre = parse_version(current)
    if new_core != old_core:
        return new_core > old_core
    if new_pre == old_pre:
        return False
    if new_pre is None:
        return True
    if old_pre is None:
        return False
    return new_pre > old_pre


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_manifest(payload: dict[str, Any], secret: bytes) -> dict[str, Any]:
    return {"payload": payload, "signature": ed25519.sign(secret, canonical_payload(payload)).hex()}


def _check_url(url: object, *, installer: bool = False) -> str:
    if not isinstance(url, str):
        raise UpdateError("Update URL must be a string")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.port:
        raise UpdateError(f"Update URL is not an allowed HTTPS GitHub address: {url}")
    if installer and (parsed.hostname != "github.com" or not parsed.path.startswith(INSTALLER_PATH_PREFIX)):
        raise UpdateError(f"Installer URL is not a release asset of {REPOSITORY}: {url}")
    return url


def verify_manifest(document: object, public_key_hex: str = PUBLIC_KEY_HEX) -> UpdateInfo:
    if not isinstance(document, dict):
        raise UpdateError("Update manifest must be a JSON object")
    payload, signature = document.get("payload"), document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str) or re.fullmatch(r"[0-9a-f]{128}", signature) is None:
        raise UpdateError("Update manifest has no payload or signature")
    if not ed25519.verify(bytes.fromhex(public_key_hex), canonical_payload(payload), bytes.fromhex(signature)):
        raise UpdateError("Update manifest signature is invalid")
    if payload.get("schema") != UPDATE_SCHEMA or payload.get("product") != PRODUCT or payload.get("platform") != PLATFORM:
        raise UpdateError("Update manifest is for another product, schema or platform")
    version = payload.get("version")
    parse_version(version)  # type: ignore[arg-type]
    installer = payload.get("installer")
    if not isinstance(installer, dict):
        raise UpdateError("Update manifest has no installer")
    name, url, size, digest = (installer.get(key) for key in ("name", "url", "size", "sha256"))
    if not isinstance(name, str) or INSTALLER_NAME.fullmatch(name) is None:
        raise UpdateError(f"Unexpected installer name: {name!r}")
    _check_url(url, installer=True)
    if not isinstance(url, str) or urllib.parse.unquote(urllib.parse.urlsplit(url).path).rsplit("/", 1)[-1] != name:
        raise UpdateError("Installer URL does not end with the installer name")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise UpdateError("Installer size is missing or too large")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise UpdateError("Installer SHA-256 is missing")
    notes_url = payload.get("notes_url")
    if not isinstance(notes_url, str) or not notes_url.startswith(f"https://github.com/{REPOSITORY}/"):
        notes_url = f"https://github.com/{REPOSITORY}/releases"
    return UpdateInfo(str(version), name, url, size, digest, notes_url)


def installed_version(install_root: Path) -> str | None:
    """Version of the installer-managed copy, or None for dev installs and unknown layouts."""
    try:
        data = json.loads((install_root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != INSTALL_MANIFEST_SCHEMA or data.get("product") != PRODUCT:
        return None
    version = data.get("version")
    try:
        parse_version(version)  # type: ignore[arg-type]
    except UpdateError:
        return None
    return str(version)


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


Opener = Callable[[str], Any]


def _default_open(url: str):
    opener = urllib.request.build_opener(_HttpsOnlyRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": f"TrackVisualizer/{__version__}", "Accept": "application/octet-stream"})
    return opener.open(request, timeout=TIMEOUT_SECONDS)


def _read_limited(stream, limit: int) -> bytes:
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Update manifest is too large")
    return data


def fetch_manifest(url: str = UPDATE_URL, opener: Opener = _default_open, source_dir: Path | None = None) -> object:
    if source_dir is not None:
        data = (source_dir / "update.json").read_bytes()[: MAX_MANIFEST_BYTES + 1]
    else:
        _check_url(url)
        try:
            with opener(url) as response:
                data = _read_limited(response, MAX_MANIFEST_BYTES)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise UpdateError(f"Update server answered HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise UpdateError(f"Update server is unreachable: {exc}") from exc
    if len(data) > MAX_MANIFEST_BYTES:
        raise UpdateError("Update manifest is too large")
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as exc:
        raise UpdateError("Update manifest is not valid JSON") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chunks(stream, size: int) -> Iterable[bytes]:
    while True:
        chunk = stream.read(size)
        if not chunk:
            return
        yield chunk


def _remove_downloads(updates_dir: Path, keep: str | None = None) -> None:
    """Delete installers left by earlier updates; one that is still running stays until next time."""
    if not updates_dir.is_dir():
        return
    for stale in updates_dir.iterdir():
        if stale.is_file() and stale.name != keep:
            try:
                stale.unlink()
            except OSError:
                pass


def download_installer(
    info: UpdateInfo,
    updates_dir: Path,
    opener: Opener = _default_open,
    source_dir: Path | None = None,
    progress: Callable[[int], None] | None = None,
) -> Path:
    updates_dir.mkdir(parents=True, exist_ok=True)
    target = updates_dir / info.installer_name
    _remove_downloads(updates_dir, keep=target.name)
    if target.is_file() and target.stat().st_size == info.installer_size and _sha256(target) == info.installer_sha256:
        return target
    partial = updates_dir / f"{info.installer_name}.part"
    digest = hashlib.sha256()
    written = 0
    last_percent = -1
    try:
        stream_context = (source_dir / info.installer_name).open("rb") if source_dir is not None else opener(info.installer_url)
        with stream_context as stream, partial.open("wb") as output:
            for chunk in _chunks(stream, 256 * 1024):
                written += len(chunk)
                if written > info.installer_size:
                    raise UpdateError("Downloaded installer is larger than the signed size")
                digest.update(chunk)
                output.write(chunk)
                percent = written * 100 // info.installer_size
                if progress and percent != last_percent:
                    last_percent = percent
                    progress(percent)
        if written != info.installer_size or digest.hexdigest() != info.installer_sha256:
            raise UpdateError("Downloaded installer does not match the signed size and SHA-256")
        os.replace(partial, target)
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Installer download failed: {exc}") from exc
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def check_for_update(
    install_root: Path,
    *,
    download: bool,
    current: str | None = None,
    url: str = UPDATE_URL,
    opener: Opener = _default_open,
    source_dir: Path | None = None,
    public_key_hex: str = PUBLIC_KEY_HEX,
    progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    current = current or installed_version(install_root)
    if current is None:
        return {"status": "not_installed"}
    document = fetch_manifest(url, opener, source_dir)
    if document is None:
        return {"status": "up_to_date", "current": current}
    info = verify_manifest(document, public_key_hex)
    result: dict[str, Any] = {"current": current, "latest": info.version, "notes_url": info.notes_url}
    if not is_newer(info.version, current):
        _remove_downloads(install_root / UPDATES_DIR)
        result["status"] = "up_to_date"
        return result
    if not download:
        result["status"] = "available"
        return result
    installer = download_installer(info, install_root / UPDATES_DIR, opener, source_dir, progress)
    result.update(status="ready", installer=str(installer))
    return result
