from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from davinci_track_visualizer import ed25519, updater
from davinci_track_visualizer.updater import (
    UpdateError,
    check_for_update,
    is_newer,
    sign_manifest,
    verify_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = bytes(range(32))
PUBLIC_HEX = ed25519.public_key(SECRET).hex()
INSTALLER_NAME = "TrackVisualizerSetup-0.9.0-windows-x64.exe"
INSTALLER_BYTES = b"MZ fake installer " * 1000


def _payload(**overrides):
    payload = {
        "schema": updater.UPDATE_SCHEMA,
        "product": updater.PRODUCT,
        "platform": updater.PLATFORM,
        "version": "0.9.0",
        "notes_url": f"https://github.com/{updater.REPOSITORY}/releases/tag/v0.9.0",
        "installer": {
            "name": INSTALLER_NAME,
            "url": f"https://github.com/{updater.REPOSITORY}/releases/download/v0.9.0/{INSTALLER_NAME}",
            "size": len(INSTALLER_BYTES),
            "sha256": hashlib.sha256(INSTALLER_BYTES).hexdigest(),
        },
    }
    payload.update(overrides)
    return payload


def _install_root(directory: Path, version: str = "0.1.0") -> Path:
    root = directory / "install"
    root.mkdir()
    manifest = {"schema": updater.INSTALL_MANIFEST_SCHEMA, "product": updater.PRODUCT, "version": version, "files": []}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


class _Response(io.BytesIO):
    pass


def _opener(routes: dict[str, bytes], calls: list[str] | None = None):
    def open_url(url: str):
        if calls is not None:
            calls.append(url)
        return _Response(routes[url])

    return open_url


class Ed25519Tests(unittest.TestCase):
    def test_rfc8032_test_vector_1(self) -> None:
        secret = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        public = ed25519.public_key(secret)
        signature = ed25519.sign(secret, b"")
        self.assertEqual(public.hex(), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        self.assertEqual(
            signature.hex(),
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
        )
        self.assertTrue(ed25519.verify(public, b"", signature))

    def test_tampering_is_rejected(self) -> None:
        signature = ed25519.sign(SECRET, b"payload")
        public = bytes.fromhex(PUBLIC_HEX)
        self.assertFalse(ed25519.verify(public, b"payloaD", signature))
        broken = bytearray(signature)
        broken[5] ^= 1
        self.assertFalse(ed25519.verify(public, b"payload", bytes(broken)))
        self.assertFalse(ed25519.verify(public, b"payload", signature[:63]))

    def test_shipped_public_key_is_a_valid_point(self) -> None:
        self.assertRegex(updater.PUBLIC_KEY_HEX, r"^[0-9a-f]{64}$")
        self.assertIsNotNone(ed25519._decompress(bytes.fromhex(updater.PUBLIC_KEY_HEX)))


class VersionTests(unittest.TestCase):
    def test_semantic_version_order(self) -> None:
        ordered = ["0.1.0", "0.9.0-rc.1", "0.9.0-rc.2", "0.9.0", "0.9.1", "1.0.0-beta", "1.0.0", "1.10.0"]
        for older, newer in zip(ordered, ordered[1:]):
            self.assertTrue(is_newer(newer, older), (newer, older))
            self.assertFalse(is_newer(older, newer), (older, newer))
        self.assertFalse(is_newer("1.0.0", "1.0.0"))
        with self.assertRaises(UpdateError):
            is_newer("v1.0", "1.0.0")


class ManifestTests(unittest.TestCase):
    def test_signed_manifest_round_trips(self) -> None:
        info = verify_manifest(sign_manifest(_payload(), SECRET), PUBLIC_HEX)
        self.assertEqual((info.version, info.installer_name), ("0.9.0", INSTALLER_NAME))

    def test_changed_payload_or_foreign_key_is_rejected(self) -> None:
        document = sign_manifest(_payload(), SECRET)
        document["payload"]["installer"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(UpdateError, "signature"):
            verify_manifest(document, PUBLIC_HEX)
        with self.assertRaisesRegex(UpdateError, "signature"):
            verify_manifest(sign_manifest(_payload(), SECRET), updater.PUBLIC_KEY_HEX if updater.PUBLIC_KEY_HEX != PUBLIC_HEX else "00" * 32)

    def test_signed_but_unsafe_payloads_are_rejected(self) -> None:
        url = f"https://github.com/{updater.REPOSITORY}/releases/download/v0.9.0/{INSTALLER_NAME}"
        bad_installers = [
            {"url": url.replace("https://", "http://")},
            {"url": url.replace("github.com", "example.com")},
            {"url": f"https://github.com/someone/else/releases/download/v0.9.0/{INSTALLER_NAME}"},
            {"url": url.replace(INSTALLER_NAME, "Other.exe")},
            {"name": "evil.exe"},
            {"size": updater.MAX_INSTALLER_BYTES + 1},
            {"sha256": "abc"},
        ]
        for change in bad_installers:
            installer = dict(_payload()["installer"], **change)
            with self.assertRaises(UpdateError, msg=change):
                verify_manifest(sign_manifest(_payload(installer=installer), SECRET), PUBLIC_HEX)
        for change in ({"product": "Other"}, {"platform": "linux-x64"}, {"version": "latest"}, {"schema": "x"}):
            with self.assertRaises(UpdateError, msg=change):
                verify_manifest(sign_manifest(_payload(**change), SECRET), PUBLIC_HEX)


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.document = json.dumps(sign_manifest(_payload(), SECRET)).encode()
        self.routes = {updater.UPDATE_URL: self.document, _payload()["installer"]["url"]: INSTALLER_BYTES}

    def check(self, root: Path, **options):
        return check_for_update(root, opener=_opener(self.routes), public_key_hex=PUBLIC_HEX, **options)

    def test_dev_install_without_manifest_is_never_updated(self) -> None:
        calls: list[str] = []
        result = check_for_update(self.directory, download=True, opener=_opener(self.routes, calls), public_key_hex=PUBLIC_HEX)
        self.assertEqual(result, {"status": "not_installed"})
        self.assertEqual(calls, [])

    def test_newer_release_is_downloaded_and_verified(self) -> None:
        root = _install_root(self.directory)
        self.assertEqual(self.check(root, download=False)["status"], "available")
        result = self.check(root, download=True)
        self.assertEqual((result["status"], result["current"], result["latest"]), ("ready", "0.1.0", "0.9.0"))
        self.assertEqual(Path(result["installer"]).read_bytes(), INSTALLER_BYTES)
        self.assertEqual(sorted(p.name for p in (root / "updates").iterdir()), [INSTALLER_NAME])

    def test_same_or_older_release_is_ignored(self) -> None:
        for version in ("0.9.0", "1.0.0"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as other:
                root = _install_root(Path(other), version)
                (root / "updates").mkdir()
                (root / "updates" / "TrackVisualizerSetup-0.5.0-windows-x64.exe").write_bytes(b"old")
                self.assertEqual(self.check(root, download=True)["status"], "up_to_date")
                self.assertEqual(list((root / "updates").iterdir()), [])

    def test_corrupted_download_is_discarded(self) -> None:
        root = _install_root(self.directory)
        self.routes[_payload()["installer"]["url"]] = INSTALLER_BYTES[:-1] + b"X"
        with self.assertRaisesRegex(UpdateError, "SHA-256"):
            self.check(root, download=True)
        self.assertEqual(list((root / "updates").iterdir()), [])
        self.routes[_payload()["installer"]["url"]] = INSTALLER_BYTES + b"extra"
        with self.assertRaisesRegex(UpdateError, "larger"):
            self.check(root, download=True)

    def test_local_source_still_requires_the_signature(self) -> None:
        root = _install_root(self.directory)
        source = self.directory / "source"
        source.mkdir()
        (source / INSTALLER_NAME).write_bytes(INSTALLER_BYTES)
        (source / "update.json").write_bytes(self.document)
        result = check_for_update(root, download=True, source_dir=source, public_key_hex=PUBLIC_HEX)
        self.assertEqual(result["status"], "ready")
        with self.assertRaisesRegex(UpdateError, "signature"):
            check_for_update(root, download=True, source_dir=source)

    def test_redirects_must_stay_on_https_github(self) -> None:
        handler = updater._HttpsOnlyRedirects()
        with self.assertRaises(UpdateError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://objects.githubusercontent.com/x")
        with self.assertRaises(UpdateError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://example.com/x")


class ReleaseManifestScriptTests(unittest.TestCase):
    def test_script_refuses_a_key_the_shipped_public_key_does_not_accept(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / INSTALLER_NAME.replace("0.9.0", updater.__version__)
            installer.write_bytes(INSTALLER_BYTES)
            env = dict(os.environ, TVIZ_UPDATE_SIGNING_KEY=SECRET.hex())
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "make_update_manifest.py"), "--installer", str(installer), "--out", str(Path(temporary) / "update.json")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("signature is invalid", completed.stderr)
            self.assertFalse((Path(temporary) / "update.json").exists())

    def test_payload_points_at_the_tagged_release_asset(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import make_update_manifest
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / INSTALLER_NAME
            installer.write_bytes(INSTALLER_BYTES)
            payload = make_update_manifest.build_payload(installer, "0.9.0")
        self.assertEqual(payload, _payload())
        verify_manifest(sign_manifest(payload, SECRET), PUBLIC_HEX)


if __name__ == "__main__":
    unittest.main()
