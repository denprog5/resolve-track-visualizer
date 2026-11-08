from __future__ import annotations

import argparse
import errno
import hashlib
import json
import locale
import ntpath
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from davinci_track_visualizer.platform_paths import (
    executable_name,
    install_root as default_install_root,
    resolve_scripts_dir as default_resolve_scripts_dir,
)


PLUGIN_SCRIPT_NAME = "Track Visualizer.lua"
LEGACY_PLUGIN_SCRIPT_NAME = "Track Visualizer.py"
ENGINE_NAME = executable_name("TrackVisualizerEngine")
RUNNER_NAME = executable_name("TrackVisualizerRunner")
FFMPEG_NAME = executable_name("ffmpeg")
FFPROBE_NAME = executable_name("ffprobe")
LOGO_NAME = "aplus.png"
RUN_KEY_NAME = "DavinciTrackVisualizerRunner"
BIN_DIRECTORY = "bin"
RESOURCE_DIRECTORY = "resources"
NOTICE_NAME = "THIRD_PARTY_NOTICES.txt"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "davinci-track-visualizer.release.v1"
MANIFEST_PRODUCT = "DavinciTrackVisualizer"
INSTALL_STATE_NAME = "install-state.json"
INSTALL_STATE_SCHEMA = "davinci-track-visualizer.install-state.v1"
TRANSACTION_JOURNAL_NAME = ".tviz-transaction.json"
TRANSACTION_SCHEMA = "davinci-track-visualizer.transaction.v1"
DEFAULT_LANGUAGE = "en"
AUTO_LANGUAGE = "auto"
SUPPORTED_LANGUAGES = ("en", "ru")
LANGUAGE_OVERRIDE_ENV = "TVIZ_UI_LANG"

MESSAGE_CATALOGS = {
    "en": {
        "argparse_description": (
            "Install or uninstall DaVinci Track Visualizer for the current user"
        ),
        "argparse_error": "error",
        "argparse_error_expected_value": "argument {argument}: expected one value",
        "argparse_error_invalid_language": (
            "invalid value {value!r}; choose auto, en, or ru"
        ),
        "argparse_error_unrecognized": "unrecognized arguments: {arguments}",
        "argparse_options": "options",
        "argparse_usage": "usage",
        "dry_run_complete": (
            "Dry run complete: manifest, payload hashes, and destinations are valid; "
            "no files were changed."
        ),
        "dry_run_uninstall_complete": (
            "Dry run complete: uninstall selected; {files} managed files would be "
            "removed; no files were changed."
        ),
        "fatal_error": "ERROR: {error}",
        "help_dry_run": "Validate resources and print destinations only",
        "help_help": "Show this help message and exit",
        "help_install_root": "Override the application installation directory",
        "help_language": (
            "Installer language: auto, en, or ru (default: auto; TVIZ_UI_LANG overrides auto)"
        ),
        "help_no_pause": "Never wait for input before exiting",
        "help_resolve_script_dir": "Override the Resolve Utility scripts directory",
        "help_result_file": "Write the outcome as JSON to this file (used by self-update)",
        "help_uninstall": "Uninstall instead of install",
        "install_application_directory": "Application directory: {path}",
        "install_complete": "Installation complete.",
        "install_file": "{component}: {path}",
        "install_resolve_script_directory": "Resolve script directory: {path}",
        "install_start": "Installing DaVinci Track Visualizer...",
        "pause_prompt": "Press Enter to close...",
        "resources_missing": "Installer resources are missing:\n{paths}",
        "restart_resolve": (
            "Restart DaVinci Resolve, then open "
            "Workspace -> Scripts -> Utility -> Track Visualizer."
        ),
        "runner_behavior": (
            "Runner: starts only while rendering/opening files; no background autostart"
        ),
        "stopping_processes": "Stopping previous Track Visualizer processes...",
        "uninstall_complete": "Uninstallation complete.",
        "uninstall_start": "Uninstalling DaVinci Track Visualizer...",
    },
    "ru": {
        "argparse_description": (
            "Установить или удалить DaVinci Track Visualizer для текущего пользователя"
        ),
        "argparse_error": "ошибка",
        "argparse_error_expected_value": (
            "для аргумента {argument} требуется одно значение"
        ),
        "argparse_error_invalid_language": (
            "недопустимое значение {value!r}; выберите auto, en или ru"
        ),
        "argparse_error_unrecognized": "неизвестные аргументы: {arguments}",
        "argparse_options": "параметры",
        "argparse_usage": "использование",
        "dry_run_complete": (
            "Проверка завершена: манифест, хеши файлов и пути назначения корректны; "
            "файлы не изменены."
        ),
        "dry_run_uninstall_complete": (
            "Проверка завершена: выбрано удаление; управляемых файлов к удалению: "
            "{files}; файлы не изменены."
        ),
        "fatal_error": "ОШИБКА: {error}",
        "help_dry_run": "Проверить ресурсы и только вывести пути назначения",
        "help_help": "Показать эту справку и выйти",
        "help_install_root": "Изменить каталог установки приложения",
        "help_language": (
            "Язык установщика: auto, en или ru "
            "(по умолчанию auto; TVIZ_UI_LANG переопределяет auto)"
        ),
        "help_no_pause": "Никогда не ожидать ввода перед выходом",
        "help_resolve_script_dir": "Изменить каталог скриптов Resolve Utility",
        "help_result_file": "Записать результат в этот файл в формате JSON (для автообновления)",
        "help_uninstall": "Удалить программу вместо установки",
        "install_application_directory": "Каталог приложения: {path}",
        "install_complete": "Установка завершена.",
        "install_file": "{component}: {path}",
        "install_resolve_script_directory": "Каталог скриптов Resolve: {path}",
        "install_start": "Установка DaVinci Track Visualizer...",
        "pause_prompt": "Нажмите Enter, чтобы закрыть...",
        "resources_missing": "Отсутствуют ресурсы установщика:\n{paths}",
        "restart_resolve": (
            "Перезапустите DaVinci Resolve, затем откройте "
            "Workspace -> Scripts -> Utility -> Track Visualizer."
        ),
        "runner_behavior": (
            "Runner: запускается только при рендеринге или открытии файлов; "
            "фоновый автозапуск отключен"
        ),
        "stopping_processes": "Остановка ранее запущенных процессов Track Visualizer...",
        "uninstall_complete": "Удаление завершено.",
        "uninstall_start": "Удаление DaVinci Track Visualizer...",
    },
}


def message(key: str, language: str = DEFAULT_LANGUAGE, **values: object) -> str:
    english = MESSAGE_CATALOGS[DEFAULT_LANGUAGE][key]
    template = MESSAGE_CATALOGS.get(language, {}).get(key, english)
    return template.format(**values)


def normalize_locale_name(locale_name: str | None) -> str:
    if not locale_name:
        return DEFAULT_LANGUAGE
    candidates = [candidate.strip() for candidate in locale_name.split(":")]
    candidate = next((candidate for candidate in candidates if candidate), "")
    candidate = candidate.strip("'\"").split(".", 1)[0].split("@", 1)[0]
    primary_language = candidate.replace("_", "-").split("-", 1)[0].casefold()
    if primary_language in {"ru", "russian"}:
        return "ru"
    return DEFAULT_LANGUAGE


def _environment_ui_locale(environ: Mapping[str, str]) -> str | None:
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(variable)
        if value:
            return value
    return None


def _windows_ui_locale() -> str | None:
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_ui_language = kernel32.GetUserDefaultUILanguage
        get_ui_language.argtypes = []
        get_ui_language.restype = ctypes.c_ushort
        return locale.windows_locale.get(int(get_ui_language()))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _macos_ui_locale() -> str | None:
    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "-g", "AppleLanguages"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    quoted_language = re.search(r'"([^"\n]+)"', result.stdout)
    if quoted_language:
        return quoted_language.group(1)
    for line in result.stdout.splitlines():
        candidate = line.strip().rstrip(",").strip("'\"")
        if candidate and candidate not in {"(", ")"}:
            return candidate
    return None


def detect_system_ui_locale(
    *,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    system_name = system or platform.system()
    environment = os.environ if environ is None else environ
    if system_name == "Windows":
        return _windows_ui_locale() or _environment_ui_locale(environment)
    if system_name == "Darwin":
        return _macos_ui_locale() or _environment_ui_locale(environment)
    return _environment_ui_locale(environment)


def resolve_language(
    requested: str = AUTO_LANGUAGE,
    *,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    if requested in SUPPORTED_LANGUAGES:
        return requested
    if requested != AUTO_LANGUAGE:
        raise ValueError(requested)

    environment = os.environ if environ is None else environ
    override = environment.get(LANGUAGE_OVERRIDE_ENV, "").strip()
    if override and override.casefold() != AUTO_LANGUAGE:
        return normalize_locale_name(override)
    return normalize_locale_name(
        detect_system_ui_locale(system=system, environ=environment)
    )


def configure_unicode_console() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except (AttributeError, OSError):
            pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def required_resources(source_dir: Path) -> tuple[Path, ...]:
    return (
        source_dir / BIN_DIRECTORY / ENGINE_NAME,
        source_dir / BIN_DIRECTORY / RUNNER_NAME,
        source_dir / BIN_DIRECTORY / FFMPEG_NAME,
        source_dir / BIN_DIRECTORY / FFPROBE_NAME,
        source_dir / RESOURCE_DIRECTORY / PLUGIN_SCRIPT_NAME,
        source_dir / RESOURCE_DIRECTORY / LOGO_NAME,
        source_dir / NOTICE_NAME,
        source_dir / "LICENSE",
        source_dir / MANIFEST_NAME,
    )


MANAGED_ROOT_FILE_NAMES = (
    ENGINE_NAME,
    RUNNER_NAME,
    FFMPEG_NAME,
    FFPROBE_NAME,
    LOGO_NAME,
    NOTICE_NAME,
    "LICENSE",
    MANIFEST_NAME,
    INSTALL_STATE_NAME,
)
PACKAGED_FIXED_PATHS = {
    f"{BIN_DIRECTORY}/{ENGINE_NAME}",
    f"{BIN_DIRECTORY}/{RUNNER_NAME}",
    f"{BIN_DIRECTORY}/{FFMPEG_NAME}",
    f"{BIN_DIRECTORY}/{FFPROBE_NAME}",
    f"{RESOURCE_DIRECTORY}/{PLUGIN_SCRIPT_NAME}",
    f"{RESOURCE_DIRECTORY}/{LOGO_NAME}",
    NOTICE_NAME,
    "LICENSE",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class ManifestRecord:
    packaged_path: str
    relative_path: Path
    size: int
    sha256: str
    mode: str


@dataclass(frozen=True)
class ValidatedManifest:
    version: str
    records: tuple[ManifestRecord, ...]

    @property
    def license_paths(self) -> tuple[Path, ...]:
        return tuple(
            record.relative_path.relative_to("licenses")
            for record in self.records
            if record.relative_path.parts[0] == "licenses"
        )

    @property
    def license_records(self) -> tuple[ManifestRecord, ...]:
        return tuple(
            record for record in self.records if record.relative_path.parts[0] == "licenses"
        )


@dataclass(frozen=True)
class ValidatedInstallState:
    target_root: Path
    script_directory: Path
    script_path: Path
    script_size: int
    script_sha256: str


@dataclass(frozen=True)
class FileChange:
    target: Path
    source: Path | None = None
    content: bytes | None = None
    executable: bool = False
    label: str = ""
    commit_marker: bool = False
    expected_size: int | None = None
    expected_sha256: str | None = None
    expected_original_identity: _PathIdentity | None = None
    expected_original_size: int | None = None
    expected_original_sha256: str | None = None
    expected_original_absent: bool = False


@dataclass(frozen=True)
class FileDeletion:
    target: Path
    expected_size: int
    expected_sha256: str
    expected_identity: _PathIdentity


@dataclass(frozen=True)
class InstallPlan:
    manifest: ValidatedManifest
    changes: tuple[FileChange, ...]
    deletions: tuple[FileDeletion, ...]
    stale_license_paths: tuple[Path, ...]
    required_directories: tuple[Path, ...]
    script_directories: tuple[Path, ...]


@dataclass(frozen=True)
class UninstallPlan:
    deletions: tuple[FileDeletion, ...]
    license_paths: tuple[Path, ...]
    script_directories: tuple[Path, ...] = ()
    absent: bool = False

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(deletion.target for deletion in self.deletions)


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _safe_manifest_relative_path(value: object) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"Unsafe manifest path: {value!r}")
    if "\\" in value or ":" in value or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError(f"Unsafe manifest path: {value!r}")

    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Unsafe manifest path: {value!r}")
    for part in parts:
        if part.endswith((" ", ".")) or any(character in '<>"|?*' for character in part):
            raise ValueError(f"Unsafe manifest path: {value!r}")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Unsafe manifest path: {value!r}")
    return value, Path(*parts)


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        attributes = 0
    if attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _path_components(path: Path, boundary: Path | None = None) -> tuple[Path, ...]:
    if boundary is None:
        return (*reversed(path.parents), path)
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise RuntimeError(f"Path escapes its managed root: {path}") from exc
    components = [boundary]
    current = boundary
    for part in relative.parts:
        current /= part
        components.append(current)
    return tuple(components)


def _assert_no_links(path: Path, *, boundary: Path | None = None) -> None:
    components = _path_components(path, boundary)
    for index, component in enumerate(components):
        if not _path_exists(component):
            continue
        if _is_link_or_junction(component):
            raise RuntimeError(f"Refusing to follow a link or junction: {component}")
        if index < len(components) - 1 and not component.is_dir():
            raise RuntimeError(f"Managed path parent is not a directory: {component}")


def _assert_safe_file(path: Path, *, boundary: Path | None = None) -> None:
    _assert_no_links(path, boundary=boundary)
    if _path_exists(path) and not path.is_file():
        raise RuntimeError(f"Managed file path is not a regular file: {path}")


def _assert_safe_directory(path: Path, *, boundary: Path | None = None) -> None:
    _assert_no_links(path, boundary=boundary)
    if _path_exists(path) and not path.is_dir():
        raise RuntimeError(f"Managed directory path is not a directory: {path}")


@dataclass(frozen=True)
class _PathIdentity:
    device: int
    inode: int
    file_type: int


_DirectorySnapshot = tuple[tuple[Path, _PathIdentity], ...]


def _identity_from_stat(result: os.stat_result) -> _PathIdentity:
    return _PathIdentity(
        device=int(result.st_dev),
        inode=int(result.st_ino),
        file_type=stat.S_IFMT(result.st_mode),
    )


def _path_identity(path: Path) -> _PathIdentity:
    return _identity_from_stat(path.lstat())


def _capture_directory_snapshot(path: Path) -> _DirectorySnapshot:
    _assert_safe_directory(path)
    snapshot: list[tuple[Path, _PathIdentity]] = []
    for component in _path_components(path):
        if not component.is_dir():
            raise RuntimeError(f"Managed path parent is not a directory: {component}")
        snapshot.append((component, _path_identity(component)))
    return tuple(snapshot)


def _assert_directory_snapshot(snapshot: _DirectorySnapshot) -> None:
    for path, expected in snapshot:
        _assert_safe_directory(path)
        if not path.is_dir() or _path_identity(path) != expected:
            raise RuntimeError(f"Managed directory identity changed during transaction: {path}")


def _assert_file_identity(path: Path, expected: _PathIdentity | None) -> None:
    _assert_safe_file(path)
    actual = _path_identity(path) if _path_exists(path) else None
    if actual != expected:
        raise RuntimeError(f"Managed file identity changed during transaction: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_file_identity(path: Path, size: int, digest: str) -> _PathIdentity:
    _assert_safe_file(path)
    if not path.is_file():
        raise RuntimeError(f"Managed file disappeared: {path}")
    path_identity = _path_identity(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        descriptor_identity = _identity_from_stat(os.fstat(descriptor))
        if descriptor_identity != path_identity:
            raise RuntimeError(f"Managed file identity changed during verification: {path}")
        actual_size = 0
        actual_digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            actual_size += len(chunk)
            actual_digest.update(chunk)
        if _identity_from_stat(os.fstat(descriptor)) != path_identity:
            raise RuntimeError(f"Managed file identity changed during verification: {path}")
    finally:
        os.close(descriptor)
    _assert_file_identity(path, path_identity)
    if actual_size != size or actual_digest.hexdigest() != digest:
        raise RuntimeError(f"Managed file content changed unexpectedly: {path}")
    return path_identity


def _file_matches_digest(path: Path, size: int, digest: str) -> bool:
    try:
        _verified_file_identity(path, size, digest)
    except RuntimeError:
        return False
    return True


def _deletion_for_file(
    path: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> FileDeletion:
    _assert_safe_file(path)
    if expected_size is None:
        expected_size = path.stat().st_size
    if expected_sha256 is None:
        expected_sha256 = _sha256_file(path)
    identity = _verified_file_identity(path, expected_size, expected_sha256)
    return FileDeletion(path, expected_size, expected_sha256, identity)


def _planned_original(
    path: Path,
) -> tuple[_PathIdentity | None, int | None, str | None, bool]:
    _assert_safe_file(path)
    if not path.is_file():
        return None, None, None, True
    size = path.stat().st_size
    digest = _sha256_file(path)
    identity = _verified_file_identity(path, size, digest)
    return identity, size, digest, False


def _record_matches_file(record: ManifestRecord, path: Path) -> bool:
    _assert_safe_file(path)
    return (
        path.is_file()
        and path.stat().st_size == record.size
        and _sha256_file(path) == record.sha256
    )


def _manifest_from_data(data: object) -> ValidatedManifest:
    if not isinstance(data, Mapping):
        raise ValueError("Manifest must be a JSON object")
    if data.get("schema") != MANIFEST_SCHEMA or data.get("product") != MANIFEST_PRODUCT:
        raise ValueError("Manifest schema or product does not identify this installer")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Manifest version must be a non-empty string")
    files = data.get("files")
    if not isinstance(files, list):
        raise ValueError("Manifest files must be a list")

    records: list[ManifestRecord] = []
    seen_paths: set[str] = set()
    seen_portable_paths: set[str] = set()
    for raw_record in files:
        if not isinstance(raw_record, Mapping):
            raise ValueError("Manifest file records must be objects")
        packaged_path, relative_path = _safe_manifest_relative_path(raw_record.get("path"))
        if packaged_path in seen_paths:
            raise ValueError(f"Duplicate manifest path: {packaged_path}")
        portable_path = packaged_path.casefold()
        if portable_path in seen_portable_paths:
            raise ValueError(f"Manifest paths collide on a case-insensitive filesystem: {packaged_path}")
        if packaged_path not in PACKAGED_FIXED_PATHS and relative_path.parts[0] != "licenses":
            raise ValueError(f"Manifest contains an unmanaged path: {packaged_path}")
        size = raw_record.get("size")
        digest = raw_record.get("sha256")
        mode = raw_record.get("mode")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"Invalid size for manifest path: {packaged_path}")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"Invalid SHA-256 for manifest path: {packaged_path}")
        if not isinstance(mode, str) or re.fullmatch(r"0[0-7]{3}", mode) is None:
            raise ValueError(f"Invalid mode for manifest path: {packaged_path}")
        seen_paths.add(packaged_path)
        seen_portable_paths.add(portable_path)
        records.append(ManifestRecord(packaged_path, relative_path, size, digest, mode))

    missing = sorted(PACKAGED_FIXED_PATHS - seen_paths)
    if missing:
        raise ValueError(f"Manifest is missing required payload paths: {', '.join(missing)}")
    records.sort(key=lambda record: record.packaged_path)
    return ValidatedManifest(version=version, records=tuple(records))


def load_release_manifest(manifest_path: Path) -> ValidatedManifest:
    _assert_safe_file(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid manifest JSON: {manifest_path}") from exc
    return _manifest_from_data(data)


def _source_license_paths(source_licenses: Path, source_dir: Path) -> set[Path]:
    if not _path_exists(source_licenses):
        return set()
    _assert_safe_directory(source_licenses, boundary=source_dir)
    relative_paths: set[Path] = set()
    for current_name, directory_names, file_names in os.walk(
        source_licenses, topdown=True, followlinks=False
    ):
        current = Path(current_name)
        for name in directory_names:
            _assert_safe_directory(current / name, boundary=source_dir)
        for name in file_names:
            path = current / name
            _assert_safe_file(path, boundary=source_dir)
            relative_paths.add(path.relative_to(source_licenses))
    return relative_paths


def validate_resources(
    source_dir: Path,
    *,
    language: str = DEFAULT_LANGUAGE,
    captured_payloads: dict[str, bytes] | None = None,
) -> ValidatedManifest:
    missing: list[Path] = []
    for path in required_resources(source_dir):
        try:
            _assert_safe_file(path, boundary=source_dir)
        except RuntimeError:
            raise
        if not path.is_file():
            missing.append(path)
    if missing:
        formatted = "\n".join(f"  {path}" for path in missing)
        raise FileNotFoundError(message("resources_missing", language, paths=formatted))

    manifest = load_release_manifest(source_dir / MANIFEST_NAME)
    for record in manifest.records:
        source = source_dir / record.relative_path
        _assert_safe_file(source, boundary=source_dir)
        if not source.is_file():
            raise FileNotFoundError(source)
        if record.packaged_path == f"{RESOURCE_DIRECTORY}/{PLUGIN_SCRIPT_NAME}":
            source_identity = _path_identity(source)
            source_bytes = source.read_bytes()
            _assert_file_identity(source, source_identity)
            matches = (
                len(source_bytes) == record.size
                and hashlib.sha256(source_bytes).hexdigest() == record.sha256
            )
            if captured_payloads is not None:
                captured_payloads[record.packaged_path] = source_bytes
        else:
            matches = (
                source.stat().st_size == record.size
                and _sha256_file(source) == record.sha256
            )
        if not matches:
            raise ValueError(f"Payload does not match manifest hash: {record.packaged_path}")

    recorded_licenses = set(manifest.license_paths)
    packaged_licenses = _source_license_paths(source_dir / "licenses", source_dir)
    if recorded_licenses != packaged_licenses:
        raise ValueError("Manifest license records do not match the packaged license tree")
    return manifest


def _lua_quote(value: str | Path) -> str:
    content = str(value)
    if all(ord(character) >= 32 and ord(character) != 127 for character in content):
        for level in range(100):
            equals = "=" * level
            closing = f"]{equals}]"
            if closing not in content:
                return f"[{equals}[{content}{closing}"
    escaped: list[str] = []
    for character in content:
        if character == "\\":
            escaped.append("\\\\")
        elif character == '"':
            escaped.append('\\"')
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif ord(character) < 32 or ord(character) == 127:
            escaped.append(f"\\{ord(character):03d}")
        else:
            escaped.append(character)
    return f'"{"".join(escaped)}"'


def _render_resolve_script(source_bytes: bytes, target_root: Path) -> bytes:
    try:
        content = source_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Packaged Resolve script is not valid UTF-8") from exc
    replacements = {
        "__INSTALL_ROOT__": target_root,
        "__ENGINE_EXECUTABLE__": target_root / ENGINE_NAME,
        "__RUNNER_EXECUTABLE__": target_root / RUNNER_NAME,
        "__FFMPEG_EXECUTABLE__": target_root / FFMPEG_NAME,
        "__FFPROBE_EXECUTABLE__": target_root / FFPROBE_NAME,
    }
    for marker, value in replacements.items():
        token = f"[[{marker}]]"
        if content.count(marker) != 1 or content.count(token) != 1:
            raise ValueError(f"Resolve script marker must appear exactly once: {marker}")
        content = content.replace(token, _lua_quote(value))
    return content.encode("utf-8")


def _script_targets_root(script_path: Path, target_root: Path) -> bool:
    _assert_safe_file(script_path)
    if not script_path.is_file():
        return False
    try:
        content = script_path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise RuntimeError(f"Installed Resolve script is not valid UTF-8: {script_path}") from exc
    expected_values = (
        target_root,
        target_root / ENGINE_NAME,
        target_root / RUNNER_NAME,
        target_root / FFMPEG_NAME,
        target_root / FFPROBE_NAME,
    )
    return all(
        _lua_quote(value) in content or f"[[{value}]]" in content
        for value in expected_values
    )


def _legacy_script_targets_root(script_path: Path, target_root: Path) -> bool:
    _assert_safe_file(script_path)
    if not script_path.is_file():
        return False
    try:
        content = script_path.read_text(encoding="utf-8")
    except UnicodeError:
        return False
    expected_values = (
        target_root,
        target_root / ENGINE_NAME,
        target_root / RUNNER_NAME,
        target_root / FFMPEG_NAME,
        target_root / FFPROBE_NAME,
    )
    return (
        ("Track Visualizer" in content or "TrackVisualizer" in content)
        and all(
            str(value) in content
            or repr(str(value))[1:-1] in content
            for value in expected_values
        )
    )


def _install_state_content(
    target_root: Path, script_directory: Path, script_content: bytes
) -> bytes:
    script_path = script_directory / PLUGIN_SCRIPT_NAME
    data = {
        "schema": INSTALL_STATE_SCHEMA,
        "product": MANIFEST_PRODUCT,
        "target_root": os.path.abspath(os.fspath(target_root)),
        "script_directory": os.path.abspath(os.fspath(script_directory)),
        "script_path": os.path.abspath(os.fspath(script_path)),
        "script_size": len(script_content),
        "script_sha256": hashlib.sha256(script_content).hexdigest(),
    }
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _install_state_from_data(
    data: object, expected_target_root: Path
) -> ValidatedInstallState:
    expected_keys = {
        "schema",
        "product",
        "target_root",
        "script_directory",
        "script_path",
        "script_size",
        "script_sha256",
    }
    if (
        not isinstance(data, dict)
        or set(data) != expected_keys
        or data.get("schema") != INSTALL_STATE_SCHEMA
        or data.get("product") != MANIFEST_PRODUCT
    ):
        raise RuntimeError("Invalid installer-owned install state")
    target_value = data["target_root"]
    script_directory_value = data["script_directory"]
    script_path_value = data["script_path"]
    if not all(
        isinstance(value, str)
        and value
        and Path(value).is_absolute()
        and value == os.path.abspath(os.path.normpath(value))
        for value in (target_value, script_directory_value, script_path_value)
    ):
        raise RuntimeError("Install state contains an invalid path")
    target_root = Path(target_value)
    script_directory = Path(script_directory_value)
    script_path = Path(script_path_value)
    if (
        _path_key(target_root) != _path_key(expected_target_root)
        or _path_key(script_path.parent) != _path_key(script_directory)
        or script_path.name != PLUGIN_SCRIPT_NAME
    ):
        raise RuntimeError("Install state does not match its managed root and script path")
    script_size = data["script_size"]
    script_sha256 = data["script_sha256"]
    if not _valid_digest(script_size, script_sha256):
        raise RuntimeError("Install state contains an invalid script digest")
    _assert_safe_directory(target_root)
    _assert_safe_directory(script_directory)
    _assert_no_links(script_path)
    return ValidatedInstallState(
        target_root=target_root,
        script_directory=script_directory,
        script_path=script_path,
        script_size=int(script_size),
        script_sha256=str(script_sha256),
    )


def _load_install_state(target_root: Path) -> ValidatedInstallState:
    state_path = target_root / INSTALL_STATE_NAME
    _assert_safe_file(state_path)
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    identity = _path_identity(state_path)
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid installer-owned install state: {state_path}") from exc
    _assert_file_identity(state_path, identity)
    return _install_state_from_data(data, target_root)


def _installed_installation(
    target_root: Path,
) -> tuple[ValidatedManifest, ValidatedInstallState] | None:
    _assert_safe_directory(target_root)
    manifest_path = target_root / MANIFEST_NAME
    state_path = target_root / INSTALL_STATE_NAME
    _assert_safe_file(manifest_path)
    _assert_safe_file(state_path)

    if not manifest_path.is_file() and not state_path.is_file():
        possible_artifacts = [
            *(
                target_root / name
                for name in MANAGED_ROOT_FILE_NAMES
                if name not in {MANIFEST_NAME, INSTALL_STATE_NAME}
            ),
        ]
        for path in possible_artifacts:
            _assert_safe_file(path)
        if any(_path_exists(path) for path in possible_artifacts):
            raise RuntimeError(
                "Managed-looking files exist without a valid owned installed manifest"
            )
        return None
    if not manifest_path.is_file() or not state_path.is_file():
        raise RuntimeError(
            "Installed files require both a valid owned manifest and install state"
        )

    manifest = load_release_manifest(manifest_path)
    install_state = _load_install_state(target_root)
    return manifest, install_state


PRE_MANIFEST_ROOT_FILE_NAMES = (
    ENGINE_NAME,
    RUNNER_NAME,
    FFMPEG_NAME,
    FFPROBE_NAME,
    LOGO_NAME,
)


def _pre_manifest_installation(target_root: Path, script_dir: Path) -> bool:
    """Whether ``target_root`` holds a build that predates the install manifest.

    Preview builds before 0.1.0 copied the runtime and the Resolve script without writing a
    manifest or install state. Such an install is replaced (transactionally, with rollback) only
    when nothing but the files those builds wrote is present and a Resolve script in
    ``script_dir`` points at exactly this root's runtime. Anything else stays fail-closed.
    """
    _assert_safe_directory(target_root)
    _assert_safe_directory(script_dir)
    owned_markers = (MANIFEST_NAME, INSTALL_STATE_NAME, NOTICE_NAME, "LICENSE")
    for name in owned_markers:
        _assert_safe_file(target_root / name)
        if _path_exists(target_root / name):
            return False
    runtime = [target_root / name for name in PRE_MANIFEST_ROOT_FILE_NAMES]
    for path in runtime:
        _assert_safe_file(path)
    if not any(_path_exists(path) for path in runtime):
        return False
    return any(
        _legacy_script_targets_root(script_dir / name, target_root)
        for name in (PLUGIN_SCRIPT_NAME, LEGACY_PLUGIN_SCRIPT_NAME)
    )


def _installed_script_health(
    install_state: ValidatedInstallState,
) -> str:
    script_path = install_state.script_path
    if not _path_exists(script_path):
        return "missing"
    if not script_path.is_file():
        return "modified"
    try:
        _verified_file_identity(
            script_path,
            install_state.script_size,
            install_state.script_sha256,
        )
    except RuntimeError:
        return "modified"
    return "owned" if _script_targets_root(script_path, install_state.target_root) else "modified"


def _record_target(
    record: ManifestRecord, target_root: Path, script_dir: Path
) -> tuple[Path, str, bool]:
    packaged_path = record.packaged_path
    mapping = {
        f"{BIN_DIRECTORY}/{ENGINE_NAME}": (target_root / ENGINE_NAME, "Engine", True),
        f"{BIN_DIRECTORY}/{RUNNER_NAME}": (target_root / RUNNER_NAME, "Runner", True),
        f"{BIN_DIRECTORY}/{FFMPEG_NAME}": (target_root / FFMPEG_NAME, "FFmpeg", True),
        f"{BIN_DIRECTORY}/{FFPROBE_NAME}": (target_root / FFPROBE_NAME, "FFprobe", True),
        f"{RESOURCE_DIRECTORY}/{PLUGIN_SCRIPT_NAME}": (
            script_dir / PLUGIN_SCRIPT_NAME,
            "Resolve script",
            False,
        ),
        f"{RESOURCE_DIRECTORY}/{LOGO_NAME}": (target_root / LOGO_NAME, "Logo", False),
        NOTICE_NAME: (target_root / NOTICE_NAME, "Notices", False),
        "LICENSE": (target_root / "LICENSE", "License", False),
    }
    if packaged_path in mapping:
        return mapping[packaged_path]
    relative_license = record.relative_path.relative_to("licenses")
    return target_root / "licenses" / relative_license, "Dependency license", False


def build_install_plan(
    source_dir: Path, target_root: Path, script_dir: Path, *, language: str
) -> InstallPlan:
    captured_payloads: dict[str, bytes] = {}
    manifest = validate_resources(
        source_dir,
        language=language,
        captured_payloads=captured_payloads,
    )
    pre_manifest = _pre_manifest_installation(target_root, script_dir)
    installed = None if pre_manifest else _installed_installation(target_root)
    old_manifest = installed[0] if installed is not None else None
    old_state = installed[1] if installed is not None else None
    old_script_health = (
        _installed_script_health(old_state) if old_state is not None else None
    )
    _assert_safe_directory(script_dir)
    _assert_safe_directory(target_root / "tmp")
    _assert_safe_directory(target_root / "licenses")

    changes: list[FileChange] = []
    script_packaged_path = f"{RESOURCE_DIRECTORY}/{PLUGIN_SCRIPT_NAME}"
    script_source_bytes = captured_payloads[script_packaged_path]
    rendered_script = _render_resolve_script(script_source_bytes, target_root)
    old_license_records = {
        record.relative_path.relative_to("licenses"): record
        for record in (old_manifest.license_records if old_manifest is not None else ())
    }
    for record in manifest.records:
        target, label, executable = _record_target(record, target_root, script_dir)
        _assert_safe_file(target)
        if record.relative_path.parts[0] == "licenses" and _path_exists(target):
            relative_license = record.relative_path.relative_to("licenses")
            old_record = old_license_records.get(relative_license)
            if old_record is None:
                raise RuntimeError(
                    f"Refusing to overwrite an unowned existing license file: {target}"
                )
            try:
                owned_identity = _verified_file_identity(
                    target, old_record.size, old_record.sha256
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Installed license file is modified or unowned: {target}"
                ) from exc
        else:
            owned_identity = None
        if record.packaged_path == script_packaged_path and _path_exists(target):
            if pre_manifest and _legacy_script_targets_root(target, target_root):
                pass
            elif (
                old_state is None
                or _path_key(target) != _path_key(old_state.script_path)
                or old_script_health != "owned"
            ):
                raise RuntimeError(
                    f"Refusing to overwrite an unowned or modified Resolve script: {target}"
                )
        (
            original_identity,
            original_size,
            original_sha256,
            original_absent,
        ) = _planned_original(target)
        if owned_identity is not None and original_identity != owned_identity:
            raise RuntimeError(f"Installed license identity changed while planning: {target}")
        if record.packaged_path == script_packaged_path:
            changes.append(
                FileChange(
                    target=target,
                    content=rendered_script,
                    label=label,
                    expected_size=len(rendered_script),
                    expected_sha256=hashlib.sha256(rendered_script).hexdigest(),
                    expected_original_identity=original_identity,
                    expected_original_size=original_size,
                    expected_original_sha256=original_sha256,
                    expected_original_absent=original_absent,
                )
            )
        else:
            changes.append(
                FileChange(
                    target=target,
                    source=source_dir / record.relative_path,
                    executable=executable,
                    label=label,
                    expected_size=record.size,
                    expected_sha256=record.sha256,
                    expected_original_identity=original_identity,
                    expected_original_size=original_size,
                    expected_original_sha256=original_sha256,
                    expected_original_absent=original_absent,
                )
            )

    manifest_content = (source_dir / MANIFEST_NAME).read_bytes()
    if _manifest_from_data(json.loads(manifest_content.decode("utf-8"))) != manifest:
        raise ValueError("Package manifest changed after validation")
    manifest_target = target_root / MANIFEST_NAME
    (
        original_identity,
        original_size,
        original_sha256,
        original_absent,
    ) = _planned_original(manifest_target)
    changes.append(
        FileChange(
            target=manifest_target,
            content=manifest_content,
            label="Manifest",
            expected_size=len(manifest_content),
            expected_sha256=hashlib.sha256(manifest_content).hexdigest(),
            expected_original_identity=original_identity,
            expected_original_size=original_size,
            expected_original_sha256=original_sha256,
            expected_original_absent=original_absent,
        )
    )
    state_content = _install_state_content(target_root, script_dir, rendered_script)
    state_target = target_root / INSTALL_STATE_NAME
    (
        original_identity,
        original_size,
        original_sha256,
        original_absent,
    ) = _planned_original(state_target)
    changes.append(
        FileChange(
            target=state_target,
            content=state_content,
            label="Install state",
            commit_marker=True,
            expected_size=len(state_content),
            expected_sha256=hashlib.sha256(state_content).hexdigest(),
            expected_original_identity=original_identity,
            expected_original_size=original_size,
            expected_original_sha256=original_sha256,
            expected_original_absent=original_absent,
        )
    )
    new_licenses = set(manifest.license_paths)
    stale_candidates = sorted(
        set(old_license_records) - new_licenses, key=lambda path: path.as_posix()
    )
    stale_pairs: list[tuple[Path, FileDeletion]] = [
        (
            path,
            _deletion_for_file(
                target_root / "licenses" / path,
                expected_size=old_license_records[path].size,
                expected_sha256=old_license_records[path].sha256,
            ),
        )
        for path in stale_candidates
        if _record_matches_file(
            old_license_records[path], target_root / "licenses" / path
        )
    ]
    stale_paths = tuple(path for path, _ in stale_pairs)
    deletions = [deletion for _, deletion in stale_pairs]
    script_directories: dict[str, Path] = {_path_key(script_dir): script_dir}
    if old_state is not None:
        script_directories[_path_key(old_state.script_directory)] = (
            old_state.script_directory
        )
        if (
            old_script_health == "owned"
            and _path_key(old_state.script_path)
            != _path_key(script_dir / PLUGIN_SCRIPT_NAME)
        ):
            deletions.append(
                _deletion_for_file(
                    old_state.script_path,
                    expected_size=old_state.script_size,
                    expected_sha256=old_state.script_sha256,
                )
            )
    for directory in script_directories.values():
        legacy_script = directory / LEGACY_PLUGIN_SCRIPT_NAME
        if _legacy_script_targets_root(legacy_script, target_root):
            deletions.append(_deletion_for_file(legacy_script))
    return InstallPlan(
        manifest=manifest,
        changes=tuple(changes),
        deletions=tuple(deletions),
        stale_license_paths=stale_paths,
        required_directories=(target_root / "tmp",),
        script_directories=tuple(script_directories.values()),
    )


def build_uninstall_plan(target_root: Path, script_dir: Path) -> UninstallPlan:
    installed = _installed_installation(target_root)
    selected_script = script_dir / PLUGIN_SCRIPT_NAME
    _assert_safe_file(selected_script)
    candidate_script_directories: dict[str, Path] = {_path_key(script_dir): script_dir}
    if installed is not None:
        candidate_script_directories[_path_key(installed[1].script_directory)] = (
            installed[1].script_directory
        )
    legacy_deletions = tuple(
        _deletion_for_file(legacy_script)
        for directory in candidate_script_directories.values()
        if _legacy_script_targets_root(
            legacy_script := directory / LEGACY_PLUGIN_SCRIPT_NAME, target_root
        )
    )
    transaction_script_directories: dict[str, Path] = {
        _path_key(deletion.target.parent): deletion.target.parent
        for deletion in legacy_deletions
    }
    if installed is None:
        return UninstallPlan(
            deletions=legacy_deletions,
            license_paths=(),
            script_directories=tuple(transaction_script_directories.values()),
            absent=not legacy_deletions,
        )
    manifest, install_state = installed
    script_health = _installed_script_health(install_state)
    transaction_script_directories[_path_key(install_state.script_directory)] = (
        install_state.script_directory
    )

    _assert_safe_directory(target_root / "licenses")
    candidates = [target_root / name for name in MANAGED_ROOT_FILE_NAMES]
    deletions: list[FileDeletion] = []
    for path in candidates:
        _assert_safe_file(path)
        if path.is_file():
            deletions.append(_deletion_for_file(path))
    if script_health == "owned":
        deletions.append(
            _deletion_for_file(
                install_state.script_path,
                expected_size=install_state.script_size,
                expected_sha256=install_state.script_sha256,
            )
        )
    owned_license_paths: list[Path] = []
    for record in manifest.license_records:
        relative_path = record.relative_path.relative_to("licenses")
        target = target_root / "licenses" / relative_path
        if _record_matches_file(record, target):
            deletions.append(
                _deletion_for_file(
                    target,
                    expected_size=record.size,
                    expected_sha256=record.sha256,
                )
            )
            owned_license_paths.append(relative_path)
    deletions.extend(legacy_deletions)
    return UninstallPlan(
        deletions=tuple(deletions),
        license_paths=tuple(owned_license_paths),
        script_directories=tuple(transaction_script_directories.values()),
    )


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(path), _path_key(root))) == _path_key(root)
    except ValueError:
        return False


def _stable_artifact_directory(
    target: Path, created_directories: Sequence[Path], journal_directory: Path
) -> Path:
    created_keys = {_path_key(path) for path in created_directories}
    directory = target.parent
    while (
        _path_key(directory) != _path_key(journal_directory)
        and _path_key(directory) in created_keys
    ):
        if directory.parent == directory:
            raise RuntimeError("Unable to find a stable transaction artifact directory")
        directory = directory.parent
    return directory


def _ensure_directory(
    path: Path,
    created_directories: set[Path],
    transaction_roots: Sequence[Path],
) -> None:
    _assert_safe_directory(path)
    missing: list[Path] = []
    current = path
    while not _path_exists(current):
        missing.append(current)
        if current.parent == current:
            raise RuntimeError(f"Filesystem root is unavailable: {current}")
        current = current.parent
    for directory in reversed(missing):
        parent_snapshot = _capture_directory_snapshot(directory.parent)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{directory.name}.tviz-directory-",
                suffix=".tmp",
                dir=directory.parent,
            )
        )
        temporary_identity = _path_identity(temporary)
        published = False
        try:
            _assert_directory_snapshot(parent_snapshot)
            _safe_publish_directory(
                temporary,
                directory,
                parent_snapshot=parent_snapshot,
                source_identity=temporary_identity,
            )
            published = True
        except FileExistsError:
            _assert_safe_directory(directory)
        finally:
            if _path_exists(temporary):
                _assert_safe_directory(temporary)
                if _path_identity(temporary) != temporary_identity:
                    raise RuntimeError(
                        f"Temporary directory identity changed: {temporary}"
                    )
                _remove_directory_if_empty(temporary)
        _assert_safe_directory(directory)
        if published and any(
            _path_is_within(directory, root) for root in transaction_roots
        ):
            created_directories.add(directory)


@dataclass
class _SecureTemp:
    path: Path
    descriptor: int
    identity: _PathIdentity
    parent_snapshot: _DirectorySnapshot

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


def _directory_snapshot_matches(snapshot: _DirectorySnapshot) -> bool:
    try:
        return all(
            path.is_dir()
            and not _is_link_or_junction(path)
            and _path_identity(path) == expected
            for path, expected in snapshot
        )
    except OSError:
        return False


def _remove_failed_temp(temporary: _SecureTemp) -> None:
    if not _directory_snapshot_matches(temporary.parent_snapshot):
        return
    try:
        _assert_file_identity(temporary.path, temporary.identity)
        temporary.path.unlink()
        _sync_directory(temporary.path.parent)
    except (OSError, RuntimeError):
        pass


def _temporary_file(
    target: Path,
    purpose: str,
    *,
    transaction_id: str | None = None,
    directory: Path | None = None,
) -> _SecureTemp:
    artifact_directory = directory or target.parent
    parent_snapshot = _capture_directory_snapshot(artifact_directory)
    identifier = f"{transaction_id}-" if transaction_id is not None else ""
    prefix = (
        f".tviz-journal-{identifier}"
        if purpose == "journal" and transaction_id is not None
        else f".{target.name}.tviz-{purpose}-{identifier}"
    )
    descriptor, name = tempfile.mkstemp(
        prefix=prefix,
        suffix=".tmp",
        dir=artifact_directory,
    )
    temporary = _SecureTemp(
        Path(name), descriptor, _identity_from_stat(os.fstat(descriptor)), parent_snapshot
    )
    try:
        _assert_directory_snapshot(parent_snapshot)
        _assert_file_identity(temporary.path, temporary.identity)
        return temporary
    except BaseException:
        temporary.close()
        _remove_failed_temp(temporary)
        raise


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("Failed to write transaction artifact")
        view = view[written:]


def _descriptor_digest(descriptor: int) -> tuple[int, str]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    size = 0
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _prepare_change(change: FileChange, staged: _SecureTemp) -> None:
    os.lseek(staged.descriptor, 0, os.SEEK_SET)
    os.ftruncate(staged.descriptor, 0)
    if change.source is not None:
        source_identity = _path_identity(change.source)
        staged_mode = stat.S_IMODE(change.source.stat().st_mode)
        source_descriptor = os.open(
            change.source, os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
        try:
            if _identity_from_stat(os.fstat(source_descriptor)) != source_identity:
                raise RuntimeError(f"Payload identity changed during staging: {change.source}")
            while chunk := os.read(source_descriptor, 1024 * 1024):
                _write_all(staged.descriptor, chunk)
            if _identity_from_stat(os.fstat(source_descriptor)) != source_identity:
                raise RuntimeError(f"Payload identity changed during staging: {change.source}")
        finally:
            os.close(source_descriptor)
        _assert_file_identity(change.source, source_identity)
    elif change.content is not None:
        staged_mode = 0o644
        _write_all(staged.descriptor, change.content)
    else:
        raise RuntimeError(f"File change has no source content: {change.target}")
    if change.executable:
        staged_mode |= 0o755
    if os.name != "nt" and hasattr(os, "fchmod"):
        os.fchmod(staged.descriptor, staged_mode)
    os.fsync(staged.descriptor)


def _verify_staged_change(change: FileChange, staged: _SecureTemp) -> None:
    size, digest = _descriptor_digest(staged.descriptor)
    if (
        change.expected_size is not None
        and change.expected_sha256 is not None
        and (size != change.expected_size or digest != change.expected_sha256)
    ):
        raise ValueError(f"Staged payload changed after validation: {change.target}")
    if _identity_from_stat(os.fstat(staged.descriptor)) != staged.identity:
        raise RuntimeError(f"Staged payload identity changed: {change.target}")


def _windows_flush_path(path: Path, *, directory: bool) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush = kernel32.FlushFileBuffers
    flush.argtypes = [wintypes.HANDLE]
    flush.restype = wintypes.BOOL
    close = kernel32.CloseHandle
    handle = create_file(
        str(path),
        0x40000000 if directory else 0x80000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x80000000 | (0x02000000 if directory else 0),
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), f"Unable to open for durable flush: {path}")
    try:
        if not flush(handle):
            raise OSError(ctypes.get_last_error(), f"Unable to durably flush: {path}")
    finally:
        close(handle)


def _sync_file(path: Path, identity: _PathIdentity | None = None) -> None:
    flags = (os.O_RDWR if os.name == "nt" else os.O_RDONLY) | getattr(
        os, "O_BINARY", 0
    )
    descriptor = os.open(path, flags)
    try:
        if identity is not None and _identity_from_stat(os.fstat(descriptor)) != identity:
            raise RuntimeError(f"File identity changed before durable flush: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if identity is not None:
        _assert_file_identity(path, identity)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        _windows_flush_path(path, directory=True)
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EINVAL, getattr(errno, "ENOTSUP", -1)}:
            raise
    finally:
        os.close(descriptor)


def _replace_path(source: Path, target: Path) -> None:
    if os.name != "nt":
        os.replace(source, target)
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move = kernel32.MoveFileExW
    move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    move.restype = ctypes.c_int
    if not move(str(source), str(target), 0x1 | 0x8):
        raise OSError(ctypes.get_last_error(), f"Unable to replace {target}")


def _publish_directory_path(source: Path, target: Path) -> None:
    if os.name != "nt":
        os.rename(source, target)
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move = kernel32.MoveFileExW
    move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    move.restype = ctypes.c_int
    if not move(str(source), str(target), 0x8):
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise FileExistsError(error, f"Directory already exists: {target}")
        raise OSError(error, f"Unable to publish directory {target}")


def _safe_publish_directory(
    source: Path,
    target: Path,
    *,
    parent_snapshot: _DirectorySnapshot,
    source_identity: _PathIdentity,
) -> None:
    if source.parent != target.parent:
        raise RuntimeError("Directory publication must remain in one parent")
    _assert_directory_snapshot(parent_snapshot)
    _assert_safe_directory(source)
    if _path_identity(source) != source_identity:
        raise RuntimeError(f"Directory identity changed before publication: {source}")
    _assert_safe_directory(target)
    if _path_exists(target):
        raise FileExistsError(target)
    _publish_directory_path(source, target)
    _assert_directory_snapshot(parent_snapshot)
    _assert_safe_directory(target)
    if _path_identity(target) != source_identity or _path_exists(source):
        raise RuntimeError(f"Directory publication identity changed: {target}")
    _sync_directory(target.parent)


def _artifact_publish_alias(path: Path) -> Path:
    return path.with_name(f"{path.name}.publish")


def _restore_artifact_publication(path: Path, identity: _PathIdentity) -> None:
    if _path_exists(path):
        return
    alias = _artifact_publish_alias(path)
    if not _path_exists(alias):
        return
    parent_snapshot = _capture_directory_snapshot(path.parent)
    _safe_replace(
        alias,
        path,
        parent_snapshot=parent_snapshot,
        source_identity=identity,
        target_identity=None,
    )


def _publish_artifact(path: Path, identity: _PathIdentity) -> None:
    _assert_file_identity(path, identity)
    _sync_file(path, identity)
    if os.name != "nt":
        _sync_directory(path.parent)
        return
    alias = _artifact_publish_alias(path)
    _assert_file_identity(alias, None)
    parent_snapshot = _capture_directory_snapshot(path.parent)
    _safe_replace(
        path,
        alias,
        parent_snapshot=parent_snapshot,
        source_identity=identity,
        target_identity=None,
    )
    try:
        _safe_replace(
            alias,
            path,
            parent_snapshot=parent_snapshot,
            source_identity=identity,
            target_identity=None,
        )
    except BaseException:
        _restore_artifact_publication(path, identity)
        raise


def _safe_replace(
    source: Path,
    target: Path,
    *,
    parent_snapshot: _DirectorySnapshot,
    source_identity: _PathIdentity,
    target_identity: _PathIdentity | None,
) -> None:
    source_parent_snapshot = (
        parent_snapshot
        if source.parent == target.parent
        else _capture_directory_snapshot(source.parent)
    )
    _assert_directory_snapshot(parent_snapshot)
    _assert_directory_snapshot(source_parent_snapshot)
    _assert_file_identity(source, source_identity)
    _assert_file_identity(target, target_identity)
    if source.stat().st_dev != target.parent.stat().st_dev:
        raise RuntimeError("Transaction replacement must remain on one filesystem")
    _replace_path(source, target)
    _assert_directory_snapshot(parent_snapshot)
    _assert_directory_snapshot(source_parent_snapshot)
    _assert_file_identity(target, source_identity)
    _assert_file_identity(source, None)
    _sync_file(target, source_identity)
    _sync_directory(target.parent)
    if source.parent != target.parent:
        _sync_directory(source.parent)


def _safe_unlink(
    path: Path,
    *,
    parent_snapshot: _DirectorySnapshot,
    expected_identity: _PathIdentity,
) -> None:
    _assert_directory_snapshot(parent_snapshot)
    _assert_file_identity(path, expected_identity)
    _sync_file(path, expected_identity)
    path.unlink()
    _assert_directory_snapshot(parent_snapshot)
    _assert_file_identity(path, None)
    _sync_directory(path.parent)


def _unlink_with_retries(path: Path, expected_identity: _PathIdentity) -> None:
    if not _path_exists(path):
        return
    parent_snapshot = _capture_directory_snapshot(path.parent)
    last_error: PermissionError | None = None
    for attempt in range(10):
        try:
            _safe_unlink(
                path,
                parent_snapshot=parent_snapshot,
                expected_identity=expected_identity,
            )
            return
        except PermissionError as exc:
            last_error = exc
            if attempt < 9:
                time.sleep(0.1)
    if last_error is not None:
        raise last_error


def _identity_data(identity: _PathIdentity | None) -> dict[str, int] | None:
    if identity is None:
        return None
    return {
        "device": identity.device,
        "inode": identity.inode,
        "file_type": identity.file_type,
    }


def _identity_from_data(value: object) -> _PathIdentity | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"device", "inode", "file_type"}:
        raise RuntimeError("Invalid transaction artifact identity")
    fields = tuple(value[name] for name in ("device", "inode", "file_type"))
    if any(isinstance(field, bool) or not isinstance(field, int) or field < 0 for field in fields):
        raise RuntimeError("Invalid transaction artifact identity")
    return _PathIdentity(*fields)


def _write_journal(path: Path, data: Mapping[str, object]) -> None:
    content = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = _temporary_file(
        path, "journal", transaction_id=str(data["transaction_id"])
    )
    try:
        _write_all(temporary.descriptor, content)
        os.fsync(temporary.descriptor)
        if _descriptor_digest(temporary.descriptor) != (
            len(content),
            hashlib.sha256(content).hexdigest(),
        ):
            raise RuntimeError("Journal staging verification failed")
        temporary.close()
        _assert_file_identity(temporary.path, temporary.identity)
        current_identity = _path_identity(path) if _path_exists(path) else None
        _safe_replace(
            temporary.path,
            path,
            parent_snapshot=temporary.parent_snapshot,
            source_identity=temporary.identity,
            target_identity=current_identity,
        )
    finally:
        temporary.close()
        if _path_exists(temporary.path):
            _unlink_with_retries(temporary.path, temporary.identity)


def _target_is_managed(
    target: Path,
    roots: Sequence[Path],
    allowed_targets: Sequence[Path],
    manifest_license_targets: Sequence[Path] = (),
    state_script_targets: Sequence[Path] = (),
) -> bool:
    if any(
        _path_key(target) == _path_key(path)
        for path in (
            *allowed_targets,
            *manifest_license_targets,
            *state_script_targets,
        )
    ):
        return True
    if len(roots) < 2:
        return False
    target_root, *script_directories = roots
    fixed_targets = {target_root / name for name in MANAGED_ROOT_FILE_NAMES}
    for script_directory in script_directories:
        fixed_targets.add(script_directory / LEGACY_PLUGIN_SCRIPT_NAME)
    if any(_path_key(target) == _path_key(path) for path in fixed_targets):
        return True
    return False


def _target_has_deferred_managed_shape(target: Path, roots: Sequence[Path]) -> bool:
    if len(roots) < 2:
        return False
    licenses_root = roots[0] / "licenses"
    if _path_is_within(target, licenses_root) and _path_key(target) != _path_key(
        licenses_root
    ):
        return True
    return any(
        _path_key(target) == _path_key(root / PLUGIN_SCRIPT_NAME)
        for root in roots[1:]
    )


def _secure_manifest(path: Path) -> ValidatedManifest:
    _assert_safe_file(path)
    identity = _path_identity(path)
    content = path.read_bytes()
    _assert_file_identity(path, identity)
    try:
        return _manifest_from_data(json.loads(content.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid manifest JSON: {path}") from exc


def _license_targets_from_manifest(
    manifest: ValidatedManifest, target_root: Path
) -> tuple[Path, ...]:
    return tuple(
        target_root / "licenses" / relative_path
        for relative_path in manifest.license_paths
    )


def _secure_install_state(
    path: Path, target_root: Path
) -> ValidatedInstallState:
    _assert_safe_file(path)
    identity = _path_identity(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid installer-owned install state: {path}") from exc
    _assert_file_identity(path, identity)
    return _install_state_from_data(data, target_root)


def _transaction_state_script_targets(
    changes: Sequence[FileChange], roots: Sequence[Path]
) -> tuple[Path, ...]:
    if len(roots) < 2:
        return ()
    target_root = roots[0]
    state_target = target_root / INSTALL_STATE_NAME
    targets: dict[str, Path] = {}
    if state_target.is_file():
        state = _secure_install_state(state_target, target_root)
        targets[_path_key(state.script_path)] = state.script_path
    for change in changes:
        if _path_key(change.target) != _path_key(state_target):
            continue
        if change.content is None:
            raise RuntimeError("Install-state transaction must use captured content")
        if (
            change.expected_size != len(change.content)
            or change.expected_sha256 != hashlib.sha256(change.content).hexdigest()
        ):
            raise RuntimeError("Install-state content changed after planning")
        try:
            state = _install_state_from_data(
                json.loads(change.content.decode("utf-8")), target_root
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Invalid transaction install-state content") from exc
        targets[_path_key(state.script_path)] = state.script_path
    return tuple(targets.values())


def _transaction_manifest_license_targets(
    changes: Sequence[FileChange], roots: Sequence[Path]
) -> tuple[Path, ...]:
    if len(roots) < 2:
        return ()
    target_root = roots[0]
    targets: dict[str, Path] = {}
    installed_path = target_root / MANIFEST_NAME
    if installed_path.is_file():
        for target in _license_targets_from_manifest(
            _secure_manifest(installed_path), target_root
        ):
            targets[_path_key(target)] = target
    for change in changes:
        if _path_key(change.target) != _path_key(installed_path):
            continue
        if change.content is None:
            raise RuntimeError("Manifest transaction must use captured content")
        if (
            change.expected_size != len(change.content)
            or change.expected_sha256 != hashlib.sha256(change.content).hexdigest()
        ):
            raise RuntimeError("Manifest transaction content changed after planning")
        try:
            manifest = _manifest_from_data(json.loads(change.content.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid transaction manifest content") from exc
        for target in _license_targets_from_manifest(manifest, target_root):
            targets[_path_key(target)] = target
    return tuple(targets.values())


def _journal_state_script_targets(
    operations: Sequence[object], expected_roots: Sequence[Path]
) -> tuple[Path, ...]:
    if len(expected_roots) < 2:
        return ()
    target_root = expected_roots[0]
    state_target = target_root / INSTALL_STATE_NAME
    candidates: list[tuple[Path, int | None, str | None, _PathIdentity | None]] = []
    if state_target.is_file():
        candidates.append((state_target, None, None, None))
    for operation in operations:
        if (
            not isinstance(operation, Mapping)
            or operation.get("type") not in {"replace", "delete"}
            or _path_key(Path(str(operation.get("target"))))
            != _path_key(state_target)
        ):
            continue
        for field, prefix in (("staged", "new"), ("backup", "original")):
            value = operation.get(field)
            identity = _identity_from_data(operation.get(f"{field}_identity"))
            size = operation.get(f"{prefix}_size")
            digest = operation.get(f"{prefix}_sha256")
            if (
                isinstance(value, str)
                and identity is not None
                and _valid_digest(size, digest)
            ):
                candidates.append((Path(value), int(size), str(digest), identity))

    targets: dict[str, Path] = {}
    for path, size, digest, expected_identity in candidates:
        try:
            if expected_identity is not None:
                actual = _verified_file_identity(path, int(size), str(digest))
                if actual != expected_identity:
                    continue
            state = _secure_install_state(path, target_root)
        except (OSError, RuntimeError, ValueError):
            continue
        targets[_path_key(state.script_path)] = state.script_path
    return tuple(targets.values())


def _journal_manifest_license_targets(
    operations: Sequence[object], expected_roots: Sequence[Path]
) -> tuple[Path, ...]:
    if len(expected_roots) < 2:
        return ()
    target_root = expected_roots[0]
    manifest_target = target_root / MANIFEST_NAME
    candidates: list[tuple[Path, int | None, str | None, _PathIdentity | None]] = []
    if manifest_target.is_file():
        candidates.append((manifest_target, None, None, None))
    for operation in operations:
        if (
            not isinstance(operation, Mapping)
            or operation.get("type") not in {"replace", "delete"}
            or _path_key(Path(str(operation.get("target"))))
            != _path_key(manifest_target)
        ):
            continue
        for field, prefix in (("staged", "new"), ("backup", "original")):
            value = operation.get(field)
            identity = _identity_from_data(operation.get(f"{field}_identity"))
            size = operation.get(f"{prefix}_size")
            digest = operation.get(f"{prefix}_sha256")
            if (
                isinstance(value, str)
                and identity is not None
                and _valid_digest(size, digest)
            ):
                candidates.append((Path(value), int(size), str(digest), identity))

    targets: dict[str, Path] = {}
    for path, size, digest, expected_identity in candidates:
        try:
            if expected_identity is not None:
                actual = _verified_file_identity(path, int(size), str(digest))
                if actual != expected_identity:
                    continue
            manifest = _secure_manifest(path)
        except (OSError, RuntimeError, ValueError):
            continue
        for target in _license_targets_from_manifest(manifest, target_root):
            targets[_path_key(target)] = target
    return tuple(targets.values())


_OPERATION_KEYS = {
    "type",
    "target",
    "state",
    "had_original",
    "original_identity",
    "original_mode",
    "original_size",
    "original_sha256",
    "new_size",
    "new_sha256",
    "staged",
    "staged_identity",
    "applied_identity",
    "backup",
    "backup_identity",
}


def _valid_digest(size: object, digest: object) -> bool:
    return (
        not isinstance(size, bool)
        and isinstance(size, int)
        and size >= 0
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
    )


def _validate_transaction_journal(
    data: object,
    journal_path: Path,
    expected_roots: Sequence[Path],
    allowed_targets: Sequence[Path] = (),
) -> dict[str, object]:
    top_keys = {
        "schema",
        "transaction_id",
        "phase",
        "roots",
        "created_directories",
        "operations",
    }
    if (
        not isinstance(data, dict)
        or set(data) != top_keys
        or data.get("schema") != TRANSACTION_SCHEMA
    ):
        raise RuntimeError(f"Invalid installer transaction journal: {journal_path}")
    transaction_id = data["transaction_id"]
    roots = data["roots"]
    if (
        not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or not isinstance(roots, list)
        or not all(isinstance(root, str) and Path(root).is_absolute() for root in roots)
        or [_path_key(Path(root)) for root in roots]
        != [_path_key(root) for root in expected_roots]
        or data["phase"] not in {"active", "committed"}
    ):
        raise RuntimeError(f"Invalid installer transaction journal: {journal_path}")
    created_directories = data["created_directories"]
    operations = data["operations"]
    if (
        not isinstance(created_directories, list)
        or not isinstance(operations, list)
        or not operations
    ):
        raise RuntimeError(f"Invalid installer transaction journal: {journal_path}")
    recorded_created_directories = tuple(
        Path(value)
        for value in created_directories
        if isinstance(value, str) and Path(value).is_absolute()
    )

    seen_targets: set[str] = set()
    operation_targets: list[Path] = []
    valid_states = {"planned", "staged", "ready", "applied", "rolled_back"}
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != _OPERATION_KEYS:
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        operation_type = operation["type"]
        target_value = operation["target"]
        if (
            operation_type not in {"replace", "delete"}
            or operation["state"] not in valid_states
            or not isinstance(target_value, str)
            or not Path(target_value).is_absolute()
        ):
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        target = Path(target_value)
        target_key = _path_key(target)
        if target_key in seen_targets:
            raise RuntimeError(f"Duplicate installer transaction target: {target}")
        seen_targets.add(target_key)
        operation_targets.append(target)
        legacy_root = next(
            (
                root
                for root in expected_roots[1:]
                if target_key == _path_key(root / LEGACY_PLUGIN_SCRIPT_NAME)
            ),
            None,
        )
        if legacy_root is not None:
            if operation_type != "delete":
                raise RuntimeError(f"Unsafe legacy script transaction: {target}")
            backup_value = operation["backup"]
            ownership_path = (
                target
                if target.is_file()
                else Path(str(backup_value))
                if isinstance(backup_value, str) and Path(backup_value).is_file()
                else None
            )
            if ownership_path is None:
                if data["phase"] != "committed":
                    raise RuntimeError(f"Legacy script is not installer-owned: {target}")
            elif not _legacy_script_targets_root(ownership_path, expected_roots[0]):
                raise RuntimeError(f"Legacy script is not installer-owned: {target}")
        had_original = operation["had_original"]
        original_identity = _identity_from_data(operation["original_identity"])
        original_valid = _valid_digest(
            operation["original_size"], operation["original_sha256"]
        )
        mode = operation["original_mode"]
        if (
            not isinstance(had_original, bool)
            or had_original != (original_identity is not None)
            or had_original != original_valid
            or (had_original and (isinstance(mode, bool) or not isinstance(mode, int) or mode < 0))
            or (not had_original and mode is not None)
        ):
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        new_valid = _valid_digest(operation["new_size"], operation["new_sha256"])
        if (operation_type == "replace") != new_valid:
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        state = operation["state"]
        if data["phase"] == "committed" and state != "applied":
            raise RuntimeError(f"Invalid committed transaction state: {journal_path}")
        if operation_type == "delete" and state == "staged":
            raise RuntimeError(f"Invalid deletion transaction state: {journal_path}")
        if operation_type == "delete" and not had_original:
            raise RuntimeError(f"Invalid deletion transaction original: {journal_path}")
        if operation_type == "delete" and (
            operation["staged"] is not None
            or operation["staged_identity"] is not None
            or operation["applied_identity"] is not None
        ):
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        applied_identity = _identity_from_data(operation["applied_identity"])
        if operation_type == "replace" and state not in {"ready", "applied", "rolled_back"}:
            if applied_identity is not None:
                raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        for field, purpose in (("staged", "new"), ("backup", "backup")):
            value = operation[field]
            identity = _identity_from_data(operation[f"{field}_identity"])
            if value is None:
                if identity is not None:
                    raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
                continue
            if not isinstance(value, str) or identity is None:
                raise RuntimeError(f"Invalid installer transaction artifact: {journal_path}")
            artifact = Path(value)
            prefix = f".{target.name}.tviz-{purpose}-{transaction_id}-"
            allowed_parent = target.parent
            if field == "staged":
                allowed_parent = _stable_artifact_directory(
                    target, recorded_created_directories, expected_roots[0]
                )
            if (
                not artifact.is_absolute()
                or artifact.parent != allowed_parent
                or not artifact.name.startswith(prefix)
                or not artifact.name.endswith(".tmp")
            ):
                raise RuntimeError(f"Unsafe installer transaction artifact: {artifact}")
        if not had_original and (
            operation["backup"] is not None or operation["backup_identity"] is not None
        ):
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        if operation_type == "replace" and state == "planned" and (
            operation["backup"] is not None or operation["backup_identity"] is not None
        ):
            raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        if state in {"staged", "ready", "applied"}:
            if operation_type == "replace" and operation["staged_identity"] is None:
                raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")
        if state in {"ready", "applied"} and had_original:
            if operation["backup_identity"] is None:
                raise RuntimeError(f"Invalid installer transaction operation: {journal_path}")

    if data["phase"] == "active":
        states = [str(operation["state"]) for operation in operations]
        rolled_back_at = next(
            (index for index, state in enumerate(states) if state == "rolled_back"),
            len(states),
        )
        if any(state != "rolled_back" for state in states[rolled_back_at:]):
            raise RuntimeError(f"Invalid rollback transaction order: {journal_path}")
        mutation_states = states[:rolled_back_at]
        seen_pending = False
        ready_count = 0
        for state in mutation_states:
            if state == "ready":
                ready_count += 1
            if state in {"ready", "applied"}:
                if seen_pending:
                    raise RuntimeError(f"Invalid mutation transaction order: {journal_path}")
            else:
                seen_pending = True
        if ready_count > 1:
            raise RuntimeError(f"Invalid mutation transaction order: {journal_path}")

    manifest_license_targets = _journal_manifest_license_targets(
        operations, expected_roots
    )
    state_script_targets = _journal_state_script_targets(operations, expected_roots)
    for operation, target in zip(operations, operation_targets, strict=True):
        if not _target_is_managed(
            target,
            expected_roots,
            allowed_targets,
            manifest_license_targets,
            state_script_targets,
        ):
            backup = operation["backup"]
            harmless_completed_deletion = (
                data["phase"] == "committed"
                and operation["type"] == "delete"
                and operation["state"] == "applied"
                and not _path_exists(target)
                and (not isinstance(backup, str) or not _path_exists(Path(backup)))
            )
            staged = operation["staged"]
            harmless_rolled_back_replacement = (
                data["phase"] == "active"
                and operation["type"] == "replace"
                and operation["state"] == "rolled_back"
                and not operation["had_original"]
                and not _path_exists(target)
                and (not isinstance(staged, str) or not _path_exists(Path(staged)))
                and (not isinstance(backup, str) or not _path_exists(Path(backup)))
                and _target_has_deferred_managed_shape(target, expected_roots)
            )
            if harmless_completed_deletion or harmless_rolled_back_replacement:
                continue
            raise RuntimeError(f"Unsafe installer transaction target: {target}")

    seen_directories: set[str] = set()
    for value in created_directories:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise RuntimeError(f"Unsafe installer transaction directory: {value}")
        directory = Path(value)
        directory_key = _path_key(directory)
        is_root = any(directory_key == _path_key(root) for root in expected_roots)
        is_target_ancestor = any(
            directory_key != _path_key(target)
            and _path_is_within(target, directory)
            and any(_path_is_within(directory, root) for root in expected_roots)
            for target in operation_targets
        )
        if directory_key in seen_directories or not (is_root or is_target_ancestor):
            raise RuntimeError(f"Unsafe installer transaction directory: {value}")
        seen_directories.add(directory_key)
    return data


def _load_transaction_journal(
    journal_path: Path,
    expected_roots: Sequence[Path],
    allowed_targets: Sequence[Path] = (),
) -> tuple[dict[str, object], _PathIdentity]:
    _assert_safe_file(journal_path)
    identity = _path_identity(journal_path)
    try:
        content = journal_path.read_bytes()
        _assert_file_identity(journal_path, identity)
        data = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid installer transaction journal: {journal_path}") from exc
    return (
        _validate_transaction_journal(
            data, journal_path, expected_roots, allowed_targets
        ),
        identity,
    )


def _recorded_transaction_roots(
    journal_path: Path, selected_target_root: Path
) -> tuple[Path, ...]:
    _assert_safe_file(journal_path)
    identity = _path_identity(journal_path)
    try:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid installer transaction journal: {journal_path}") from exc
    _assert_file_identity(journal_path, identity)
    roots = data.get("roots") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema") != TRANSACTION_SCHEMA or (
        not isinstance(roots, list)
        or not 2 <= len(roots) <= 3
        or not all(
            isinstance(value, str)
            and Path(value).is_absolute()
            and value == os.path.abspath(os.path.normpath(value))
            for value in roots
        )
    ):
        raise RuntimeError(f"Invalid installer transaction roots: {journal_path}")
    recorded = tuple(Path(value) for value in roots)
    if _path_key(recorded[0]) != _path_key(selected_target_root):
        raise RuntimeError("Transaction journal belongs to a different install root")
    script_keys: set[str] = set()
    for script_root in recorded[1:]:
        key = _path_key(script_root)
        if key in script_keys:
            raise RuntimeError("Transaction journal repeats a Resolve script root")
        script_keys.add(key)
        _assert_safe_directory(script_root)
    return recorded


def _artifact_identity(operation: Mapping[str, object], field: str) -> _PathIdentity:
    identity = _identity_from_data(operation[f"{field}_identity"])
    if identity is None:
        raise RuntimeError(f"Transaction artifact was not securely registered: {field}")
    return identity


def _verified_artifact(
    operation: Mapping[str, object], field: str, digest_prefix: str
) -> tuple[Path, _PathIdentity]:
    value = operation[field]
    if not isinstance(value, str):
        raise RuntimeError(f"Transaction artifact is missing: {field}")
    path = Path(value)
    identity = _artifact_identity(operation, field)
    _restore_artifact_publication(path, identity)
    verified = _verified_file_identity(
        path,
        int(operation[f"{digest_prefix}_size"]),
        str(operation[f"{digest_prefix}_sha256"]),
    )
    if verified != identity:
        raise RuntimeError(f"Transaction artifact identity changed: {path}")
    return path, identity


def _target_digest_identity(
    operation: Mapping[str, object], prefix: str
) -> _PathIdentity | None:
    target = Path(str(operation["target"]))
    if not _path_exists(target):
        return None
    try:
        return _verified_file_identity(
            target,
            int(operation[f"{prefix}_size"]),
            str(operation[f"{prefix}_sha256"]),
        )
    except RuntimeError:
        return None


def _require_recorded_target_identity(
    operation: Mapping[str, object],
    actual: _PathIdentity | None,
    *identity_fields: str,
) -> _PathIdentity | None:
    if actual is None:
        return None
    allowed = {
        identity
        for field in identity_fields
        if (identity := _identity_from_data(operation[field])) is not None
    }
    if actual not in allowed:
        raise RuntimeError(
            f"Transaction target identity changed: {operation['target']}"
        )
    return actual


def _missing_operation_parent_is_recorded(
    target: Path, data: Mapping[str, object]
) -> bool:
    created = data["created_directories"]
    if not isinstance(created, list):
        raise RuntimeError("Invalid transaction directories")
    recorded = {_path_key(Path(str(value))) for value in created}
    current = target.parent
    missing: list[Path] = []
    while not _path_exists(current):
        missing.append(current)
        if current.parent == current:
            return False
        current = current.parent
    return bool(missing) and all(_path_key(path) in recorded for path in missing)


def _recreate_recorded_operation_parent(
    target: Path,
    data: Mapping[str, object],
    transaction_roots: Sequence[Path],
) -> None:
    if _path_exists(target.parent):
        _assert_safe_directory(target.parent)
        return
    if not _missing_operation_parent_is_recorded(target, data):
        raise RuntimeError(
            f"Missing transaction target parent was not installer-created: {target.parent}"
        )
    recreated: set[Path] = set()
    _ensure_directory(target.parent, recreated, transaction_roots)
    recorded = {
        _path_key(Path(str(value)))
        for value in data["created_directories"]
        if isinstance(value, str)
    }
    if any(_path_key(path) not in recorded for path in recreated):
        raise RuntimeError("Recovery recreated an unrecorded transaction directory")


def _rollback_journal_operation(
    operation: Mapping[str, object], data: Mapping[str, object]
) -> None:
    if operation["state"] in {"planned", "staged", "rolled_back"}:
        return
    target = Path(str(operation["target"]))
    if not _path_exists(target.parent):
        _assert_safe_directory(target.parent)
        if (
            not operation["had_original"]
            and _missing_operation_parent_is_recorded(target, data)
        ):
            return
        raise RuntimeError(f"Interrupted transaction target parent disappeared: {target.parent}")
    parent_snapshot = _capture_directory_snapshot(target.parent)
    original_identity = (
        _require_recorded_target_identity(
            operation,
            _target_digest_identity(operation, "original"),
            "original_identity",
            "backup_identity",
        )
        if operation["had_original"]
        else None
    )
    new_identity = (
        _require_recorded_target_identity(
            operation,
            _target_digest_identity(operation, "new"),
            "staged_identity",
            "applied_identity",
        )
        if operation["type"] == "replace"
        else None
    )
    if operation["had_original"]:
        if original_identity is not None:
            return
        if _path_exists(target) and new_identity is None:
            raise RuntimeError(f"Interrupted transaction target changed unexpectedly: {target}")
        if operation["type"] == "replace" and new_identity is not None:
            staged_value = operation["staged"]
            if not isinstance(staged_value, str):
                raise RuntimeError("Replacement transaction lacks a staged artifact path")
            staged = Path(staged_value)
            if _path_exists(staged):
                _verified_artifact(operation, "staged", "new")
                _safe_unlink(
                    target,
                    parent_snapshot=parent_snapshot,
                    expected_identity=new_identity,
                )
            else:
                _safe_replace(
                    target,
                    staged,
                    parent_snapshot=_capture_directory_snapshot(staged.parent),
                    source_identity=new_identity,
                    target_identity=None,
                )
            new_identity = None
        backup, backup_identity = _verified_artifact(operation, "backup", "original")
        _safe_replace(
            backup,
            target,
            parent_snapshot=parent_snapshot,
            source_identity=backup_identity,
            target_identity=new_identity,
        )
        _verified_file_identity(
            target,
            int(operation["original_size"]),
            str(operation["original_sha256"]),
        )
        return
    if not _path_exists(target):
        return
    if new_identity is None:
        raise RuntimeError(f"Interrupted transaction target changed unexpectedly: {target}")
    if operation["type"] == "replace":
        staged_value = operation["staged"]
        if not isinstance(staged_value, str):
            raise RuntimeError("Replacement transaction lacks a staged artifact path")
        staged = Path(staged_value)
        if _path_exists(staged):
            _verified_artifact(operation, "staged", "new")
            _safe_unlink(
                target,
                parent_snapshot=parent_snapshot,
                expected_identity=new_identity,
            )
        else:
            _safe_replace(
                target,
                staged,
                parent_snapshot=_capture_directory_snapshot(staged.parent),
                source_identity=new_identity,
                target_identity=None,
            )
        return
    _safe_unlink(
        target,
        parent_snapshot=parent_snapshot,
        expected_identity=new_identity,
    )


def _finish_committed_operation(
    operation: Mapping[str, object],
    data: Mapping[str, object],
    transaction_roots: Sequence[Path],
) -> None:
    target = Path(str(operation["target"]))
    if not _path_exists(target.parent):
        _assert_safe_directory(target.parent)
        if operation["type"] == "delete":
            return
        _recreate_recorded_operation_parent(target, data, transaction_roots)
    parent_snapshot = _capture_directory_snapshot(target.parent)
    if operation["type"] == "replace":
        new_identity = _require_recorded_target_identity(
            operation,
            _target_digest_identity(operation, "new"),
            "staged_identity",
            "applied_identity",
        )
        if new_identity is not None:
            return
        original_identity = (
            _require_recorded_target_identity(
                operation,
                _target_digest_identity(operation, "original"),
                "original_identity",
            )
            if operation["had_original"]
            else None
        )
        if _path_exists(target) and original_identity is None:
            raise RuntimeError(f"Committed transaction target changed unexpectedly: {target}")
        staged, staged_identity = _verified_artifact(operation, "staged", "new")
        _safe_replace(
            staged,
            target,
            parent_snapshot=parent_snapshot,
            source_identity=staged_identity,
            target_identity=original_identity,
        )
        return
    if not _path_exists(target):
        return
    original_identity = _require_recorded_target_identity(
        operation,
        _target_digest_identity(operation, "original"),
        "original_identity",
    )
    if original_identity is None:
        raise RuntimeError(f"Committed deletion target changed unexpectedly: {target}")
    _safe_unlink(
        target,
        parent_snapshot=parent_snapshot,
        expected_identity=original_identity,
    )


def _cleanup_transaction_artifacts(data: Mapping[str, object]) -> None:
    operations = data["operations"]
    if not isinstance(operations, list):
        raise RuntimeError("Invalid transaction operations")
    ordered_operations = sorted(
        operations,
        key=lambda operation: (
            2
            if isinstance(operation, Mapping)
            and Path(str(operation.get("target"))).name == INSTALL_STATE_NAME
            else 1
            if isinstance(operation, Mapping)
            and Path(str(operation.get("target"))).name == MANIFEST_NAME
            else 0
        ),
    )
    for operation in ordered_operations:
        if not isinstance(operation, Mapping):
            raise RuntimeError("Invalid transaction operation")
        for field in ("staged", "backup"):
            value = operation[field]
            identity = _identity_from_data(operation[f"{field}_identity"])
            if value is not None and identity is not None:
                _restore_artifact_publication(Path(str(value)), identity)
            if value is not None and _path_exists(Path(str(value))):
                if identity is None:
                    raise RuntimeError(f"Refusing to remove unregistered artifact: {value}")
                _assert_file_identity(Path(str(value)), identity)
                _unlink_with_retries(Path(str(value)), identity)


def _cleanup_abandoned_journal_temps(
    target_root: Path, journal_path: Path
) -> None:
    _assert_safe_directory(target_root)
    _assert_safe_file(journal_path)
    if journal_path.is_file() or not target_root.is_dir():
        return
    snapshot = _capture_directory_snapshot(target_root)
    pattern = re.compile(r"\.tviz-journal-[0-9a-f]{32}-.+\.tmp")
    for candidate in target_root.iterdir():
        if pattern.fullmatch(candidate.name) is None:
            continue
        if _is_link_or_junction(candidate) or not candidate.is_file():
            continue
        identity = _path_identity(candidate)
        _safe_unlink(
            candidate,
            parent_snapshot=snapshot,
            expected_identity=identity,
        )


def _cleanup_orphan_transaction_artifacts(
    data: Mapping[str, object], journal_path: Path
) -> None:
    transaction_id = data["transaction_id"]
    operations = data["operations"]
    if not isinstance(transaction_id, str) or not isinstance(operations, list):
        raise RuntimeError("Invalid transaction orphan-cleanup data")
    prefixes_by_directory: dict[str, tuple[Path, set[str]]] = {}
    registered_paths: set[str] = set()
    for operation in operations:
        if not isinstance(operation, Mapping):
            raise RuntimeError("Invalid transaction operation")
        target = Path(str(operation["target"]))
        key = _path_key(target.parent)
        directory, prefixes = prefixes_by_directory.setdefault(
            key, (target.parent, set())
        )
        prefixes.update(
            {
                f".{target.name}.tviz-new-{transaction_id}-",
                f".{target.name}.tviz-backup-{transaction_id}-",
                f".{target.name}.tviz-apply-{transaction_id}-",
            }
        )
        for field in ("staged", "backup"):
            value = operation[field]
            if isinstance(value, str):
                artifact = Path(value)
                _, artifact_prefixes = prefixes_by_directory.setdefault(
                    _path_key(artifact.parent), (artifact.parent, set())
                )
                artifact_prefixes.update(
                    {
                        f".{target.name}.tviz-new-{transaction_id}-",
                        f".{target.name}.tviz-backup-{transaction_id}-",
                        f".{target.name}.tviz-apply-{transaction_id}-",
                    }
                )
                registered_paths.add(_path_key(artifact))
                registered_paths.add(_path_key(_artifact_publish_alias(artifact)))
    journal_key = _path_key(journal_path.parent)
    directory, prefixes = prefixes_by_directory.setdefault(
        journal_key, (journal_path.parent, set())
    )
    prefixes.add(f".tviz-journal-{transaction_id}-")

    for directory, prefixes in prefixes_by_directory.values():
        _assert_safe_directory(directory)
        if not directory.is_dir():
            continue
        snapshot = _capture_directory_snapshot(directory)
        for candidate in directory.iterdir():
            if _path_key(candidate) in registered_paths:
                continue
            if not candidate.name.endswith((".tmp", ".tmp.publish")) or not any(
                candidate.name.startswith(prefix) for prefix in prefixes
            ):
                continue
            if _is_link_or_junction(candidate) or not candidate.is_file():
                continue
            identity = _path_identity(candidate)
            _safe_unlink(
                candidate,
                parent_snapshot=snapshot,
                expected_identity=identity,
            )


def _recover_transaction(
    journal_path: Path,
    expected_roots: Sequence[Path],
    *,
    allowed_targets: Sequence[Path] = (),
) -> None:
    data, _ = _load_transaction_journal(
        journal_path, expected_roots, allowed_targets
    )
    _cleanup_orphan_transaction_artifacts(data, journal_path)
    operations = data["operations"]
    if not isinstance(operations, list):
        raise RuntimeError("Invalid transaction operations")
    if data["phase"] == "active":
        for operation in reversed(operations):
            if not isinstance(operation, dict):
                raise RuntimeError("Invalid transaction operation")
            if operation["state"] != "rolled_back":
                _rollback_journal_operation(operation, data)
                operation["state"] = "rolled_back"
                _write_journal(journal_path, data)
    else:
        for operation in operations:
            if not isinstance(operation, dict):
                raise RuntimeError("Invalid transaction operation")
            _finish_committed_operation(operation, data, expected_roots)
    _, journal_identity = _load_transaction_journal(
        journal_path, expected_roots, allowed_targets
    )
    _cleanup_transaction_artifacts(data)
    _unlink_with_retries(journal_path, journal_identity)
    if data["phase"] == "active":
        created = data["created_directories"]
        if not isinstance(created, list):
            raise RuntimeError("Invalid transaction directories")
        for directory in sorted(
            (Path(str(value)) for value in created),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            _remove_directory_if_empty(directory)


def _recover_stale_transaction(
    target_root: Path,
    script_dir: Path,
    *,
    dry_run: bool = False,
) -> bool:
    journal_path = target_root / TRANSACTION_JOURNAL_NAME
    _assert_safe_file(journal_path)
    if not journal_path.is_file():
        if not dry_run:
            _cleanup_abandoned_journal_temps(target_root, journal_path)
        return False
    recorded_roots = _recorded_transaction_roots(journal_path, target_root)
    _load_transaction_journal(journal_path, recorded_roots)
    if dry_run:
        raise RuntimeError(
            "An interrupted installer transaction requires recovery before a dry run"
        )
    if _windows_stale_recovery_requires_process_stop():
        stop_existing_processes(target_root)
    _recover_transaction(journal_path, recorded_roots)
    return True


def _windows_stale_recovery_requires_process_stop() -> bool:
    return os.name == "nt"


def _operation_record(
    operation_type: str,
    target: Path,
    original_identity: _PathIdentity | None,
    original_mode: int | None,
    original_size: int | None,
    original_sha256: str | None,
    new_size: int | None,
    new_sha256: str | None,
) -> dict[str, object]:
    return {
        "type": operation_type,
        "target": os.path.abspath(os.fspath(target)),
        "state": "planned",
        "had_original": original_identity is not None,
        "original_identity": _identity_data(original_identity),
        "original_mode": original_mode,
        "original_size": original_size,
        "original_sha256": original_sha256,
        "new_size": new_size,
        "new_sha256": new_sha256,
        "staged": None,
        "staged_identity": None,
        "applied_identity": None,
        "backup": None,
        "backup_identity": None,
    }


def _register_temp(
    operation: dict[str, object],
    field: str,
    temporary: _SecureTemp,
    journal_path: Path,
    journal_data: dict[str, object],
) -> None:
    operation[field] = os.path.abspath(os.fspath(temporary.path))
    operation[f"{field}_identity"] = _identity_data(temporary.identity)
    try:
        _write_journal(journal_path, journal_data)
    except BaseException:
        temporary.close()
        if _path_exists(temporary.path):
            _unlink_with_retries(temporary.path, temporary.identity)
        operation[field] = None
        operation[f"{field}_identity"] = None
        raise


def _copy_original_to_backup(
    operation: Mapping[str, object], backup: _SecureTemp
) -> None:
    target = Path(str(operation["target"]))
    original_identity = _identity_from_data(operation["original_identity"])
    if original_identity is None:
        raise RuntimeError("Backup requested without an original file")
    source_descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        if _identity_from_stat(os.fstat(source_descriptor)) != original_identity:
            raise RuntimeError(f"Managed target changed before backup: {target}")
        while chunk := os.read(source_descriptor, 1024 * 1024):
            _write_all(backup.descriptor, chunk)
        if _identity_from_stat(os.fstat(source_descriptor)) != original_identity:
            raise RuntimeError(f"Managed target changed during backup: {target}")
    finally:
        os.close(source_descriptor)
    mode = operation["original_mode"]
    if isinstance(mode, int) and os.name != "nt" and hasattr(os, "fchmod"):
        os.fchmod(backup.descriptor, mode)
    os.fsync(backup.descriptor)
    if _descriptor_digest(backup.descriptor) != (
        int(operation["original_size"]),
        str(operation["original_sha256"]),
    ):
        raise RuntimeError(f"Transaction backup verification failed: {target}")


def _copy_staged_for_application(
    operation: Mapping[str, object],
    staged_path: Path,
    staged_identity: _PathIdentity,
    application: _SecureTemp,
) -> None:
    source_descriptor = os.open(
        staged_path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
    )
    try:
        source_stat = os.fstat(source_descriptor)
        if _identity_from_stat(source_stat) != staged_identity:
            raise RuntimeError(f"Staged artifact changed before application: {staged_path}")
        while chunk := os.read(source_descriptor, 1024 * 1024):
            _write_all(application.descriptor, chunk)
        if _identity_from_stat(os.fstat(source_descriptor)) != staged_identity:
            raise RuntimeError(f"Staged artifact changed during application: {staged_path}")
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(application.descriptor, stat.S_IMODE(source_stat.st_mode))
    finally:
        os.close(source_descriptor)
    os.fsync(application.descriptor)
    if _descriptor_digest(application.descriptor) != (
        int(operation["new_size"]),
        str(operation["new_sha256"]),
    ):
        raise RuntimeError(f"Application artifact verification failed: {staged_path}")


def _verify_change_original(
    change: FileChange,
) -> tuple[_PathIdentity | None, int | None, str | None]:
    target = change.target
    if change.expected_original_absent:
        if any(
            value is not None
            for value in (
                change.expected_original_identity,
                change.expected_original_size,
                change.expected_original_sha256,
            )
        ):
            raise RuntimeError(f"File change has conflicting original state: {target}")
        _assert_safe_file(target)
        if _path_exists(target):
            raise RuntimeError(f"Managed target appeared after planning: {target}")
        return None, None, None
    if (
        change.expected_original_identity is None
        or change.expected_original_size is None
        or change.expected_original_sha256 is None
    ):
        raise RuntimeError(f"File change lacks a plan-time original state: {target}")
    identity = _verified_file_identity(
        target,
        change.expected_original_size,
        change.expected_original_sha256,
    )
    if identity != change.expected_original_identity:
        raise RuntimeError(f"Managed target identity changed after planning: {target}")
    return identity, change.expected_original_size, change.expected_original_sha256


def _apply_file_transaction(
    changes: Sequence[FileChange],
    deletions: Sequence[FileDeletion] = (),
    *,
    required_directories: Sequence[Path] = (),
    journal_path: Path | None = None,
    transaction_roots: Sequence[Path] = (),
    allowed_targets: Sequence[Path] = (),
) -> None:
    first_target = next(
        (change.target for change in changes),
        next((deletion.target for deletion in deletions), None),
    )
    if first_target is None:
        return
    if journal_path is None:
        journal_path = first_target.parent / TRANSACTION_JOURNAL_NAME
    roots = tuple(transaction_roots) or (journal_path.parent,)
    manifest_license_targets = _transaction_manifest_license_targets(changes, roots)
    manifest_license_keys = {_path_key(path) for path in manifest_license_targets}
    state_script_targets = _transaction_state_script_targets(changes, roots)
    state_script_keys = {_path_key(path) for path in state_script_targets}
    transaction_id = uuid.uuid4().hex
    created_directories: set[Path] = set()
    ordered_specs: list[tuple[str, FileChange | FileDeletion]] = [
        *(('replace', change) for change in changes if not change.commit_marker),
        *(('delete', deletion) for deletion in deletions),
        *(('replace', change) for change in changes if change.commit_marker),
    ]
    journal_data: dict[str, object] | None = None
    _assert_safe_file(journal_path)
    _cleanup_abandoned_journal_temps(journal_path.parent, journal_path)
    if _path_exists(journal_path):
        raise RuntimeError(f"An installer transaction journal already exists: {journal_path}")
    try:
        deferred_license_operations = bool(manifest_license_keys) and any(
            isinstance(spec, FileChange)
            and _path_key(spec.target) == _path_key(roots[0] / MANIFEST_NAME)
            for _, spec in ordered_specs
        )
        deferred_script_operations = bool(state_script_keys) and any(
            isinstance(spec, FileChange)
            and _path_key(spec.target) == _path_key(roots[0] / INSTALL_STATE_NAME)
            for _, spec in ordered_specs
        )
        deferred_target_keys: set[str] = set()
        if deferred_license_operations:
            deferred_target_keys.update(manifest_license_keys)
        if deferred_script_operations:
            deferred_target_keys.update(state_script_keys)
        initial_specs = [
            entry
            for entry in ordered_specs
            if _path_key(entry[1].target) not in deferred_target_keys
        ]
        _ensure_directory(journal_path.parent, created_directories, roots)
        for _, spec in initial_specs:
            _ensure_directory(spec.target.parent, created_directories, roots)
        entries: list[
            tuple[tuple[str, FileChange | FileDeletion], dict[str, object]]
        ] = []
        target_keys: set[str] = set()
        for operation_type, spec in ordered_specs:
            target = spec.target
            if not _target_is_managed(
                target,
                roots,
                allowed_targets,
                manifest_license_targets,
                state_script_targets,
            ):
                raise RuntimeError(f"Unsafe installer transaction target: {target}")
            if _path_key(target) in target_keys:
                raise RuntimeError("Installer transaction contains duplicate targets")
            target_keys.add(_path_key(target))
            _assert_safe_file(target)
            if isinstance(spec, FileDeletion):
                identity = _verified_file_identity(
                    target, spec.expected_size, spec.expected_sha256
                )
                if identity != spec.expected_identity:
                    raise RuntimeError(f"Deletion target identity changed: {target}")
                original_size = spec.expected_size
                original_sha256 = spec.expected_sha256
                new_size = new_sha256 = None
            else:
                identity, original_size, original_sha256 = _verify_change_original(spec)
                if spec.expected_size is None or spec.expected_sha256 is None:
                    raise RuntimeError(f"File change lacks an expected digest: {target}")
                new_size = spec.expected_size
                new_sha256 = spec.expected_sha256
            original_mode = (
                stat.S_IMODE(target.stat().st_mode) if identity is not None else None
            )
            entries.append(
                (
                    (operation_type, spec),
                    _operation_record(
                        operation_type,
                        target,
                        identity,
                        original_mode,
                        original_size,
                        original_sha256,
                        new_size,
                        new_sha256,
                    ),
                )
            )
        initial_target_keys = {_path_key(spec.target) for _, spec in initial_specs}
        records: list[dict[str, object]] = [
            operation
            for (_, spec), operation in entries
            if _path_key(spec.target) in initial_target_keys
        ]
        journal_data = {
            "schema": TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "phase": "active",
            "roots": [os.path.abspath(os.fspath(root)) for root in roots],
            "created_directories": [
                os.path.abspath(os.fspath(directory))
                for directory in sorted(created_directories, key=lambda path: len(path.parts))
            ],
            "operations": records,
        }
        _write_journal(journal_path, journal_data)

        def stage_replacement(
            spec: FileChange, operation: dict[str, object]
        ) -> None:
            artifact_directory = _stable_artifact_directory(
                spec.target, tuple(created_directories), journal_path.parent
            )
            staged = _temporary_file(
                spec.target,
                "new",
                transaction_id=transaction_id,
                directory=artifact_directory,
            )
            _register_temp(operation, "staged", staged, journal_path, journal_data)
            try:
                _prepare_change(spec, staged)
                _verify_staged_change(spec, staged)
                staged.close()
                verified = _verified_file_identity(
                    staged.path,
                    int(operation["new_size"]),
                    str(operation["new_sha256"]),
                )
                if verified != staged.identity:
                    raise RuntimeError(f"Staged payload identity changed: {spec.target}")
                _publish_artifact(staged.path, staged.identity)
                operation["state"] = "staged"
                _write_journal(journal_path, journal_data)
            finally:
                staged.close()

        if deferred_license_operations:
            manifest_entry = next(
                (
                    (spec, operation)
                    for (_, spec), operation in entries
                    if isinstance(spec, FileChange)
                    and _path_key(spec.target) == _path_key(roots[0] / MANIFEST_NAME)
                ),
                None,
            )
            if manifest_entry is None:
                raise RuntimeError("License transaction lacks a manifest artifact")
            stage_replacement(*manifest_entry)

        if deferred_script_operations:
            state_entry = next(
                (
                    (spec, operation)
                    for (_, spec), operation in entries
                    if isinstance(spec, FileChange)
                    and _path_key(spec.target)
                    == _path_key(roots[0] / INSTALL_STATE_NAME)
                ),
                None,
            )
            if state_entry is None:
                raise RuntimeError("Resolve script transaction lacks an install-state artifact")
            stage_replacement(*state_entry)

        if deferred_license_operations or deferred_script_operations:
            records[:] = [operation for _, operation in entries]
            _write_journal(journal_path, journal_data)
            for (_, spec), _ in entries:
                if _path_key(spec.target) in deferred_target_keys:
                    _ensure_directory(spec.target.parent, created_directories, roots)
            journal_data["created_directories"] = [
                os.path.abspath(os.fspath(directory))
                for directory in sorted(created_directories, key=lambda path: len(path.parts))
            ]
            _write_journal(journal_path, journal_data)

        for (operation_type, spec), operation in entries:
            if operation_type != "replace" or not isinstance(spec, FileChange):
                continue
            if operation["state"] != "staged":
                stage_replacement(spec, operation)

        for operation in records:
            target = Path(str(operation["target"]))
            parent_snapshot = _capture_directory_snapshot(target.parent)
            original_identity = _identity_from_data(operation["original_identity"])
            if original_identity is not None:
                current = _verified_file_identity(
                    target,
                    int(operation["original_size"]),
                    str(operation["original_sha256"]),
                )
                if current != original_identity:
                    raise RuntimeError(f"Managed target changed before mutation: {target}")
                backup = _temporary_file(
                    target, "backup", transaction_id=transaction_id
                )
                _register_temp(operation, "backup", backup, journal_path, journal_data)
                try:
                    _copy_original_to_backup(operation, backup)
                    backup.close()
                    verified = _verified_file_identity(
                        backup.path,
                        int(operation["original_size"]),
                        str(operation["original_sha256"]),
                    )
                    if verified != backup.identity:
                        raise RuntimeError(f"Backup identity changed: {target}")
                    _publish_artifact(backup.path, backup.identity)
                finally:
                    backup.close()
            operation["state"] = "ready"
            _write_journal(journal_path, journal_data)
            if operation["type"] == "replace":
                staged, staged_identity = _verified_artifact(operation, "staged", "new")
                application: _SecureTemp | None = None
                replacement = staged
                replacement_identity = staged_identity
                try:
                    if staged.parent != target.parent:
                        application = _temporary_file(
                            target,
                            "apply",
                            transaction_id=transaction_id,
                            directory=staged.parent,
                        )
                        _copy_staged_for_application(
                            operation, staged, staged_identity, application
                        )
                        application.close()
                        replacement_identity = _verified_file_identity(
                            application.path,
                            int(operation["new_size"]),
                            str(operation["new_sha256"]),
                        )
                        if replacement_identity != application.identity:
                            raise RuntimeError(
                                f"Application artifact identity changed: {target}"
                            )
                        _publish_artifact(application.path, application.identity)
                        replacement = application.path
                        operation["applied_identity"] = _identity_data(
                            replacement_identity
                        )
                        _write_journal(journal_path, journal_data)
                    _safe_replace(
                        replacement,
                        target,
                        parent_snapshot=parent_snapshot,
                        source_identity=replacement_identity,
                        target_identity=original_identity,
                    )
                finally:
                    if application is not None:
                        application.close()
                        if _path_exists(application.path):
                            _unlink_with_retries(
                                application.path, application.identity
                            )
            elif original_identity is not None:
                _safe_unlink(
                    target,
                    parent_snapshot=parent_snapshot,
                    expected_identity=original_identity,
                )
            operation["state"] = "applied"
            _write_journal(journal_path, journal_data)

        journal_data["phase"] = "committed"
        _write_journal(journal_path, journal_data)
        for directory in required_directories:
            _ensure_directory(directory, set(), roots)
    except BaseException as exc:
        try:
            if _path_exists(journal_path):
                _recover_transaction(
                    journal_path, roots, allowed_targets=allowed_targets
                )
            else:
                for directory in sorted(
                    created_directories,
                    key=lambda path: len(path.parts),
                    reverse=True,
                ):
                    _remove_directory_if_empty(directory)
        except BaseException:
            raise RuntimeError(
                "Installer transaction failed and recovery is incomplete; journal retained"
            ) from exc
        raise
    if journal_data is None:
        return
    try:
        for operation in records:
            _finish_committed_operation(operation, journal_data, roots)
        _, journal_identity = _load_transaction_journal(
            journal_path, roots, allowed_targets
        )
        _cleanup_transaction_artifacts(journal_data)
        _unlink_with_retries(journal_path, journal_identity)
    except BaseException as exc:
        raise RuntimeError(
            "Installer transaction committed but cleanup is incomplete; journal retained"
        ) from exc


def _license_directories(target_root: Path, license_paths: Sequence[Path]) -> set[Path]:
    license_root = target_root / "licenses"
    directories = {license_root}
    for relative_path in license_paths:
        for depth in range(1, len(relative_path.parts)):
            directories.add(license_root.joinpath(*relative_path.parts[:depth]))
    return directories


def _remove_directory_if_empty(path: Path) -> None:
    _assert_safe_directory(path)
    if not path.is_dir():
        return
    try:
        path.rmdir()
    except FileNotFoundError:
        pass
    except OSError as exc:
        if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise


def _prune_license_directories(target_root: Path, license_paths: Sequence[Path]) -> None:
    for directory in sorted(
        _license_directories(target_root, license_paths),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        _remove_directory_if_empty(directory)


def _prune_absent_install_license_directories(target_root: Path) -> None:
    license_root = target_root / "licenses"
    if not _path_exists(license_root) or _is_link_or_junction(license_root):
        return
    _assert_safe_directory(license_root)
    if not license_root.is_dir():
        return

    def prune(directory: Path) -> None:
        _assert_safe_directory(directory)
        with os.scandir(directory) as entries:
            children = tuple(entries)
        for entry in children:
            child = Path(entry.path)
            if _is_link_or_junction(child):
                continue
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if is_directory:
                prune(child)
        if directory != license_root:
            _remove_directory_if_empty(directory)

    prune(license_root)


def _cleanup_known_empty_install_directories(target_root: Path) -> None:
    for directory in (target_root / "licenses", target_root / "tmp"):
        if _path_exists(directory) and _is_link_or_junction(directory):
            continue
        _remove_directory_if_empty(directory)
    _remove_directory_if_empty(target_root)


def install_from_plan(
    plan: InstallPlan,
    target_root: Path,
    script_dir: Path | None = None,
) -> tuple[Path, ...]:
    if script_dir is None:
        script_dir = next(
            change.target.parent
            for change in plan.changes
            if change.target.name == PLUGIN_SCRIPT_NAME
        )
    _apply_file_transaction(
        plan.changes,
        plan.deletions,
        required_directories=plan.required_directories,
        journal_path=target_root / TRANSACTION_JOURNAL_NAME,
        transaction_roots=(target_root, *plan.script_directories),
    )
    _prune_license_directories(target_root, plan.stale_license_paths)
    return tuple(change.target for change in plan.changes)


def uninstall_from_plan(
    plan: UninstallPlan,
    target_root: Path,
    script_dir: Path | None = None,
) -> None:
    if plan.absent:
        _prune_absent_install_license_directories(target_root)
        _cleanup_known_empty_install_directories(target_root)
        return
    if script_dir is None:
        script_dir = next(
            (
                path.parent
                for path in plan.files
                if path.name in {PLUGIN_SCRIPT_NAME, LEGACY_PLUGIN_SCRIPT_NAME}
            ),
            target_root,
        )
    _apply_file_transaction(
        (),
        plan.deletions,
        journal_path=target_root / TRANSACTION_JOURNAL_NAME,
        transaction_roots=(target_root, *plan.script_directories),
    )
    _prune_license_directories(target_root, plan.license_paths)
    _cleanup_known_empty_install_directories(target_root)


def copy_required_file(source: Path, target: Path, *, executable: bool = False) -> Path:
    _assert_safe_file(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    journal_path = target.parent / TRANSACTION_JOURNAL_NAME
    if journal_path.is_file():
        _recover_transaction(
            journal_path,
            (target.parent,),
            allowed_targets=(target,),
        )
    source_size = source.stat().st_size
    source_sha256 = _sha256_file(source)
    (
        original_identity,
        original_size,
        original_sha256,
        original_absent,
    ) = _planned_original(target)
    _apply_file_transaction(
        (
            FileChange(
                target=target,
                source=source,
                executable=executable,
                expected_size=source_size,
                expected_sha256=source_sha256,
                expected_original_identity=original_identity,
                expected_original_size=original_size,
                expected_original_sha256=original_sha256,
                expected_original_absent=original_absent,
            ),
        ),
        journal_path=journal_path,
        transaction_roots=(target.parent,),
        allowed_targets=(target,),
    )
    return target


def _normalized_windows_path(path: str | Path) -> str:
    value = os.path.expandvars(os.fspath(path)).strip()
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


def _is_managed_windows_executable(path: str | Path, expected_paths: set[str]) -> bool:
    return _normalized_windows_path(path) in expected_paths


def _windows_process_ids() -> tuple[int, ...]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", wintypes.WPARAM),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    snapshot = create_snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return ()
    process_ids: list[int] = []
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not process_first(snapshot, ctypes.byref(entry)):
            return ()
        while True:
            process_ids.append(int(entry.th32ProcessID))
            if not process_next(snapshot, ctypes.byref(entry)):
                break
    finally:
        close_handle(snapshot)
    return tuple(process_ids)


def _wait_for_windows_process_exit(
    wait_for_process: object, handle: object, pid: int
) -> None:
    wait_result = int(wait_for_process(handle, 5000))
    if wait_result == 0x00000102:
        raise RuntimeError(f"Timed out waiting for managed process {pid} to exit")
    if wait_result != 0x00000000:
        import ctypes

        raise OSError(ctypes.get_last_error(), f"Unable to wait for managed process {pid}")


def _terminate_windows_process_if_managed(pid: int, expected_paths: set[str]) -> bool:
    import ctypes
    from ctypes import wintypes

    if pid in {0, os.getpid()}:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_image.restype = wintypes.BOOL
    terminate_process = kernel32.TerminateProcess
    terminate_process.argtypes = [wintypes.HANDLE, wintypes.UINT]
    terminate_process.restype = wintypes.BOOL
    wait_for_process = kernel32.WaitForSingleObject
    wait_for_process.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_process.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(0x1000 | 0x0001 | 0x00100000, False, pid)
    if not handle:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not query_image(handle, 0, buffer, ctypes.byref(size)):
            return False
        if not _is_managed_windows_executable(buffer.value, expected_paths):
            return False
        if not terminate_process(handle, 1):
            raise OSError(ctypes.get_last_error(), f"Unable to terminate managed process {pid}")
        _wait_for_windows_process_exit(wait_for_process, handle, pid)
        return True
    finally:
        close_handle(handle)


def stop_existing_processes(target_root: Path) -> None:
    if os.name != "nt":
        return
    expected_paths = {
        _normalized_windows_path(target_root / name)
        for name in (ENGINE_NAME, RUNNER_NAME, FFMPEG_NAME, FFPROBE_NAME)
    }
    for pid in _windows_process_ids():
        _terminate_windows_process_if_managed(pid, expected_paths)


def _windows_command_executable(command: object) -> str | None:
    if not isinstance(command, str):
        return None
    value = os.path.expandvars(command).strip()
    if not value:
        return None
    if value.startswith('"'):
        closing_quote = value.find('"', 1)
        if closing_quote < 0:
            return None
        executable = value[1:closing_quote]
    else:
        executable = value.split(maxsplit=1)[0]
    windows_path = PureWindowsPath(executable)
    if not windows_path.is_absolute() or not windows_path.drive:
        return None
    return executable


def _runner_command_targets_root(command: object, target_root: Path) -> bool:
    executable = _windows_command_executable(command)
    if executable is None:
        return False
    return _normalized_windows_path(executable) == _normalized_windows_path(
        target_root / RUNNER_NAME
    )


def unregister_runner_autostart(target_root: Path) -> None:
    if os.name != "nt":
        return
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                command, _ = winreg.QueryValueEx(key, RUN_KEY_NAME)
            except FileNotFoundError:
                return
            if _runner_command_targets_root(command, target_root):
                winreg.DeleteValue(key, RUN_KEY_NAME)
    except FileNotFoundError:
        pass


class LocalizedArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: object, language: str, **kwargs: object) -> None:
        self.language = language
        super().__init__(*args, **kwargs)

    def _localize_usage(self, text: str) -> str:
        return text.replace(
            "usage: ", f"{message('argparse_usage', self.language)}: ", 1
        )

    def format_usage(self) -> str:
        return self._localize_usage(super().format_usage())

    def format_help(self) -> str:
        return self._localize_usage(super().format_help())

    def error(self, error_message: str) -> None:
        unrecognized = "unrecognized arguments: "
        if error_message.startswith(unrecognized):
            error_message = message(
                "argparse_error_unrecognized",
                self.language,
                arguments=error_message.removeprefix(unrecognized),
            )
        else:
            missing_value = re.fullmatch(r"argument (.+): expected one argument", error_message)
            if missing_value:
                error_message = message(
                    "argparse_error_expected_value",
                    self.language,
                    argument=missing_value.group(1),
                )
        self.print_usage(sys.stderr)
        self.exit(
            2,
            f"{self.prog}: {message('argparse_error', self.language)}: {error_message}\n",
        )


def build_parser(language: str = DEFAULT_LANGUAGE) -> argparse.ArgumentParser:
    parser = LocalizedArgumentParser(
        language=language,
        description=message("argparse_description", language),
        add_help=False,
    )
    parser._optionals.title = message("argparse_options", language)
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        help=message("help_help", language),
    )

    def parse_language(value: str) -> str:
        if value not in (AUTO_LANGUAGE, *SUPPORTED_LANGUAGES):
            raise argparse.ArgumentTypeError(
                message("argparse_error_invalid_language", language, value=value)
            )
        return value

    parser.add_argument(
        "--language",
        default=AUTO_LANGUAGE,
        type=parse_language,
        metavar="{auto,en,ru}",
        help=message("help_language", language),
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        help=message("help_install_root", language),
    )
    parser.add_argument(
        "--resolve-script-dir",
        type=Path,
        help=message("help_resolve_script_dir", language),
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help=message("help_uninstall", language),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=message("help_dry_run", language),
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help=message("help_no_pause", language),
    )
    parser.add_argument(
        "--result-file",
        type=Path,
        help=message("help_result_file", language),
    )
    return parser


def _language_from_argv(argv: Sequence[str]) -> str:
    requested = AUTO_LANGUAGE
    for index, argument in enumerate(argv):
        if argument == "--language" and index + 1 < len(argv):
            requested = argv[index + 1]
        elif argument.startswith("--language="):
            requested = argument.partition("=")[2]
    if requested not in (AUTO_LANGUAGE, *SUPPORTED_LANGUAGES):
        return AUTO_LANGUAGE
    return requested


def _pause_if_needed(no_pause: bool, language: str = DEFAULT_LANGUAGE) -> None:
    if no_pause or os.environ.get("TVIZ_NO_PAUSE") == "1" or not sys.stdin.isatty():
        return
    input(message("pause_prompt", language))


def write_result_file(path: Path | None, *, ok: bool, version: str | None, error: str | None) -> None:
    """Atomically record the outcome for a caller that cannot read the console (self-update)."""
    if path is None:
        return
    payload = {"ok": ok, "version": version, "error": error}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def _payload_version(source_dir: Path) -> str | None:
    try:
        data = json.loads((source_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


def main(argv: list[str] | None = None) -> int:
    configure_unicode_console()
    command_line = list(sys.argv[1:] if argv is None else argv)
    language = resolve_language(_language_from_argv(command_line))
    args = build_parser(language).parse_args(command_line)
    language = resolve_language(args.language)
    version = _payload_version(resource_root())
    try:
        exit_code = _run(args, language)
    except Exception as exc:
        write_result_file(args.result_file, ok=False, version=version, error=str(exc))
        raise
    write_result_file(args.result_file, ok=exit_code == 0, version=version, error=None)
    return exit_code


def _run(args: argparse.Namespace, language: str) -> int:
    source_dir = resource_root()
    target_root = _absolute_path(args.install_root or default_install_root())
    script_dir = _absolute_path(args.resolve_script_dir or default_resolve_scripts_dir())
    _recover_stale_transaction(target_root, script_dir, dry_run=args.dry_run)

    if args.uninstall:
        print(message("uninstall_start", language))
        print(message("install_application_directory", language, path=target_root))
        print(message("install_resolve_script_directory", language, path=script_dir))
        plan = build_uninstall_plan(target_root, script_dir)
        if args.dry_run:
            print(message("dry_run_uninstall_complete", language, files=len(plan.files)))
            return 0

        unregister_runner_autostart(target_root)
        if not plan.absent:
            print(message("stopping_processes", language))
            stop_existing_processes(target_root)
        uninstall_from_plan(plan, target_root, script_dir)
        print(message("uninstall_complete", language))
        _pause_if_needed(args.no_pause, language)
        return 0

    print(message("install_start", language))
    print(message("install_application_directory", language, path=target_root))
    print(message("install_resolve_script_directory", language, path=script_dir))
    plan = build_install_plan(source_dir, target_root, script_dir, language=language)
    if args.dry_run:
        print(message("dry_run_complete", language))
        return 0

    print(message("stopping_processes", language))
    stop_existing_processes(target_root)
    unregister_runner_autostart(target_root)
    install_from_plan(plan, target_root, script_dir)

    for change in plan.changes:
        print(message("install_file", language, component=change.label, path=change.target))
    print(message("runner_behavior", language))
    print(message("install_complete", language))
    print(message("restart_resolve", language))
    _pause_if_needed(args.no_pause, language)
    return 0


if __name__ == "__main__":
    configure_unicode_console()
    cli_arguments = sys.argv[1:]
    cli_language = resolve_language(_language_from_argv(cli_arguments))
    no_pause_requested = "--no-pause" in cli_arguments or os.environ.get("TVIZ_NO_PAUSE") == "1"
    try:
        exit_code = main(cli_arguments)
    except Exception as exc:
        print(message("fatal_error", cli_language, error=exc), file=sys.stderr)
        _pause_if_needed(no_pause_requested, cli_language)
        raise SystemExit(1) from None
    raise SystemExit(exit_code)
