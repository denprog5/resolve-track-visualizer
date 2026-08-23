from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path


PRODUCT_DIRECTORY = "DavinciTrackVisualizer"
HOME_ENV = "DAVINCI_TRACK_VISUALIZER_HOME"
RESOLVE_SCRIPTS_ENV = "DAVINCI_TRACK_VISUALIZER_RESOLVE_SCRIPTS"


def platform_name(system: str | None = None) -> str:
    value = (system or platform.system()).strip().lower()
    if value.startswith("win"):
        return "windows"
    if value in {"darwin", "mac", "macos"}:
        return "macos"
    if value == "linux":
        return "linux"
    raise RuntimeError(f"Unsupported platform: {system or platform.system()}")


def executable_name(base_name: str, system: str | None = None) -> str:
    return f"{base_name}.exe" if platform_name(system) == "windows" else base_name


def install_root(
    *,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    override = env.get(HOME_ENV)
    if override:
        return Path(override).expanduser()

    user_home = Path(home).expanduser() if home is not None else Path.home()
    target = platform_name(system)
    if target == "windows":
        base = Path(env.get("LOCALAPPDATA") or user_home / "AppData" / "Local")
        return base / PRODUCT_DIRECTORY
    if target == "macos":
        return user_home / "Library" / "Application Support" / PRODUCT_DIRECTORY
    base = Path(env.get("XDG_DATA_HOME") or user_home / ".local" / "share")
    return base / PRODUCT_DIRECTORY


def resolve_scripts_dir(
    *,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    override = env.get(RESOLVE_SCRIPTS_ENV)
    if override:
        return Path(override).expanduser()

    user_home = Path(home).expanduser() if home is not None else Path.home()
    target = platform_name(system)
    if target == "windows":
        base = Path(env.get("APPDATA") or user_home / "AppData" / "Roaming")
        return base / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Utility"
    if target == "macos":
        return (
            user_home
            / "Library"
            / "Application Support"
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Fusion"
            / "Scripts"
            / "Utility"
        )
    return user_home / ".local" / "share" / "DaVinciResolve" / "Fusion" / "Scripts" / "Utility"
