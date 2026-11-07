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


def _is_ascii(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _windows_short_path(path: Path) -> str | None:
    """8.3 short form of an existing path, or None when unavailable."""
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    if not 0 < length < len(buffer):
        return None
    return buffer.value


def _posix_private_dir(path: Path) -> Path | None:
    """``path`` as a directory owned by this user with no group/other access, or None."""
    import stat

    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        return None
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        return None
    return path


def comp_staging_dir(
    preferred: Path,
    *,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Directory for Fusion ``.comp`` files that Resolve imports.

    ``TimelineItem:ImportFusionComp`` rejected comp paths with non-ASCII characters during
    host testing (Resolve Studio 20.2.1, Windows), which is common for user profile folders.
    Comps contain expressions that Resolve evaluates, so they are never staged in a location
    other local users can write to:

    * Windows: only the 8.3 short form of ``preferred`` (same folder, same permissions). Shared
      roots such as ProgramData are never used: their parent folders can be pre-created and
      swapped by another user.
    * POSIX: ``$XDG_RUNTIME_DIR`` or ``/tmp``, only as a 0700 directory owned by this user.

    When nothing safe is available ``preferred`` is returned unchanged.
    """
    if _is_ascii(preferred):
        return preferred
    env = os.environ if environ is None else environ
    if platform_name(system) == "windows":
        try:
            preferred.mkdir(parents=True, exist_ok=True)
        except OSError:
            return preferred
        short = _windows_short_path(preferred)
        if short and short.isascii():
            return Path(short)
        return preferred
    import tempfile

    uid = os.getuid()
    runtime = env.get("XDG_RUNTIME_DIR", "")
    if runtime and runtime.isascii() and _posix_private_dir(Path(runtime)) is not None:
        candidate = _posix_private_dir(Path(runtime) / f"{PRODUCT_DIRECTORY}-comps")
        if candidate is not None:
            return candidate
    temp_root = Path("/tmp")
    candidate = _posix_private_dir(temp_root / f"{PRODUCT_DIRECTORY}-comps-{uid}")
    if candidate is not None:
        return candidate
    try:
        return Path(tempfile.mkdtemp(prefix=f"{PRODUCT_DIRECTORY}-comps-", dir=temp_root))
    except OSError:
        return preferred
