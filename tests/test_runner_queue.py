from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import runner_entry


class RunnerQueueTests(unittest.TestCase):
    def _task(self, root: Path, name: str, marker: str, output: Path, done: Path) -> Path:
        task = root / "tmp" / f"runner_launch_{name}.json"
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text(
            json.dumps(
                {
                    "mode": "run",
                    "cwd": str(root),
                    "command": [sys.executable, "-c", f"print({marker!r})"],
                    "stdout_path": str(output),
                    "done_path": str(done),
                }
            ),
            encoding="utf-8",
        )
        return task

    def test_no_argument_queue_processes_tasks_in_timestamp_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            output = root / "runner.log"
            first_done = root / "first.done.json"
            second_done = root / "second.done.json"
            first = self._task(root, "first", "first", output, first_done)
            second = self._task(root, "second", "second", output, second_done)
            os.utime(first, (100, 100))
            os.utime(second, (200, 200))

            with patch.object(runner_entry, "_application_root", return_value=root):
                self.assertEqual(runner_entry.main([]), 0)

            self.assertEqual(output.read_text(encoding="utf-8").splitlines(), ["first", "second"])
            self.assertEqual(json.loads(first_done.read_text(encoding="utf-8"))["returncode"], 0)
            self.assertEqual(json.loads(second_done.read_text(encoding="utf-8"))["returncode"], 0)
            self.assertEqual(list((root / "tmp").glob("runner_launch_*.json*")), [])

    def test_failed_task_writes_error_and_does_not_block_later_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            output = root / "runner.log"
            failed_done = root / "failed.done.json"
            good_done = root / "good.done.json"
            failed = root / "tmp" / "runner_launch_01_failed.json"
            failed.parent.mkdir(parents=True)
            failed.write_text(
                json.dumps(
                    {
                        "mode": "run",
                        "command": [],
                        "stdout_path": str(output),
                        "done_path": str(failed_done),
                    }
                ),
                encoding="utf-8",
            )
            self._task(root, "02_good", "good", output, good_done)

            self.assertEqual(runner_entry.run_pending_launches(root), 0)

            failed_result = json.loads(failed_done.read_text(encoding="utf-8"))
            self.assertEqual(failed_result["returncode"], 1)
            self.assertIn("no command list", failed_result["error"])
            self.assertEqual(json.loads(good_done.read_text(encoding="utf-8"))["returncode"], 0)

    def test_queue_contract_handles_unicode_profile_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "profile-Пример-音楽"
            output = root / "вывод" / "runner.log"
            done = root / "готово" / "result.json"
            self._task(root, "unicode", "unicode-ok", output, done)

            self.assertEqual(runner_entry.run_pending_launches(root), 0)

            self.assertEqual(output.read_text(encoding="utf-8").strip(), "unicode-ok")
            self.assertEqual(json.loads(done.read_text(encoding="utf-8"))["returncode"], 0)
            self.assertEqual(list((root / "tmp").glob("runner_launch_*.json*")), [])

    def test_platform_open_commands(self) -> None:
        with patch.object(runner_entry.sys, "platform", "darwin"), patch.object(
            runner_entry.subprocess, "Popen"
        ) as popen:
            self.assertEqual(runner_entry._open_file({"path": "/tmp/preview.png"}), 0)
            self.assertEqual(popen.call_args.args[0], ["open", "/tmp/preview.png"])

        with patch.object(runner_entry.sys, "platform", "linux"), patch.object(
            runner_entry.subprocess, "Popen"
        ) as popen:
            self.assertEqual(runner_entry._open_file({"path": "/tmp/preview.png"}), 0)
            self.assertEqual(popen.call_args.args[0], ["xdg-open", "/tmp/preview.png"])


if __name__ == "__main__":
    unittest.main()
