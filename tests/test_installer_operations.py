from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from installer import track_visualizer_installer as installer


class InstallerOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.source = self.root / "source"
        self.install_root = self.root / "installed"
        self.script_directory = self.root / "resolve-scripts"
        self._resource_tree()

    def _resource_tree(self) -> None:
        for resource in installer.required_resources(self.source):
            if resource.name == installer.MANIFEST_NAME:
                continue
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(b"packaged")
        self._write_script_template("v1")
        self._write_manifest("1.0")

    def _write_script_template(self, version: str) -> None:
        script = self.source / installer.RESOURCE_DIRECTORY / installer.PLUGIN_SCRIPT_NAME
        script.write_text(
            f"-- {version}\n"
            "root = [[__INSTALL_ROOT__]]\n"
            "engine = [[__ENGINE_EXECUTABLE__]]\n"
            "runner = [[__RUNNER_EXECUTABLE__]]\n"
            "ffmpeg = [[__FFMPEG_EXECUTABLE__]]\n"
            "ffprobe = [[__FFPROBE_EXECUTABLE__]]\n",
            encoding="utf-8",
        )

    def _manifest_data(self, version: str = "1.0") -> dict[str, object]:
        records = []
        for path in sorted(self.source.rglob("*")):
            if not path.is_file() or path.name == installer.MANIFEST_NAME:
                continue
            relative = path.relative_to(self.source)
            records.append(
                {
                    "path": relative.as_posix(),
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "mode": "0755" if relative.parts[0] == installer.BIN_DIRECTORY else "0644",
                }
            )
        return {
            "schema": installer.MANIFEST_SCHEMA,
            "product": installer.MANIFEST_PRODUCT,
            "version": version,
            "files": records,
        }

    def _write_manifest(self, version: str = "1.0") -> None:
        self.source.mkdir(parents=True, exist_ok=True)
        (self.source / installer.MANIFEST_NAME).write_text(
            json.dumps(self._manifest_data(version), sort_keys=True), encoding="utf-8"
        )

    def _rewrite_payload(self, version: str) -> None:
        for resource in installer.required_resources(self.source):
            if resource.name not in {installer.MANIFEST_NAME, installer.PLUGIN_SCRIPT_NAME}:
                resource.write_bytes(f"payload {version}".encode())
        self._write_script_template(version)
        self._write_manifest(version)

    def _legacy_script_content(self, target_root: Path | None = None) -> str:
        root = target_root or self.install_root
        return (
            "# DaVinci Track Visualizer legacy utility\n"
            f"INSTALL_ROOT = {str(root)!r}\n"
            f"ENGINE = {str(root / installer.ENGINE_NAME)!r}\n"
            f"RUNNER = {str(root / installer.RUNNER_NAME)!r}\n"
            f"FFMPEG = {str(root / installer.FFMPEG_NAME)!r}\n"
            f"FFPROBE = {str(root / installer.FFPROBE_NAME)!r}\n"
        )

    def _arguments(self, *arguments: str) -> list[str]:
        return [
            "--no-pause",
            "--install-root",
            str(self.install_root),
            "--resolve-script-dir",
            str(self.script_directory),
            *arguments,
        ]

    def _run(self, *arguments: str) -> int:
        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "stop_existing_processes"),
            patch.object(installer, "unregister_runner_autostart"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return installer.main(self._arguments(*arguments))

    def _create_directory_symlink(self, target: Path, link: Path) -> None:
        try:
            os.symlink(target, link, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Directory symlinks are unavailable: {exc}")

    def _create_file_symlink(self, target: Path, link: Path) -> None:
        try:
            os.symlink(target, link)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"File symlinks are unavailable: {exc}")

    def test_install_recursively_copies_nested_licenses(self) -> None:
        nested_license = self.source / "licenses" / "Pillow" / "dist-info" / "LICENSE"
        nested_license.parent.mkdir(parents=True)
        nested_license.write_text("nested license\n", encoding="utf-8")
        direct_license = self.source / "licenses" / "FFMPEG_LICENSE.txt"
        direct_license.write_text("ffmpeg license\n", encoding="utf-8")
        self._write_manifest()

        self.assertEqual(self._run(), 0)

        self.assertEqual(
            (self.install_root / "licenses" / "Pillow" / "dist-info" / "LICENSE").read_text(
                encoding="utf-8"
            ),
            "nested license\n",
        )
        self.assertEqual(
            (self.install_root / "licenses" / "FFMPEG_LICENSE.txt").read_text(
                encoding="utf-8"
            ),
            "ffmpeg license\n",
        )

    def test_manifest_rejects_unsafe_paths_on_every_platform(self) -> None:
        invalid_paths = (
            "/licenses/victim.txt",
            "C:/victim.txt",
            "licenses/D:/victim.txt",
            "licenses\\victim.txt",
            "licenses/./victim.txt",
            "licenses/../victim.txt",
            "licenses//victim.txt",
            "licenses/file:name.txt",
            "licenses/NUL.txt",
            "licenses/trailing. ",
        )
        for invalid_path in invalid_paths:
            with self.subTest(path=invalid_path):
                data = self._manifest_data()
                files = list(data["files"])
                files.append(
                    {
                        "path": invalid_path,
                        "size": 0,
                        "sha256": hashlib.sha256(b"").hexdigest(),
                        "mode": "0644",
                    }
                )
                data["files"] = files
                with self.assertRaisesRegex(ValueError, "Unsafe manifest path"):
                    installer._manifest_from_data(data)

        collision = self._manifest_data()
        files = list(collision["files"])
        empty_record = {
            "size": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
            "mode": "0644",
        }
        files.extend(
            (
                {"path": "licenses/Case.txt", **empty_record},
                {"path": "licenses/case.txt", **empty_record},
            )
        )
        collision["files"] = files
        with self.assertRaisesRegex(ValueError, "case-insensitive filesystem"):
            installer._manifest_from_data(collision)

    def test_install_dry_run_validates_hashes_without_mutation(self) -> None:
        engine = self.source / installer.BIN_DIRECTORY / installer.ENGINE_NAME
        engine.write_bytes(b"corrupt after manifest")
        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(ValueError, "does not match manifest hash"),
        ):
            installer.main(self._arguments("--dry-run"))
        self.assertFalse(self.install_root.exists())
        self.assertFalse(self.script_directory.exists())
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_install_dry_run_rejects_symlinked_managed_directory(self) -> None:
        managed_license = self.source / "licenses" / "nested" / "LICENSE"
        managed_license.parent.mkdir(parents=True)
        managed_license.write_text("managed\n", encoding="utf-8")
        self._write_manifest()
        outside = self.root / "outside"
        outside.mkdir()
        self.install_root.mkdir()
        self._create_directory_symlink(outside, self.install_root / "licenses")

        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "link or junction"),
        ):
            installer.main(self._arguments("--dry-run"))
        self.assertEqual(list(outside.iterdir()), [])
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_install_dry_run_rejects_windows_junction_marker(self) -> None:
        self.install_root.mkdir()

        def mark_root_as_junction(path: Path) -> bool:
            return path == self.install_root

        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "_is_link_or_junction", side_effect=mark_root_as_junction),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "link or junction"),
        ):
            installer.main(self._arguments("--dry-run"))
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_main_scopes_install_and_uninstall_dry_run_computes_real_plan(self) -> None:
        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(installer.main(self._arguments()), 0)
        stop_processes.assert_called_once_with(self.install_root.absolute())
        unregister.assert_called_once_with(self.install_root.absolute())

        output = io.StringIO()
        with (
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(
                installer.main(
                    self._arguments("--language", "en", "--uninstall", "--dry-run")
                ),
                0,
            )
        expected_count = len(installer.build_uninstall_plan(self.install_root, self.script_directory).files)
        self.assertIn(f"{expected_count} managed files would be removed", output.getvalue())
        self.assertTrue((self.install_root / installer.MANIFEST_NAME).is_file())
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_transaction_rolls_back_every_managed_file_on_upgrade_failure(self) -> None:
        managed_license = self.source / "licenses" / "old" / "LICENSE"
        managed_license.parent.mkdir(parents=True)
        managed_license.write_text("old license\n", encoding="utf-8")
        self._write_manifest("1.0")
        self.assertEqual(self._run(), 0)
        settings = self.install_root / "settings.json"
        settings.write_text("user settings\n", encoding="utf-8")

        original_files = {
            path: path.read_bytes()
            for path in (
                *(self.install_root / name for name in installer.MANAGED_ROOT_FILE_NAMES),
                self.install_root / "licenses" / "old" / "LICENSE",
                self.script_directory / installer.PLUGIN_SCRIPT_NAME,
            )
        }
        for resource in installer.required_resources(self.source):
            if resource.name != installer.MANIFEST_NAME and resource.name != installer.PLUGIN_SCRIPT_NAME:
                resource.write_bytes(b"version two")
        self._write_script_template("v2")
        managed_license.write_text("new license contents\n", encoding="utf-8")
        self._write_manifest("2.0")

        real_replace = installer._replace_path
        failure_injected = False

        def fail_runner_once(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
            nonlocal failure_injected
            source_path = Path(source)
            target_path = Path(target)
            if (
                not failure_injected
                and target_path == self.install_root / installer.RUNNER_NAME
                and ".tviz-new-" in source_path.name
            ):
                failure_injected = True
                raise OSError("injected commit failure")
            real_replace(source_path, target_path)

        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "stop_existing_processes"),
            patch.object(installer, "unregister_runner_autostart"),
            patch.object(installer, "_replace_path", side_effect=fail_runner_once),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(OSError, "injected commit failure"),
        ):
            installer.main(self._arguments())

        self.assertTrue(failure_injected)
        for path, content in original_files.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assertEqual(settings.read_text(encoding="utf-8"), "user settings\n")
        transaction_files = [
            path
            for root in (self.install_root, self.script_directory)
            for path in root.rglob("*")
            if ".tviz-" in path.name
        ]
        self.assertEqual(transaction_files, [])

    def test_base_exception_interrupt_rolls_back_and_removes_journal(self) -> None:
        self.assertEqual(self._run(), 0)
        settings = self.install_root / "settings.json"
        settings.write_text("preserve\n", encoding="utf-8")
        original_files = {
            path: path.read_bytes()
            for path in (
                *(self.install_root / name for name in installer.MANAGED_ROOT_FILE_NAMES),
                self.script_directory / installer.PLUGIN_SCRIPT_NAME,
            )
        }
        self._rewrite_payload("2.0")
        real_replace = installer._replace_path
        interrupted = False

        def interrupt_runner(
            source: str | os.PathLike[str], target: str | os.PathLike[str]
        ) -> None:
            nonlocal interrupted
            source_path = Path(source)
            target_path = Path(target)
            if (
                not interrupted
                and target_path == self.install_root / installer.RUNNER_NAME
                and ".tviz-new-" in source_path.name
            ):
                interrupted = True
                raise KeyboardInterrupt
            real_replace(source_path, target_path)

        with (
            patch.object(installer, "_replace_path", side_effect=interrupt_runner),
            self.assertRaises(KeyboardInterrupt),
        ):
            plan = installer.build_install_plan(
                self.source,
                self.install_root,
                self.script_directory,
                language="en",
            )
            installer.install_from_plan(plan, self.install_root, self.script_directory)

        self.assertTrue(interrupted)
        for path, content in original_files.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assertEqual(settings.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse(
            (self.install_root / installer.TRANSACTION_JOURNAL_NAME).exists()
        )
        self.assertEqual(
            [
                path
                for root in (self.install_root, self.script_directory)
                for path in root.rglob("*")
                if ".tviz-" in path.name
            ],
            [],
        )

    def test_stale_active_upgrade_journal_restores_previous_install(self) -> None:
        self.assertEqual(self._run(), 0)
        original_files = {
            path: path.read_bytes()
            for path in (
                *(self.install_root / name for name in installer.MANAGED_ROOT_FILE_NAMES),
                self.script_directory / installer.PLUGIN_SCRIPT_NAME,
            )
        }
        self._rewrite_payload("2.0")
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        real_replace = installer._replace_path
        interrupted = False

        def terminate_during_replace(
            source: str | os.PathLike[str], target: str | os.PathLike[str]
        ) -> None:
            nonlocal interrupted
            source_path = Path(source)
            target_path = Path(target)
            if (
                not interrupted
                and target_path == self.install_root / installer.RUNNER_NAME
                and ".tviz-new-" in source_path.name
            ):
                interrupted = True
                raise KeyboardInterrupt
            real_replace(source_path, target_path)

        with (
            patch.object(installer, "_replace_path", side_effect=terminate_during_replace),
            patch.object(
                installer,
                "_recover_transaction",
                side_effect=RuntimeError("simulated process termination"),
            ),
            self.assertRaisesRegex(RuntimeError, "recovery is incomplete"),
        ):
            installer.install_from_plan(plan, self.install_root, self.script_directory)

        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        self.assertTrue(interrupted)
        self.assertTrue(journal.is_file())
        self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["phase"], "active")

        installer._recover_stale_transaction(self.install_root, self.script_directory)

        for path, content in original_files.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assertFalse(journal.exists())
        self.assertEqual(
            [
                path
                for root in (self.install_root, self.script_directory)
                for path in root.rglob("*")
                if ".tviz-" in path.name
            ],
            [],
        )

    def test_stale_active_fresh_install_recovers_absent_originals(self) -> None:
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        real_safe_replace = installer._safe_replace
        interrupted = False

        def interrupt_first_target(source: Path, target: Path, **values: object) -> None:
            nonlocal interrupted
            if (
                not interrupted
                and target == self.install_root / installer.ENGINE_NAME
                and ".tviz-new-" in source.name
            ):
                interrupted = True
                raise KeyboardInterrupt
            real_safe_replace(source, target, **values)

        with (
            patch.object(installer, "_safe_replace", side_effect=interrupt_first_target),
            patch.object(
                installer,
                "_recover_transaction",
                side_effect=RuntimeError("simulated process termination"),
            ),
            self.assertRaisesRegex(RuntimeError, "recovery is incomplete"),
        ):
            installer.install_from_plan(plan, self.install_root, self.script_directory)

        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        self.assertTrue(interrupted)
        self.assertTrue(journal.is_file())
        installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertFalse(journal.exists())
        self.assertFalse((self.install_root / installer.ENGINE_NAME).exists())
        self.assertEqual(self._run(), 0)

    def test_active_recovery_tolerates_lost_created_script_directory(self) -> None:
        custom_script_directory = self.root / "custom-resolve-scripts"
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            custom_script_directory,
            language="en",
        )
        real_safe_replace = installer._safe_replace

        def interrupt_script(source: Path, target: Path, **values: object) -> None:
            if (
                target == custom_script_directory / installer.PLUGIN_SCRIPT_NAME
                and ".tviz-apply-" in source.name
            ):
                raise KeyboardInterrupt
            real_safe_replace(source, target, **values)

        with (
            patch.object(installer, "_safe_replace", side_effect=interrupt_script),
            patch.object(
                installer,
                "_recover_transaction",
                side_effect=RuntimeError("simulated process termination"),
            ),
            self.assertRaisesRegex(RuntimeError, "recovery is incomplete"),
        ):
            installer.install_from_plan(plan, self.install_root, custom_script_directory)

        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        data = json.loads(journal.read_text(encoding="utf-8"))
        self.assertIn(str(custom_script_directory), data["created_directories"])
        shutil.rmtree(custom_script_directory)
        with patch.object(installer, "stop_existing_processes"):
            installer._recover_stale_transaction(
                self.install_root, self.root / "new-cli-script-directory"
            )
        self.assertFalse(journal.exists())
        self.assertFalse(custom_script_directory.exists())

    def test_committed_recovery_republishes_lost_created_script_directory(self) -> None:
        custom_script_directory = self.root / "custom-resolve-scripts"
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            custom_script_directory,
            language="en",
        )
        script_change = next(
            change
            for change in plan.changes
            if change.target == custom_script_directory / installer.PLUGIN_SCRIPT_NAME
        )
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        real_unlink = installer._unlink_with_retries

        def retain_staged_script(
            path: Path, expected_identity: installer._PathIdentity
        ) -> None:
            if (
                path.parent == custom_script_directory.parent
                and path.name.startswith(
                    f".{installer.PLUGIN_SCRIPT_NAME}.tviz-new-"
                )
            ):
                raise PermissionError("staged script is locked")
            real_unlink(path, expected_identity)

        with (
            patch.object(
                installer, "_unlink_with_retries", side_effect=retain_staged_script
            ),
            self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"),
        ):
            installer.install_from_plan(plan, self.install_root, custom_script_directory)
        data = json.loads(journal.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "committed")
        self.assertIn(str(custom_script_directory), data["created_directories"])
        script_operation = next(
            operation
            for operation in data["operations"]
            if Path(str(operation["target"])) == script_change.target
        )
        staged_script = Path(str(script_operation["staged"]))
        self.assertTrue(staged_script.is_file())
        self.assertEqual(staged_script.parent, custom_script_directory.parent)
        shutil.rmtree(custom_script_directory)
        with patch.object(installer, "stop_existing_processes"):
            installer._recover_stale_transaction(
                self.install_root, self.root / "new-cli-script-directory"
            )
        self.assertFalse(journal.exists())
        self.assertEqual(script_change.target.read_bytes(), script_change.content)

    def test_interrupted_script_root_a_recovers_before_installing_to_b(self) -> None:
        script_directory_b = self.root / "resolve-scripts-b"
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        real_safe_replace = installer._safe_replace
        interrupted = False

        def interrupt_script(source: Path, target: Path, **values: object) -> None:
            nonlocal interrupted
            if (
                not interrupted
                and target == self.script_directory / installer.PLUGIN_SCRIPT_NAME
                and ".tviz-apply-" in source.name
            ):
                interrupted = True
                raise KeyboardInterrupt
            real_safe_replace(source, target, **values)

        with (
            patch.object(installer, "_safe_replace", side_effect=interrupt_script),
            patch.object(
                installer,
                "_recover_transaction",
                side_effect=RuntimeError("simulated process termination"),
            ),
            self.assertRaisesRegex(RuntimeError, "recovery is incomplete"),
        ):
            installer.install_from_plan(plan, self.install_root, self.script_directory)

        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        recorded = json.loads(journal.read_text(encoding="utf-8"))["roots"]
        self.assertIn(str(self.script_directory), recorded)
        self.assertNotIn(str(script_directory_b), recorded)
        self.assertEqual(
            self._run("--resolve-script-dir", str(script_directory_b)),
            0,
        )
        self.assertTrue(interrupted)
        self.assertFalse((self.script_directory / installer.PLUGIN_SCRIPT_NAME).exists())
        self.assertTrue((script_directory_b / installer.PLUGIN_SCRIPT_NAME).is_file())
        state = json.loads(
            (self.install_root / installer.INSTALL_STATE_NAME).read_text(encoding="utf-8")
        )
        self.assertEqual(
            Path(state["script_path"]),
            script_directory_b / installer.PLUGIN_SCRIPT_NAME,
        )

    def test_windows_stale_recovery_validates_then_stops_before_replay(self) -> None:
        self.install_root.mkdir()
        self.script_directory.mkdir()
        target = self.install_root / installer.ENGINE_NAME
        operation = installer._operation_record(
            "replace",
            target,
            None,
            None,
            None,
            None,
            len(b"new"),
            hashlib.sha256(b"new").hexdigest(),
        )
        data = {
            "schema": installer.TRANSACTION_SCHEMA,
            "transaction_id": "9" * 32,
            "phase": "active",
            "roots": [str(self.install_root), str(self.script_directory)],
            "created_directories": [],
            "operations": [operation],
        }
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        journal.write_text(json.dumps(data), encoding="utf-8")

        with (
            patch.object(
                installer,
                "_windows_stale_recovery_requires_process_stop",
                return_value=True,
            ),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            self.assertRaisesRegex(RuntimeError, "requires recovery before a dry run"),
        ):
            installer._recover_stale_transaction(
                self.install_root, self.root / "new-cli-script-root", dry_run=True
            )
        stop_processes.assert_not_called()
        self.assertTrue(journal.is_file())

        events: list[str] = []
        real_load = installer._load_transaction_journal
        real_recover = installer._recover_transaction

        def observe_load(*args: object, **kwargs: object) -> object:
            events.append("validate")
            return real_load(*args, **kwargs)

        def observe_stop(target_root: Path) -> None:
            self.assertEqual(target_root, self.install_root)
            events.append("stop")

        def observe_recover(*args: object, **kwargs: object) -> None:
            events.append("replay")
            real_recover(*args, **kwargs)

        with (
            patch.object(
                installer,
                "_windows_stale_recovery_requires_process_stop",
                return_value=True,
            ),
            patch.object(installer, "_load_transaction_journal", side_effect=observe_load),
            patch.object(installer, "stop_existing_processes", side_effect=observe_stop),
            patch.object(installer, "_recover_transaction", side_effect=observe_recover),
        ):
            installer._recover_stale_transaction(
                self.install_root, self.root / "new-cli-script-root"
            )
        self.assertEqual(events[:3], ["validate", "stop", "replay"])
        self.assertFalse(journal.exists())

    def test_stale_recovery_rejects_wrong_target_and_noncanonical_script_roots(self) -> None:
        self.install_root.mkdir()
        self.script_directory.mkdir()
        target = self.install_root / installer.ENGINE_NAME
        operation = installer._operation_record(
            "replace",
            target,
            None,
            None,
            None,
            None,
            len(b"new"),
            hashlib.sha256(b"new").hexdigest(),
        )
        data = {
            "schema": installer.TRANSACTION_SCHEMA,
            "transaction_id": "8" * 32,
            "phase": "active",
            "roots": [str(self.root / "other-install"), str(self.script_directory)],
            "created_directories": [],
            "operations": [operation],
        }
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        journal.write_text(json.dumps(data), encoding="utf-8")
        with (
            patch.object(
                installer,
                "_windows_stale_recovery_requires_process_stop",
                return_value=True,
            ),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            self.assertRaisesRegex(RuntimeError, "different install root"),
        ):
            installer._recover_stale_transaction(
                self.install_root, self.script_directory
            )
        stop_processes.assert_not_called()

        data["roots"] = [
            str(self.install_root),
            str(self.script_directory / "nested" / ".."),
        ]
        journal.write_text(json.dumps(data), encoding="utf-8")
        with (
            patch.object(
                installer,
                "_windows_stale_recovery_requires_process_stop",
                return_value=True,
            ),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            self.assertRaisesRegex(RuntimeError, "Invalid installer transaction roots"),
        ):
            installer._recover_stale_transaction(
                self.install_root, self.script_directory
            )
        stop_processes.assert_not_called()
        self.assertTrue(journal.is_file())

    def test_fresh_license_install_rolls_back_after_manifest_mutation(self) -> None:
        license_path = self.source / "licenses" / "New" / "NOTICE.txt"
        license_path.parent.mkdir(parents=True)
        license_path.write_text("new license\n", encoding="utf-8")
        self._write_manifest()
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        real_write_journal = installer._write_journal
        interrupted = False

        def interrupt_manifest_state(path: Path, data: dict[str, object]) -> None:
            nonlocal interrupted
            manifest_operation = next(
                (
                    operation
                    for operation in data["operations"]
                    if Path(str(operation["target"]))
                    == self.install_root / installer.MANIFEST_NAME
                ),
                None,
            )
            if (
                not interrupted
                and data["phase"] == "active"
                and manifest_operation is not None
                and manifest_operation["state"] == "applied"
            ):
                interrupted = True
                raise KeyboardInterrupt
            real_write_journal(path, data)

        with (
            patch.object(installer, "_write_journal", side_effect=interrupt_manifest_state),
            self.assertRaises(KeyboardInterrupt),
        ):
            installer.install_from_plan(plan, self.install_root, self.script_directory)

        self.assertTrue(interrupted)
        self.assertFalse((self.install_root / installer.MANIFEST_NAME).exists())
        self.assertFalse(
            (self.install_root / "licenses" / "New" / "NOTICE.txt").exists()
        )
        self.assertFalse(
            (self.install_root / installer.TRANSACTION_JOURNAL_NAME).exists()
        )

    def test_stale_active_uninstall_journal_restores_managed_files(self) -> None:
        self.assertEqual(self._run(), 0)
        plan = installer.build_uninstall_plan(self.install_root, self.script_directory)
        original_files = {path: path.read_bytes() for path in plan.files}
        real_safe_unlink = installer._safe_unlink
        interrupted = False

        def interrupt_runner(path: Path, **values: object) -> None:
            nonlocal interrupted
            if not interrupted and path == self.install_root / installer.RUNNER_NAME:
                interrupted = True
                raise KeyboardInterrupt
            real_safe_unlink(path, **values)

        with (
            patch.object(installer, "_safe_unlink", side_effect=interrupt_runner),
            patch.object(
                installer,
                "_recover_transaction",
                side_effect=RuntimeError("simulated process termination"),
            ),
            self.assertRaisesRegex(RuntimeError, "recovery is incomplete"),
        ):
            installer.uninstall_from_plan(plan, self.install_root, self.script_directory)

        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        self.assertTrue(interrupted)
        self.assertTrue(journal.is_file())
        installer._recover_stale_transaction(self.install_root, self.script_directory)
        for path, content in original_files.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assertFalse(journal.exists())

    def test_committed_locked_backup_retains_recoverable_journal(self) -> None:
        source = self.root / "new.bin"
        target = self.root / "destination" / "runtime.bin"
        source.write_bytes(b"new")
        target.parent.mkdir()
        target.write_bytes(b"old")
        real_unlink_with_retries = installer._unlink_with_retries

        def deny_backup_cleanup(
            path: Path, expected_identity: installer._PathIdentity
        ) -> None:
            if ".tviz-backup-" in path.name:
                raise PermissionError("backup is locked")
            real_unlink_with_retries(path, expected_identity)

        with (
            patch.object(
                installer,
                "_unlink_with_retries",
                side_effect=deny_backup_cleanup,
            ),
            self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"),
        ):
            installer.copy_required_file(source, target)

        journal = target.parent / installer.TRANSACTION_JOURNAL_NAME
        backups = list(target.parent.glob(".*.tviz-backup-*.tmp"))
        self.assertEqual(target.read_bytes(), b"new")
        self.assertTrue(journal.is_file())
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["phase"], "committed")

        installer._recover_transaction(
            journal,
            (target.parent,),
            allowed_targets=(target,),
        )

        self.assertEqual(target.read_bytes(), b"new")
        self.assertFalse(journal.exists())
        self.assertEqual(list(target.parent.glob(".*.tviz-backup-*.tmp")), [])

    def test_rendered_lua_staged_bytes_are_hashed_and_reverified(self) -> None:
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        script_change = next(
            change for change in plan.changes if change.target.name == installer.PLUGIN_SCRIPT_NAME
        )
        self.assertIsNotNone(script_change.content)
        expected_bytes = script_change.content
        self.assertEqual(script_change.expected_size, len(expected_bytes))
        self.assertEqual(
            script_change.expected_sha256,
            hashlib.sha256(expected_bytes).hexdigest(),
        )
        real_prepare_change = installer._prepare_change

        def tamper_after_prepare(
            change: installer.FileChange, staged: installer._SecureTemp
        ) -> None:
            real_prepare_change(change, staged)
            if change.target.name == installer.PLUGIN_SCRIPT_NAME:
                os.lseek(staged.descriptor, 0, os.SEEK_END)
                os.write(staged.descriptor, b"-- tampered\n")
                os.fsync(staged.descriptor)

        with (
            patch.object(installer, "_prepare_change", side_effect=tamper_after_prepare),
            self.assertRaisesRegex(ValueError, "Staged payload changed"),
        ):
            installer.install_from_plan(plan, self.install_root, self.script_directory)
        self.assertFalse(
            (self.script_directory / installer.PLUGIN_SCRIPT_NAME).exists()
        )
        self.assertFalse(
            (self.install_root / installer.TRANSACTION_JOURNAL_NAME).exists()
        )

    def test_directory_identity_swaps_fail_closed_before_temp_and_replace(self) -> None:
        parent = self.root / "managed"
        parent.mkdir()

        with (
            patch.object(
                installer,
                "_assert_directory_snapshot",
                side_effect=RuntimeError(
                    "Managed directory identity changed during transaction"
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "directory identity changed"),
        ):
            installer._temporary_file(parent / "payload.bin", "new")
        self.assertEqual(list(parent.iterdir()), [])

        replacement_parent = self.root / "replace"
        moved_replacement_parent = self.root / "replace-moved"
        replacement_parent.mkdir()
        source = replacement_parent / "staged.tmp"
        target = replacement_parent / "payload.bin"
        source.write_bytes(b"new")
        target.write_bytes(b"old")
        snapshot = installer._capture_directory_snapshot(replacement_parent)
        source_identity = installer._path_identity(source)
        target_identity = installer._path_identity(target)
        replacement_parent.rename(moved_replacement_parent)
        replacement_parent.mkdir()

        with self.assertRaisesRegex(RuntimeError, "directory identity changed"):
            installer._safe_replace(
                source,
                target,
                parent_snapshot=snapshot,
                source_identity=source_identity,
                target_identity=target_identity,
            )
        self.assertEqual((moved_replacement_parent / "staged.tmp").read_bytes(), b"new")
        self.assertEqual((moved_replacement_parent / "payload.bin").read_bytes(), b"old")
        self.assertEqual(list(replacement_parent.iterdir()), [])

    def test_unavailable_filesystem_root_fails_without_looping(self) -> None:
        with (
            patch.object(installer, "_path_exists", return_value=False),
            self.assertRaisesRegex(RuntimeError, "Filesystem root is unavailable"),
        ):
            installer._ensure_directory(
                self.root / "missing" / "directory",
                set(),
                (self.root,),
            )

    def test_forged_journal_cannot_target_user_data_or_unknown_files(self) -> None:
        self.install_root.mkdir()
        self.script_directory.mkdir()
        protected = (
            self.install_root / "settings.json",
            self.install_root / "outputs" / "mix.mp4",
            self.install_root / "tasks" / "pending.json",
            self.install_root / "tmp" / "working.txt",
            self.install_root / "logs" / "engine.log",
            self.install_root / "unknown.dat",
        )
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        for target in protected:
            with self.subTest(target=target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"preserve")
                identity = installer._path_identity(target)
                data = {
                    "schema": installer.TRANSACTION_SCHEMA,
                    "transaction_id": "1" * 32,
                    "phase": "active",
                    "roots": [str(self.install_root), str(self.script_directory)],
                    "created_directories": [],
                    "operations": [
                        installer._operation_record(
                            "delete",
                            target,
                            identity,
                            target.stat().st_mode & 0o777,
                            target.stat().st_size,
                            hashlib.sha256(target.read_bytes()).hexdigest(),
                            None,
                            None,
                        )
                    ],
                }
                journal.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "Unsafe installer transaction target"):
                    installer._recover_stale_transaction(
                        self.install_root, self.script_directory
                    )
                self.assertEqual(target.read_bytes(), b"preserve")
                journal.unlink()

    def test_forged_journal_rejects_unlisted_license_and_unrelated_directory(self) -> None:
        self.assertEqual(self._run(), 0)
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        user_license = self.install_root / "licenses" / "custom" / "USER.txt"
        user_license.parent.mkdir(parents=True)
        user_license.write_bytes(b"preserve")
        user_operation = installer._operation_record(
            "delete",
            user_license,
            installer._path_identity(user_license),
            user_license.stat().st_mode & 0o777,
            user_license.stat().st_size,
            hashlib.sha256(user_license.read_bytes()).hexdigest(),
            None,
            None,
        )
        data = {
            "schema": installer.TRANSACTION_SCHEMA,
            "transaction_id": "3" * 32,
            "phase": "active",
            "roots": [str(self.install_root), str(self.script_directory)],
            "created_directories": [],
            "operations": [user_operation],
        }
        journal.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Unsafe installer transaction target"):
            installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertEqual(user_license.read_bytes(), b"preserve")
        journal.unlink()

        outputs = self.install_root / "outputs"
        outputs.mkdir()
        engine = self.install_root / installer.ENGINE_NAME
        data["transaction_id"] = "4" * 32
        data["created_directories"] = [str(outputs)]
        data["operations"] = [
            installer._operation_record(
                "delete",
                engine,
                installer._path_identity(engine),
                engine.stat().st_mode & 0o777,
                engine.stat().st_size,
                hashlib.sha256(engine.read_bytes()).hexdigest(),
                None,
                None,
            )
        ]
        journal.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Unsafe installer transaction directory"):
            installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertTrue(outputs.is_dir())
        self.assertTrue(engine.is_file())

    def test_recovery_removes_only_matching_unregistered_transaction_temps(self) -> None:
        self.install_root.mkdir()
        self.script_directory.mkdir()
        transaction_id = "a" * 32
        target = self.install_root / installer.ENGINE_NAME
        operation = installer._operation_record(
            "replace",
            target,
            None,
            None,
            None,
            None,
            len(b"new"),
            hashlib.sha256(b"new").hexdigest(),
        )
        data = {
            "schema": installer.TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "phase": "active",
            "roots": [str(self.install_root), str(self.script_directory)],
            "created_directories": [],
            "operations": [operation],
        }
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        journal.write_text(json.dumps(data), encoding="utf-8")
        orphan = self.install_root / (
            f".{target.name}.tviz-new-{transaction_id}-orphan.tmp"
        )
        other_transaction = self.install_root / (
            f".{target.name}.tviz-new-{'b' * 32}-preserve.tmp"
        )
        unrelated_dotfile = self.install_root / ".user-settings.tmp"
        orphan.write_bytes(b"orphan")
        other_transaction.write_bytes(b"other")
        unrelated_dotfile.write_bytes(b"user")

        with patch.object(installer, "stop_existing_processes"):
            installer._recover_stale_transaction(
                self.install_root, self.root / "different-cli-script-root"
            )

        self.assertFalse(orphan.exists())
        self.assertEqual(other_transaction.read_bytes(), b"other")
        self.assertEqual(unrelated_dotfile.read_bytes(), b"user")

    def test_no_journal_cleanup_removes_only_exact_abandoned_journal_temps(self) -> None:
        self.install_root.mkdir()
        transaction_id = "c" * 32
        abandoned = self.install_root / f".tviz-journal-{transaction_id}-orphan.tmp"
        unrelated = (
            self.install_root / f".engine.tviz-journal-{transaction_id}-preserve.tmp"
        )
        wrong_id = self.install_root / ".tviz-journal-short-preserve.tmp"
        wrong_suffix = (
            self.install_root / f".tviz-journal-{transaction_id}-preserve.tmp.extra"
        )
        matching_directory = (
            self.install_root / f".tviz-journal-{transaction_id}-directory.tmp"
        )
        abandoned.write_bytes(b"orphan")
        unrelated.write_bytes(b"unrelated")
        wrong_id.write_bytes(b"wrong id")
        wrong_suffix.write_bytes(b"wrong suffix")
        matching_directory.mkdir()

        self.assertFalse(
            installer._recover_stale_transaction(
                self.install_root, self.script_directory
            )
        )
        self.assertFalse(abandoned.exists())
        self.assertEqual(unrelated.read_bytes(), b"unrelated")
        self.assertEqual(wrong_id.read_bytes(), b"wrong id")
        self.assertEqual(wrong_suffix.read_bytes(), b"wrong suffix")
        self.assertTrue(matching_directory.is_dir())

    def test_committed_journal_requires_applied_operations(self) -> None:
        self.assertEqual(self._run(), 0)
        engine = self.install_root / installer.ENGINE_NAME
        operation = installer._operation_record(
            "delete",
            engine,
            installer._path_identity(engine),
            engine.stat().st_mode & 0o777,
            engine.stat().st_size,
            hashlib.sha256(engine.read_bytes()).hexdigest(),
            None,
            None,
        )
        data = {
            "schema": installer.TRANSACTION_SCHEMA,
            "transaction_id": "5" * 32,
            "phase": "committed",
            "roots": [str(self.install_root), str(self.script_directory)],
            "created_directories": [],
            "operations": [operation],
        }
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        journal.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "committed transaction state"):
            installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertTrue(engine.is_file())

    def test_forged_journal_rejects_extra_schema_and_mislocated_artifact(self) -> None:
        self.install_root.mkdir()
        self.script_directory.mkdir()
        target = self.install_root / installer.ENGINE_NAME
        user_file = self.install_root / "settings.json"
        user_file.write_bytes(b"preserve")
        operation = installer._operation_record(
            "replace",
            target,
            None,
            None,
            None,
            None,
            len(b"new"),
            hashlib.sha256(b"new").hexdigest(),
        )
        operation["staged"] = str(user_file)
        operation["staged_identity"] = installer._identity_data(
            installer._path_identity(user_file)
        )
        operation["state"] = "staged"
        data = {
            "schema": installer.TRANSACTION_SCHEMA,
            "transaction_id": "2" * 32,
            "phase": "active",
            "roots": [str(self.install_root), str(self.script_directory)],
            "created_directories": [],
            "operations": [operation],
        }
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        journal.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "artifact"):
            installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertEqual(user_file.read_bytes(), b"preserve")

        operation["staged"] = None
        operation["staged_identity"] = None
        operation["state"] = "planned"
        operation["unexpected"] = True
        journal.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "operation"):
            installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertEqual(user_file.read_bytes(), b"preserve")

    def test_recovery_refuses_substituted_backup_even_with_identical_bytes(self) -> None:
        source = self.root / "new.bin"
        target = self.root / "destination" / "runtime.bin"
        source.write_bytes(b"new")
        target.parent.mkdir()
        target.write_bytes(b"old")
        real_cleanup = installer._unlink_with_retries

        def retain_backup(
            path: Path, expected_identity: installer._PathIdentity
        ) -> None:
            if ".tviz-backup-" in path.name:
                raise PermissionError("retain backup")
            real_cleanup(path, expected_identity)

        with (
            patch.object(installer, "_unlink_with_retries", side_effect=retain_backup),
            self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"),
        ):
            installer.copy_required_file(source, target)
        journal = target.parent / installer.TRANSACTION_JOURNAL_NAME
        backup = next(target.parent.glob(".*.tviz-backup-*.tmp"))
        original_backup = backup.with_suffix(".original")
        backup.rename(original_backup)
        backup.write_bytes(b"old")

        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            installer._recover_transaction(
                journal,
                (target.parent,),
                allowed_targets=(target,),
            )
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(backup.read_bytes(), b"old")
        self.assertTrue(journal.is_file())

    def test_committed_recovery_preserves_backup_when_new_payload_is_lost(self) -> None:
        source = self.root / "new.bin"
        target = self.root / "destination" / "runtime.bin"
        source.write_bytes(b"new")
        target.parent.mkdir()
        target.write_bytes(b"old")
        real_cleanup = installer._unlink_with_retries

        def retain_backup(
            path: Path, expected_identity: installer._PathIdentity
        ) -> None:
            if ".tviz-backup-" in path.name:
                raise PermissionError("retain backup")
            real_cleanup(path, expected_identity)

        with (
            patch.object(installer, "_unlink_with_retries", side_effect=retain_backup),
            self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"),
        ):
            installer.copy_required_file(source, target)
        journal = target.parent / installer.TRANSACTION_JOURNAL_NAME
        backup = next(target.parent.glob(".*.tviz-backup-*.tmp"))
        target.rename(target.with_suffix(".lost"))

        with self.assertRaisesRegex(RuntimeError, "disappeared"):
            installer._recover_transaction(
                journal,
                (target.parent,),
                allowed_targets=(target,),
            )
        self.assertEqual(backup.read_bytes(), b"old")
        self.assertTrue(journal.is_file())

    def test_missing_bootstrap_parents_leave_recoverable_journal_and_retry(self) -> None:
        self.install_root = self.root / "missing" / "bootstrap" / "installed"
        self.script_directory = self.root / "missing-scripts" / "Utility"
        real_prepare = installer._prepare_change
        failed = False

        def fail_first_stage(
            change: installer.FileChange, staged: installer._SecureTemp
        ) -> None:
            nonlocal failed
            real_prepare(change, staged)
            if not failed:
                failed = True
                raise OSError("simulated validation interruption")

        with (
            patch.object(installer, "_prepare_change", side_effect=fail_first_stage),
            patch.object(
                installer,
                "_recover_transaction",
                side_effect=RuntimeError("simulated process termination"),
            ),
            self.assertRaisesRegex(RuntimeError, "recovery is incomplete"),
        ):
            self._run()
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        data = json.loads(journal.read_text(encoding="utf-8"))
        roots = (self.install_root, self.script_directory)
        self.assertTrue(
            all(
                any(installer._path_is_within(Path(path), root) for root in roots)
                for path in data["created_directories"]
            )
        )

        self.assertEqual(self._run(), 0)
        self.assertTrue((self.install_root / installer.MANIFEST_NAME).is_file())
        self.assertFalse(journal.exists())

    def test_stale_license_identity_swap_is_rejected_before_mutation(self) -> None:
        old_license = self.source / "licenses" / "Old" / "NOTICE.txt"
        old_license.parent.mkdir(parents=True)
        old_license.write_text("old\n", encoding="utf-8")
        self._write_manifest("1.0")
        self.assertEqual(self._run(), 0)
        old_license.unlink()
        old_license.parent.rmdir()
        self._write_manifest("2.0")
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        installed_license = self.install_root / "licenses" / "Old" / "NOTICE.txt"
        moved = installed_license.with_suffix(".original")
        installed_license.rename(moved)
        installed_license.write_bytes(moved.read_bytes())

        with self.assertRaisesRegex(RuntimeError, "Deletion target identity changed"):
            installer.install_from_plan(plan, self.install_root, self.script_directory)
        self.assertEqual(installed_license.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(
            json.loads((self.install_root / installer.MANIFEST_NAME).read_text())["version"],
            "1.0",
        )

    def test_lua_markers_are_single_use_and_paths_are_quoted(self) -> None:
        quoted_root = self.root / "root]]with\\slashes"
        plan = installer.build_install_plan(
            self.source,
            quoted_root,
            self.script_directory,
            language="en",
        )
        script = next(
            change.content
            for change in plan.changes
            if change.target.name == installer.PLUGIN_SCRIPT_NAME
        ).decode("utf-8")
        self.assertIn(installer._lua_quote(quoted_root), script)
        self.assertNotIn(f"[[{quoted_root}]]", script)
        self.assertNotIn("__INSTALL_ROOT__", script)

        source_script = self.source / installer.RESOURCE_DIRECTORY / installer.PLUGIN_SCRIPT_NAME
        source_script.write_text(
            source_script.read_text(encoding="utf-8") + "-- __INSTALL_ROOT__\n",
            encoding="utf-8",
        )
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "exactly once: __INSTALL_ROOT__"):
            installer.build_install_plan(
                self.source,
                self.install_root,
                self.script_directory,
                language="en",
            )

    def test_lua_render_uses_the_exact_manifest_verified_bytes(self) -> None:
        source_script = self.source / installer.RESOURCE_DIRECTORY / installer.PLUGIN_SCRIPT_NAME
        verified_bytes = source_script.read_bytes()
        real_render = installer._render_resolve_script

        def mutate_after_validation(source_bytes: bytes, target_root: Path) -> bytes:
            source_script.write_bytes(b"changed after validation")
            self.assertEqual(source_bytes, verified_bytes)
            return real_render(source_bytes, target_root)

        with patch.object(installer, "_render_resolve_script", side_effect=mutate_after_validation):
            plan = installer.build_install_plan(
                self.source,
                self.install_root,
                self.script_directory,
                language="en",
            )
        script = next(
            change.content
            for change in plan.changes
            if change.target.name == installer.PLUGIN_SCRIPT_NAME
        )
        self.assertIn(b"-- v1", script)

    def test_resolve_targets_substituted_after_planning_are_preserved(self) -> None:
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        self.script_directory.mkdir()
        current = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        current.write_bytes(b"foreign current script")
        with self.assertRaisesRegex(RuntimeError, "appeared after planning"):
            installer.install_from_plan(plan, self.install_root, self.script_directory)
        self.assertEqual(current.read_bytes(), b"foreign current script")
        current.unlink()

        legacy = self.script_directory / installer.LEGACY_PLUGIN_SCRIPT_NAME
        legacy.write_text(self._legacy_script_content(), encoding="utf-8")
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            self.script_directory,
            language="en",
        )
        original = legacy.with_suffix(".original")
        legacy.rename(original)
        legacy.write_bytes(original.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "Deletion target identity changed"):
            installer.install_from_plan(plan, self.install_root, self.script_directory)
        self.assertEqual(legacy.read_bytes(), original.read_bytes())

    def test_upgrade_moves_owned_resolve_script_and_commits_install_state(self) -> None:
        script_directory_b = self.root / "resolve-scripts-b"
        self.assertEqual(self._run(), 0)
        script_a = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        self.assertTrue(script_a.is_file())
        self._rewrite_payload("2.0")
        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            script_directory_b,
            language="en",
        )
        self.assertEqual(
            [change.target for change in plan.changes if change.commit_marker],
            [self.install_root / installer.INSTALL_STATE_NAME],
        )

        self.assertEqual(
            self._run("--resolve-script-dir", str(script_directory_b)),
            0,
        )
        script_b = script_directory_b / installer.PLUGIN_SCRIPT_NAME
        self.assertFalse(script_a.exists())
        self.assertTrue(script_b.is_file())
        state_path = self.install_root / installer.INSTALL_STATE_NAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(state),
            {
                "schema",
                "product",
                "target_root",
                "script_directory",
                "script_path",
                "script_size",
                "script_sha256",
            },
        )
        self.assertEqual(Path(state["script_directory"]), script_directory_b)
        self.assertEqual(Path(state["script_path"]), script_b)
        self.assertEqual(state["script_size"], script_b.stat().st_size)
        self.assertEqual(
            state["script_sha256"], hashlib.sha256(script_b.read_bytes()).hexdigest()
        )

        self.assertEqual(
            self._run("--uninstall", "--resolve-script-dir", str(script_directory_b)),
            0,
        )
        self.assertFalse(script_a.exists())
        self.assertFalse(script_b.exists())

    def test_modified_script_blocks_same_path_repair_but_allows_relocation(self) -> None:
        script_directory_b = self.root / "resolve-scripts-b"
        self.assertEqual(self._run(), 0)
        script_a = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        script_a.write_text("user modified old script\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unowned or modified"):
            installer.build_install_plan(
                self.source,
                self.install_root,
                self.script_directory,
                language="en",
            )
        self.assertEqual(
            script_a.read_text(encoding="utf-8"), "user modified old script\n"
        )
        foreign_b = script_directory_b / installer.PLUGIN_SCRIPT_NAME
        foreign_b.parent.mkdir()
        foreign_b.write_text("foreign destination\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unowned or modified Resolve script"):
            installer.build_install_plan(
                self.source,
                self.install_root,
                script_directory_b,
                language="en",
            )
        self.assertEqual(foreign_b.read_text(encoding="utf-8"), "foreign destination\n")
        foreign_b.unlink()

        plan = installer.build_install_plan(
            self.source,
            self.install_root,
            script_directory_b,
            language="en",
        )
        installer.install_from_plan(plan, self.install_root, script_directory_b)
        self.assertEqual(
            script_a.read_text(encoding="utf-8"), "user modified old script\n"
        )
        self.assertTrue(foreign_b.is_file())
        self.assertEqual(self._run("--uninstall", "--resolve-script-dir", str(script_directory_b)), 0)
        self.assertEqual(
            script_a.read_text(encoding="utf-8"), "user modified old script\n"
        )
        self.assertFalse(foreign_b.exists())

    def test_uninstall_uses_recorded_script_root_when_cli_selects_another(self) -> None:
        script_directory_b = self.root / "resolve-scripts-b"
        self.assertEqual(self._run(), 0)
        script_a = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        self.assertTrue(script_a.is_file())

        self.assertEqual(
            self._run("--uninstall", "--resolve-script-dir", str(script_directory_b)),
            0,
        )
        self.assertFalse(script_a.exists())
        self.assertFalse((script_directory_b / installer.PLUGIN_SCRIPT_NAME).exists())

    def test_missing_script_can_be_repaired_and_does_not_block_uninstall(self) -> None:
        self.assertEqual(self._run(), 0)
        script = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        script.unlink()

        self.assertEqual(self._run(), 0)
        self.assertTrue(script.is_file())
        script.unlink()
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertFalse(script.exists())
        for name in installer.MANAGED_ROOT_FILE_NAMES:
            self.assertFalse((self.install_root / name).exists(), name)

    def test_uninstall_preserves_modified_recorded_script(self) -> None:
        self.assertEqual(self._run(), 0)
        script = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        script.write_text("user modified script\n", encoding="utf-8")

        self.assertEqual(self._run("--uninstall"), 0)
        self.assertEqual(
            script.read_text(encoding="utf-8"), "user modified script\n"
        )
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertEqual(
            script.read_text(encoding="utf-8"), "user modified script\n"
        )

    def test_install_state_rejects_schema_root_path_and_hash_tampering(self) -> None:
        self.assertEqual(self._run(), 0)
        state_path = self.install_root / installer.INSTALL_STATE_NAME
        original = json.loads(state_path.read_text(encoding="utf-8"))
        cases: dict[str, dict[str, object]] = {}

        extra_key = dict(original)
        extra_key["unexpected"] = True
        cases["Invalid installer-owned"] = extra_key
        wrong_root = dict(original)
        wrong_root["target_root"] = str(self.root / "other-install")
        cases["managed root"] = wrong_root
        noncanonical_path = dict(original)
        noncanonical_directory = self.script_directory / "nested" / ".."
        noncanonical_path["script_directory"] = str(noncanonical_directory)
        noncanonical_path["script_path"] = str(
            noncanonical_directory / installer.PLUGIN_SCRIPT_NAME
        )
        cases["invalid path"] = noncanonical_path
        bad_hash = dict(original)
        bad_hash["script_sha256"] = "invalid"
        cases["invalid script digest"] = bad_hash

        for expected_error, data in cases.items():
            with self.subTest(case=expected_error):
                state_path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, expected_error):
                    installer.build_uninstall_plan(
                        self.install_root, self.script_directory
                    )
                self.assertTrue(
                    (self.script_directory / installer.PLUGIN_SCRIPT_NAME).is_file()
                )
        state_path.write_text(json.dumps(original), encoding="utf-8")

    def test_owned_legacy_script_is_transactional_but_foreign_is_preserved(self) -> None:
        self.script_directory.mkdir()
        legacy = self.script_directory / installer.LEGACY_PLUGIN_SCRIPT_NAME
        legacy.write_text(self._legacy_script_content(), encoding="utf-8")
        self.assertEqual(self._run(), 0)
        self.assertFalse(legacy.exists())

        self.assertEqual(self._run("--uninstall"), 0)
        legacy.write_text(
            self._legacy_script_content(self.root / "different-root"),
            encoding="utf-8",
        )
        self.assertEqual(self._run(), 0)
        self.assertTrue(legacy.is_file())
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertTrue(legacy.is_file())

    def _pre_manifest_install(self, script_root: Path | None = None) -> Path:
        """Lay out what preview builds before 0.1.0 installed: runtime files and a rendered Lua
        script, with no manifest or install state."""
        self.install_root.mkdir(parents=True)
        for name in installer.PRE_MANIFEST_ROOT_FILE_NAMES:
            (self.install_root / name).write_bytes(b"old preview build")
        (self.install_root / "settings.json").write_text("keep me\n", encoding="utf-8")
        root = script_root or self.install_root
        self.script_directory.mkdir(parents=True)
        script = self.script_directory / installer.PLUGIN_SCRIPT_NAME
        script.write_text(
            "-- Track Visualizer preview build\n"
            f"local INSTALL_ROOT = [[{root}]]\n"
            f"local ENGINE_EXECUTABLE = [[{root / installer.ENGINE_NAME}]]\n"
            f"local RUNNER_EXECUTABLE = [[{root / installer.RUNNER_NAME}]]\n"
            f"local FFMPEG_EXECUTABLE = [[{root / installer.FFMPEG_NAME}]]\n"
            f"local FFPROBE_EXECUTABLE = [[{root / installer.FFPROBE_NAME}]]\n",
            encoding="utf-8",
        )
        return script

    def test_pre_manifest_preview_install_is_upgraded_in_place(self) -> None:
        script = self._pre_manifest_install()

        self.assertEqual(self._run("--dry-run"), 0)
        self.assertEqual((self.install_root / installer.ENGINE_NAME).read_bytes(), b"old preview build")

        self.assertEqual(self._run(), 0)
        self.assertEqual((self.install_root / installer.ENGINE_NAME).read_bytes(), b"packaged")
        self.assertEqual((self.install_root / installer.FFMPEG_NAME).read_bytes(), b"packaged")
        self.assertIn("-- v1", script.read_text(encoding="utf-8"))
        self.assertTrue((self.install_root / installer.MANIFEST_NAME).is_file())
        self.assertTrue((self.install_root / installer.INSTALL_STATE_NAME).is_file())
        self.assertEqual(
            (self.install_root / "settings.json").read_text(encoding="utf-8"), "keep me\n"
        )
        # The upgraded install is now owned, so a later upgrade and uninstall work normally.
        self._rewrite_payload("v2")
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertFalse(script.exists())
        self.assertTrue((self.install_root / "settings.json").is_file())

    def test_pre_manifest_runtime_without_matching_script_stays_fail_closed(self) -> None:
        script = self._pre_manifest_install(self.root / "another-root")
        with self.assertRaisesRegex(RuntimeError, "without a valid owned"):
            self._run()
        script.unlink()
        with self.assertRaisesRegex(RuntimeError, "without a valid owned"):
            self._run()
        self.assertEqual((self.install_root / installer.ENGINE_NAME).read_bytes(), b"old preview build")

    def test_pre_manifest_upgrade_requires_only_files_preview_builds_wrote(self) -> None:
        self._pre_manifest_install()
        (self.install_root / installer.NOTICE_NAME).write_text("notices\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "without a valid owned"):
            self._run()
        self.assertEqual((self.install_root / installer.ENGINE_NAME).read_bytes(), b"old preview build")

    def test_owned_legacy_only_install_is_removed_by_uninstall(self) -> None:
        self.script_directory.mkdir()
        legacy = self.script_directory / installer.LEGACY_PLUGIN_SCRIPT_NAME
        legacy.write_text(self._legacy_script_content(), encoding="utf-8")
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertFalse(legacy.exists())

    def test_committed_legacy_cleanup_recovers_after_target_and_backup_are_gone(self) -> None:
        self.script_directory.mkdir()
        legacy = self.script_directory / installer.LEGACY_PLUGIN_SCRIPT_NAME
        legacy.write_text(self._legacy_script_content(), encoding="utf-8")
        plan = installer.build_uninstall_plan(self.install_root, self.script_directory)
        journal = self.install_root / installer.TRANSACTION_JOURNAL_NAME
        real_unlink = installer._unlink_with_retries

        def retain_journal(
            path: Path, expected_identity: installer._PathIdentity
        ) -> None:
            if path == journal:
                raise PermissionError("journal is locked")
            real_unlink(path, expected_identity)

        with (
            patch.object(installer, "_unlink_with_retries", side_effect=retain_journal),
            self.assertRaisesRegex(RuntimeError, "cleanup is incomplete"),
        ):
            installer.uninstall_from_plan(plan, self.install_root, self.script_directory)
        self.assertFalse(legacy.exists())
        self.assertEqual(list(self.script_directory.glob(".*.tviz-backup-*.tmp")), [])
        installer._recover_stale_transaction(self.install_root, self.script_directory)
        self.assertFalse(journal.exists())

    def test_manifest_is_staged_before_license_operations_are_journaled(self) -> None:
        license_path = self.source / "licenses" / "New" / "NOTICE.txt"
        license_path.parent.mkdir(parents=True)
        license_path.write_text("new license\n", encoding="utf-8")
        self._write_manifest()
        snapshots: list[dict[str, object]] = []
        real_write_journal = installer._write_journal

        def capture_journal(path: Path, data: dict[str, object]) -> None:
            real_write_journal(path, data)
            snapshots.append(json.loads(json.dumps(data)))

        with patch.object(installer, "_write_journal", side_effect=capture_journal):
            self.assertEqual(self._run(), 0)

        license_target = self.install_root / "licenses" / "New" / "NOTICE.txt"
        first_license_snapshot = next(
            index
            for index, snapshot in enumerate(snapshots)
            if any(
                Path(str(operation["target"])) == license_target
                for operation in snapshot["operations"]
            )
        )
        self.assertGreater(first_license_snapshot, 0)
        self.assertFalse(
            any(
                Path(str(operation["target"])) == license_target
                for snapshot in snapshots[:first_license_snapshot]
                for operation in snapshot["operations"]
            )
        )
        manifest_operation = next(
            operation
            for operation in snapshots[first_license_snapshot]["operations"]
            if Path(str(operation["target"]))
            == self.install_root / installer.MANIFEST_NAME
        )
        self.assertEqual(manifest_operation["state"], "staged")
        self.assertIsNotNone(manifest_operation["staged_identity"])

    def test_artifacts_are_published_before_state_and_target_mutation(self) -> None:
        source = self.root / "new.bin"
        target = self.root / "destination" / "runtime.bin"
        source.write_bytes(b"new")
        target.parent.mkdir()
        target.write_bytes(b"old")
        events: list[str] = []
        real_publish = installer._publish_artifact
        real_write_journal = installer._write_journal
        real_safe_replace = installer._safe_replace

        def observe_publish(path: Path, identity: installer._PathIdentity) -> None:
            events.append("publish:backup" if ".tviz-backup-" in path.name else "publish:new")
            real_publish(path, identity)

        def observe_journal(path: Path, data: dict[str, object]) -> None:
            real_write_journal(path, data)
            operation = data["operations"][0]
            state = str(operation["state"])
            if state in {"staged", "ready"}:
                events.append(f"state:{state}")

        def observe_replace(source_path: Path, target_path: Path, **values: object) -> None:
            if target_path == target and ".tviz-new-" in source_path.name:
                events.append("mutate:target")
            real_safe_replace(source_path, target_path, **values)

        with (
            patch.object(installer, "_publish_artifact", side_effect=observe_publish),
            patch.object(installer, "_write_journal", side_effect=observe_journal),
            patch.object(installer, "_safe_replace", side_effect=observe_replace),
        ):
            installer.copy_required_file(source, target)
        self.assertLess(events.index("publish:new"), events.index("state:staged"))
        self.assertLess(events.index("publish:backup"), events.index("state:ready"))
        self.assertLess(events.index("state:ready"), events.index("mutate:target"))

    def test_windows_process_wait_timeout_is_explicit_and_bounded(self) -> None:
        calls: list[tuple[object, int]] = []

        def timeout(handle: object, milliseconds: int) -> int:
            calls.append((handle, milliseconds))
            return 0x00000102

        with self.assertRaisesRegex(RuntimeError, "Timed out waiting"):
            installer._wait_for_windows_process_exit(timeout, "handle", 42)
        self.assertEqual(calls, [("handle", 5000)])

    def test_fresh_install_rejects_existing_unowned_license_destination(self) -> None:
        packaged = self.source / "licenses" / "New" / "NOTICE.txt"
        packaged.parent.mkdir(parents=True)
        packaged.write_text("packaged\n", encoding="utf-8")
        self._write_manifest()
        existing = self.install_root / "licenses" / "New" / "NOTICE.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("user file\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "unowned existing license"):
            installer.build_install_plan(
                self.source,
                self.install_root,
                self.script_directory,
                language="en",
            )
        self.assertEqual(existing.read_text(encoding="utf-8"), "user file\n")

    def test_upgrade_rejects_collision_at_newly_introduced_license_path(self) -> None:
        self.assertEqual(self._run(), 0)
        existing = self.install_root / "licenses" / "New" / "NOTICE.txt"
        existing.parent.mkdir(parents=True)
        existing.write_text("user file\n", encoding="utf-8")
        packaged = self.source / "licenses" / "New" / "NOTICE.txt"
        packaged.parent.mkdir(parents=True)
        packaged.write_text("packaged\n", encoding="utf-8")
        self._write_manifest("2.0")

        with self.assertRaisesRegex(RuntimeError, "unowned existing license"):
            installer.build_install_plan(
                self.source,
                self.install_root,
                self.script_directory,
                language="en",
            )
        self.assertEqual(existing.read_text(encoding="utf-8"), "user file\n")

    def test_successful_upgrade_prunes_only_manifest_owned_stale_licenses(self) -> None:
        old_license = self.source / "licenses" / "Old" / "NOTICE.txt"
        old_license.parent.mkdir(parents=True)
        old_license.write_text("old\n", encoding="utf-8")
        modified_license = self.source / "licenses" / "Modified" / "NOTICE.txt"
        modified_license.parent.mkdir(parents=True)
        modified_license.write_text("packaged then changed\n", encoding="utf-8")
        self._write_manifest("1.0")
        self.assertEqual(self._run(), 0)
        unknown = self.install_root / "licenses" / "user" / "UNKNOWN.txt"
        unknown.parent.mkdir(parents=True)
        unknown.write_text("preserve\n", encoding="utf-8")
        installed_modified = self.install_root / "licenses" / "Modified" / "NOTICE.txt"
        installed_modified.write_text("user-modified\n", encoding="utf-8")

        old_license.unlink()
        old_license.parent.rmdir()
        modified_license.unlink()
        modified_license.parent.rmdir()
        new_license = self.source / "licenses" / "New" / "NOTICE.txt"
        new_license.parent.mkdir(parents=True)
        new_license.write_text("new\n", encoding="utf-8")
        self._write_manifest("2.0")
        self.assertEqual(self._run(), 0)

        self.assertFalse((self.install_root / "licenses" / "Old").exists())
        self.assertEqual(
            (self.install_root / "licenses" / "New" / "NOTICE.txt").read_text(
                encoding="utf-8"
            ),
            "new\n",
        )
        self.assertEqual(unknown.read_text(encoding="utf-8"), "preserve\n")
        self.assertEqual(installed_modified.read_text(encoding="utf-8"), "user-modified\n")

    def test_uninstall_preserves_user_data_unknown_files_and_is_idempotent(self) -> None:
        managed_license = self.source / "licenses" / "Pillow" / "nested" / "LICENSE"
        managed_license.parent.mkdir(parents=True)
        managed_license.write_text("managed\n", encoding="utf-8")
        self._write_manifest()
        self.assertEqual(self._run(), 0)
        preserved_files = {
            self.install_root / "settings.json": "settings\n",
            self.install_root / "outputs" / "mix.mp4": "output\n",
            self.install_root / "tasks" / "pending.json": "task\n",
            self.install_root / "tmp" / "working.txt": "temporary user data\n",
            self.install_root / "logs" / "engine.log": "log\n",
            self.install_root / "custom.dat": "unknown\n",
            self.install_root / "licenses" / "custom" / "USER.txt": "user license\n",
            self.script_directory / "Another Utility.lua": "other script\n",
        }
        for path, content in preserved_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        with (
            patch.object(installer, "resource_root", return_value=self.source),
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(installer.main(self._arguments("--uninstall")), 0)
            self.assertEqual(installer.main(self._arguments("--uninstall")), 0)

        stop_processes.assert_called_once_with(self.install_root.absolute())
        self.assertEqual(unregister.call_count, 2)
        unregister.assert_called_with(self.install_root.absolute())
        for name in installer.MANAGED_ROOT_FILE_NAMES:
            self.assertFalse((self.install_root / name).exists(), name)
        self.assertFalse((self.install_root / "licenses" / "Pillow").exists())
        self.assertFalse((self.script_directory / installer.PLUGIN_SCRIPT_NAME).exists())
        for path, content in preserved_files.items():
            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_uninstall_removes_only_an_empty_tmp_directory(self) -> None:
        self.assertEqual(self._run(), 0)
        temporary_directory = self.install_root / "tmp"
        self.assertTrue(temporary_directory.is_dir())
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertFalse(temporary_directory.exists())
        self.assertFalse(self.install_root.exists())

        self.assertEqual(self._run(), 0)
        preserved = self.install_root / "tmp" / "user-work.json"
        preserved.write_text("preserve\n", encoding="utf-8")
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertEqual(preserved.read_text(encoding="utf-8"), "preserve\n")
        self.assertTrue(self.install_root.is_dir())

    def test_absent_uninstall_prunes_known_empty_directories_only(self) -> None:
        (self.install_root / "licenses").mkdir(parents=True)
        (self.install_root / "tmp").mkdir()
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertFalse(self.install_root.exists())

        user_license = self.install_root / "licenses" / "user" / "NOTICE.txt"
        user_license.parent.mkdir(parents=True)
        user_license.write_text("preserve\n", encoding="utf-8")
        (self.install_root / "tmp").mkdir()
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertEqual(user_license.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse((self.install_root / "tmp").exists())
        self.assertTrue(self.install_root.is_dir())

    def test_absent_uninstall_retry_prunes_nested_empty_license_directories(self) -> None:
        packaged_license = (
            self.source / "licenses" / "Package" / "metadata" / "LICENSE.txt"
        )
        packaged_license.parent.mkdir(parents=True)
        packaged_license.write_text("managed\n", encoding="utf-8")
        self._write_manifest()
        self.assertEqual(self._run(), 0)
        installed_license = (
            self.install_root / "licenses" / "Package" / "metadata" / "LICENSE.txt"
        )
        self.assertTrue(installed_license.is_file())

        with (
            patch.object(
                installer,
                "_prune_license_directories",
                side_effect=OSError("simulated post-commit interruption"),
            ),
            self.assertRaisesRegex(OSError, "post-commit interruption"),
        ):
            self._run("--uninstall")

        self.assertFalse(installed_license.exists())
        self.assertTrue(installed_license.parent.is_dir())
        self.assertFalse(
            (self.install_root / installer.TRANSACTION_JOURNAL_NAME).exists()
        )
        self.assertEqual(self._run("--uninstall"), 0)
        self.assertFalse(self.install_root.exists())

    def test_absent_uninstall_preserves_files_and_nonempty_license_directories(self) -> None:
        empty_leaf = self.install_root / "licenses" / "empty" / "nested"
        empty_leaf.mkdir(parents=True)
        preserved_files = {
            self.install_root / "licenses" / "custom" / "NOTICE.txt": b"notice",
            self.install_root / "licenses" / "vendor" / "deep" / "LICENSE": b"",
            self.install_root / "tmp" / "user-work.json": b"work",
        }
        for path, content in preserved_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        self.assertEqual(self._run("--uninstall"), 0)

        self.assertFalse(empty_leaf.exists())
        self.assertFalse((self.install_root / "licenses" / "empty").exists())
        for path, content in preserved_files.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue((self.install_root / "licenses" / "custom").is_dir())
        self.assertTrue((self.install_root / "licenses" / "vendor").is_dir())
        self.assertTrue(self.install_root.is_dir())

    def test_uninstall_requires_owned_manifest_but_absent_install_is_idempotent(self) -> None:
        self.install_root.mkdir()
        settings = self.install_root / "settings.json"
        settings.write_text("preserve\n", encoding="utf-8")
        with (
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(installer.main(self._arguments("--uninstall")), 0)
        self.assertEqual(settings.read_text(encoding="utf-8"), "preserve\n")
        stop_processes.assert_not_called()
        unregister.assert_called_once_with(self.install_root.absolute())

        partial = self.install_root / installer.ENGINE_NAME
        partial.write_bytes(b"not owned")
        with (
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "without a valid owned"),
        ):
            installer.main(self._arguments("--uninstall", "--dry-run"))
        self.assertEqual(partial.read_bytes(), b"not owned")
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_uninstall_rejects_foreign_malformed_and_unsafe_manifests(self) -> None:
        self.install_root.mkdir()
        manifest_path = self.install_root / installer.MANIFEST_NAME
        cases: list[tuple[str, str]] = []
        foreign = self._manifest_data()
        foreign["product"] = "OtherProduct"
        cases.append(("foreign", json.dumps(foreign)))
        cases.append(("malformed", "not json"))
        unsafe = self._manifest_data()
        files = list(unsafe["files"])
        files.append(
            {
                "path": "licenses/D:/victim.txt",
                "size": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
                "mode": "0644",
            }
        )
        unsafe["files"] = files
        cases.append(("unsafe", json.dumps(unsafe)))

        for name, content in cases:
            with self.subTest(case=name):
                manifest_path.write_text(content, encoding="utf-8")
                with (
                    patch.object(installer, "stop_existing_processes") as stop_processes,
                    patch.object(installer, "unregister_runner_autostart") as unregister,
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaises((ValueError, RuntimeError)),
                ):
                    installer.main(self._arguments("--uninstall", "--dry-run"))
                self.assertEqual(manifest_path.read_text(encoding="utf-8"), content)
                stop_processes.assert_not_called()
                unregister.assert_not_called()

    def test_uninstall_dry_run_rejects_symlinked_managed_file(self) -> None:
        self.assertEqual(self._run(), 0)
        outside = self.root / "outside-engine"
        outside.write_bytes(b"outside")
        engine = self.install_root / installer.ENGINE_NAME
        engine.unlink()
        self._create_file_symlink(outside, engine)

        with (
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "link or junction"),
        ):
            installer.main(self._arguments("--uninstall", "--dry-run"))
        self.assertEqual(outside.read_bytes(), b"outside")
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_process_and_registry_scope_are_exactly_target_root_aware(self) -> None:
        selected_root = Path(r"C:\Users\test\Selected Install")
        other_root = Path(r"C:\Users\test\Other Install")
        with (
            patch.object(installer.os, "name", "nt"),
            patch.object(installer, "_windows_process_ids", return_value=(11, 22)) as process_ids,
            patch.object(
                installer, "_terminate_windows_process_if_managed", return_value=False
            ) as terminate,
        ):
            installer.stop_existing_processes(selected_root)
        process_ids.assert_called_once_with()
        expected_paths = {
            installer._normalized_windows_path(selected_root / name)
            for name in (
                installer.ENGINE_NAME,
                installer.RUNNER_NAME,
                installer.FFMPEG_NAME,
                installer.FFPROBE_NAME,
            )
        }
        self.assertEqual(terminate.call_count, 2)
        for call in terminate.call_args_list:
            self.assertEqual(call.args[1], expected_paths)
        self.assertNotIn(
            installer._normalized_windows_path(other_root / installer.ENGINE_NAME),
            expected_paths,
        )
        self.assertTrue(
            installer._is_managed_windows_executable(
                selected_root / installer.ENGINE_NAME, expected_paths
            )
        )
        self.assertFalse(
            installer._is_managed_windows_executable(
                other_root / installer.ENGINE_NAME, expected_paths
            )
        )

        deleted_values: list[str] = []

        class FakeKey:
            def __enter__(self) -> FakeKey:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_winreg(command: str) -> SimpleNamespace:
            return SimpleNamespace(
                HKEY_CURRENT_USER=object(),
                KEY_QUERY_VALUE=1,
                KEY_SET_VALUE=2,
                OpenKey=lambda *args: FakeKey(),
                QueryValueEx=lambda *args: (command, 1),
                DeleteValue=lambda key, name: deleted_values.append(name),
            )

        own_command = f'"{selected_root / installer.RUNNER_NAME}" --background'
        with (
            patch.object(installer.os, "name", "nt"),
            patch.dict(sys.modules, {"winreg": fake_winreg(own_command)}),
        ):
            installer.unregister_runner_autostart(selected_root)
        self.assertEqual(deleted_values, [installer.RUN_KEY_NAME])

        deleted_values.clear()
        other_command = f'"{other_root / installer.RUNNER_NAME}" --background'
        with (
            patch.object(installer.os, "name", "nt"),
            patch.dict(sys.modules, {"winreg": fake_winreg(other_command)}),
        ):
            installer.unregister_runner_autostart(selected_root)
        self.assertEqual(deleted_values, [])

    def test_custom_root_cannot_remove_another_roots_script_or_runtime(self) -> None:
        self.assertEqual(self._run(), 0)
        other_root = self.root / "other-install"
        other_root.mkdir()
        other_settings = other_root / "settings.json"
        other_settings.write_text("other\n", encoding="utf-8")
        arguments = [
            "--uninstall",
            "--dry-run",
            "--no-pause",
            "--install-root",
            str(other_root),
            "--resolve-script-dir",
            str(self.script_directory),
        ]
        with (
            patch.object(installer, "stop_existing_processes") as stop_processes,
            patch.object(installer, "unregister_runner_autostart") as unregister,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(installer.main(arguments), 0)
        self.assertTrue((self.install_root / installer.ENGINE_NAME).is_file())
        self.assertTrue((self.script_directory / installer.PLUGIN_SCRIPT_NAME).is_file())
        self.assertEqual(other_settings.read_text(encoding="utf-8"), "other\n")
        stop_processes.assert_not_called()
        unregister.assert_not_called()

    def test_copy_transaction_preserves_old_target_when_staging_fails(self) -> None:
        source = self.root / "new.bin"
        target = self.root / "destination" / "runtime.bin"
        source.write_bytes(b"new")
        target.parent.mkdir()
        target.write_bytes(b"old")

        with (
            patch.object(installer, "_prepare_change", side_effect=OSError("copy failed")),
            self.assertRaisesRegex(OSError, "copy failed"),
        ):
            installer.copy_required_file(source, target)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(target.parent.glob(f".{target.name}.tviz-*.tmp")), [])

    def test_copy_transaction_atomically_replaces_existing_target(self) -> None:
        source = self.root / "new.bin"
        target = self.root / "destination" / "runtime.bin"
        source.write_bytes(b"new")
        target.parent.mkdir()
        target.write_bytes(b"old")
        real_replace = installer._replace_path
        observed_old_content: list[bytes] = []

        def observe_replace(
            staged: str | os.PathLike[str], destination: str | os.PathLike[str]
        ) -> None:
            staged_path = Path(staged)
            destination_path = Path(destination)
            if destination_path == target and ".tviz-new-" in staged_path.name:
                observed_old_content.append(destination_path.read_bytes())
            real_replace(staged_path, destination_path)

        with patch.object(installer, "_replace_path", side_effect=observe_replace):
            self.assertEqual(installer.copy_required_file(source, target), target)
        self.assertEqual(observed_old_content, [b"old"])
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(list(target.parent.glob(f".{target.name}.tviz-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
