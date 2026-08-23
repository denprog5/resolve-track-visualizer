from __future__ import annotations

import argparse
import locale
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

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
DEFAULT_LANGUAGE = "en"
AUTO_LANGUAGE = "auto"
SUPPORTED_LANGUAGES = ("en", "ru")
LANGUAGE_OVERRIDE_ENV = "TVIZ_UI_LANG"

MESSAGE_CATALOGS = {
    "en": {
        "argparse_description": "Install DaVinci Track Visualizer for the current user",
        "argparse_error": "error",
        "argparse_error_expected_value": "argument {argument}: expected one value",
        "argparse_error_invalid_language": (
            "invalid value {value!r}; choose auto, en, or ru"
        ),
        "argparse_error_unrecognized": "unrecognized arguments: {arguments}",
        "argparse_options": "options",
        "argparse_usage": "usage",
        "dry_run_complete": (
            "Dry run complete: packaged resources are valid; no files were changed."
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
    },
    "ru": {
        "argparse_description": (
            "Установить DaVinci Track Visualizer для текущего пользователя"
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
            "Проверка завершена: ресурсы установщика корректны; файлы не изменены."
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


def validate_resources(source_dir: Path, *, language: str = DEFAULT_LANGUAGE) -> None:
    missing = [path for path in required_resources(source_dir) if not path.is_file()]
    if missing:
        formatted = "\n".join(f"  {path}" for path in missing)
        raise FileNotFoundError(message("resources_missing", language, paths=formatted))


def copy_required_file(source: Path, target: Path, *, executable: bool = False) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error: PermissionError | None = None
    for _ in range(10):
        try:
            shutil.copy2(source, target)
            if executable and os.name != "nt":
                target.chmod(stat.S_IMODE(target.stat().st_mode) | 0o755)
            return target
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error is not None:
        raise last_error
    return target


def install_resolve_script(source_dir: Path, target_root: Path, script_dir: Path) -> Path:
    source = source_dir / RESOURCE_DIRECTORY / PLUGIN_SCRIPT_NAME
    if not source.is_file():
        raise FileNotFoundError(source)

    script_dir.mkdir(parents=True, exist_ok=True)
    target = script_dir / PLUGIN_SCRIPT_NAME
    legacy_target = script_dir / LEGACY_PLUGIN_SCRIPT_NAME

    content = source.read_text(encoding="utf-8")
    replacements = {
        "__INSTALL_ROOT__": str(target_root),
        "__ENGINE_EXECUTABLE__": str(target_root / ENGINE_NAME),
        "__RUNNER_EXECUTABLE__": str(target_root / RUNNER_NAME),
        "__FFMPEG_EXECUTABLE__": str(target_root / FFMPEG_NAME),
        "__FFPROBE_EXECUTABLE__": str(target_root / FFPROBE_NAME),
    }
    for marker, value in replacements.items():
        content = content.replace(marker, value)
    target.write_text(content, encoding="utf-8", newline="\n")
    if legacy_target.exists():
        legacy_target.unlink()
    return target


def _creationflags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def stop_existing_processes() -> None:
    if os.name != "nt":
        return
    for image_name in (RUNNER_NAME, ENGINE_NAME):
        subprocess.run(
            ["taskkill.exe", "/F", "/T", "/IM", image_name],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
            check=False,
        )
    time.sleep(0.5)


def unregister_runner_autostart() -> None:
    if os.name != "nt":
        return
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, RUN_KEY_NAME)
            except FileNotFoundError:
                pass
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
        "--dry-run",
        action="store_true",
        help=message("help_dry_run", language),
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help=message("help_no_pause", language),
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


def main(argv: list[str] | None = None) -> int:
    configure_unicode_console()
    command_line = list(sys.argv[1:] if argv is None else argv)
    language = resolve_language(_language_from_argv(command_line))
    args = build_parser(language).parse_args(command_line)
    language = resolve_language(args.language)
    source_dir = resource_root()
    target_root = (args.install_root or default_install_root()).expanduser().resolve()
    script_dir = (args.resolve_script_dir or default_resolve_scripts_dir()).expanduser().resolve()
    validate_resources(source_dir, language=language)

    print(message("install_start", language))
    print(message("install_application_directory", language, path=target_root))
    print(message("install_resolve_script_directory", language, path=script_dir))
    if args.dry_run:
        print(message("dry_run_complete", language))
        return 0

    target_root.mkdir(parents=True, exist_ok=True)
    (target_root / "tmp").mkdir(parents=True, exist_ok=True)
    print(message("stopping_processes", language))
    stop_existing_processes()
    unregister_runner_autostart()

    installed = {
        "Engine": copy_required_file(
            source_dir / BIN_DIRECTORY / ENGINE_NAME,
            target_root / ENGINE_NAME,
            executable=True,
        ),
        "Runner": copy_required_file(
            source_dir / BIN_DIRECTORY / RUNNER_NAME,
            target_root / RUNNER_NAME,
            executable=True,
        ),
        "FFmpeg": copy_required_file(
            source_dir / BIN_DIRECTORY / FFMPEG_NAME,
            target_root / FFMPEG_NAME,
            executable=True,
        ),
        "FFprobe": copy_required_file(
            source_dir / BIN_DIRECTORY / FFPROBE_NAME,
            target_root / FFPROBE_NAME,
            executable=True,
        ),
        "Logo": copy_required_file(
            source_dir / RESOURCE_DIRECTORY / LOGO_NAME,
            target_root / LOGO_NAME,
        ),
        "Notices": copy_required_file(source_dir / NOTICE_NAME, target_root / NOTICE_NAME),
        "License": copy_required_file(source_dir / "LICENSE", target_root / "LICENSE"),
        "Manifest": copy_required_file(source_dir / MANIFEST_NAME, target_root / MANIFEST_NAME),
    }
    licenses = source_dir / "licenses"
    if licenses.is_dir():
        for license_path in sorted(licenses.iterdir()):
            if license_path.is_file():
                copy_required_file(license_path, target_root / "licenses" / license_path.name)
    installed["Resolve script"] = install_resolve_script(source_dir, target_root, script_dir)

    for label, path in installed.items():
        print(message("install_file", language, component=label, path=path))
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
