from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _creationflags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _write_done(path: str | None, returncode: int, error: str = "") -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps({"returncode": returncode, "error": error}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _append_output(path: str | None, text: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text)


def _run_command(config: dict[str, Any]) -> int:
    command = config.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError("Runner config has no command list")
    command = [str(part) for part in command]
    stdout_path = config.get("stdout_path")
    env = os.environ.copy()
    configured_env = config.get("env") or {}
    if not isinstance(configured_env, dict):
        raise ValueError("Runner config env must be an object")
    for key, value in configured_env.items():
        env[str(key)] = str(value)
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    cwd = str(config.get("cwd") or os.getcwd())

    with subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creationflags(),
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            _append_output(stdout_path, line)
        return process.wait()


def _open_file(config: dict[str, Any]) -> int:
    path = str(config.get("path") or "")
    if not path:
        raise ValueError("Runner config has no path to open")
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(
            ["open", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        subprocess.Popen(
            ["xdg-open", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return 0


def _execute_config(config: dict[str, Any]) -> int:
    mode = str(config.get("mode") or "run")
    if mode == "open":
        return _open_file(config)
    if mode != "run":
        raise ValueError(f"Unsupported runner mode: {mode}")
    return _run_command(config)


def _process_config(config: dict[str, Any]) -> int:
    done_path = config.get("done_path")
    try:
        code = _execute_config(config)
        _write_done(done_path, code)
        return code
    except Exception as exc:
        _append_output(config.get("stdout_path"), f"ERROR: {exc}\n")
        _write_done(done_path, 1, str(exc))
        return 1


def process_task_file(task_path: str | Path) -> int | None:
    task = Path(task_path)
    running = task.with_name(f"{task.name}.running.{os.getpid()}")
    try:
        task.rename(running)
    except (FileNotFoundError, FileExistsError, PermissionError):
        return None

    try:
        try:
            config = json.loads(running.read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict):
                raise ValueError("Runner config must be a JSON object")
        except Exception:
            return 1
        return _process_config(config)
    finally:
        running.unlink(missing_ok=True)


def _task_sort_key(path: Path) -> tuple[int, str]:
    try:
        modified = path.stat().st_mtime_ns
    except OSError:
        modified = 0
    return modified, path.name


def run_pending_launches(root: str | Path) -> int:
    install_root = Path(root)
    queue_dir = install_root / "tmp"
    queue_dir.mkdir(parents=True, exist_ok=True)
    for task_path in sorted(queue_dir.glob("runner_launch_*.json"), key=_task_sort_key):
        process_task_file(task_path)
    return 0


def run_daemon(root: str | Path, poll_interval: float = 0.25) -> int:
    install_root = Path(root)
    tasks_dir = install_root / "tasks"
    tmp_dir = install_root / "tmp"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    heartbeat = tmp_dir / "runner_heartbeat.txt"
    while True:
        heartbeat.write_text(str(int(time.time())), encoding="ascii")
        queued = list(tasks_dir.glob("*.json")) + list(tmp_dir.glob("runner_launch_*.json"))
        for task_path in sorted(queued, key=_task_sort_key):
            process_task_file(task_path)
        time.sleep(poll_interval)


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return run_pending_launches(_application_root())
    if args[0] == "--daemon":
        if len(args) != 2:
            raise SystemExit("Usage: TrackVisualizerRunner --daemon <install-root>")
        return run_daemon(args[1])
    if len(args) != 1:
        raise SystemExit("Usage: TrackVisualizerRunner [<config.json>]")
    config_path = Path(args[0])
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("Runner config must be a JSON object")
    return _process_config(config)


if __name__ == "__main__":
    raise SystemExit(main())
