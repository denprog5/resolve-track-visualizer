from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from davinci_track_visualizer import __version__


PRODUCT_NAME = "DavinciTrackVisualizer"
DEFAULT_SOURCE_DATE_EPOCH = 1_704_067_200
EXECUTABLE_ROLES = ("engine", "runner", "ffmpeg", "ffprobe")
RELEASE_PYTHON_VERSION = "3.12.13"
MUTAGEN_VERSION = "1.47.0"
PILLOW_VERSION = "12.2.0"
PILLOW_LICENSE_PATH = f"pillow-{PILLOW_VERSION}.dist-info/licenses/LICENSE"
# The hash-locked Pillow CPython 3.12 wheels have identical text; Windows uses CRLF.
PILLOW_LICENSE_SHA256S = frozenset(
    {
        "13e1d5014de0064b4b1ca4d837111797673cc91a116616e3dde555009243aaf6",
        "75bb81b58f9b39786eeb2e56a1eb829aae501042d49e1dc766ca187b6ce9656f",
    }
)
MUTAGEN_SOURCE_URL = (
    "https://files.pythonhosted.org/packages/81/e6/"
    "64bc71b74eef4b68e61eb921dcf72dabd9e4ec4af1e11891bbd312ccbb77/"
    "mutagen-1.47.0.tar.gz"
)
MUTAGEN_SOURCE_SHA256 = "719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99"


@dataclass(frozen=True)
class BuildTarget:
    system: str
    architecture: str

    @property
    def tag(self) -> str:
        architecture = "x64" if self.architecture == "x86_64" else self.architecture
        return f"{self.system}-{architecture}"

    @property
    def executable_suffix(self) -> str:
        return ".exe" if self.system == "windows" else ""

    @property
    def archive_suffix(self) -> str:
        return ".zip" if self.system == "windows" else ".tar.gz"

    def executable_name(self, base_name: str) -> str:
        return f"{base_name}{self.executable_suffix}"


@dataclass(frozen=True)
class RuntimeFiles:
    engine: Path
    runner: Path
    ffmpeg: Path
    ffprobe: Path


def host_target() -> BuildTarget:
    system_value = platform.system().lower()
    system_map = {"windows": "windows", "linux": "linux", "darwin": "macos"}
    if system_value not in system_map:
        raise RuntimeError(f"Unsupported build host: {platform.system()}")

    machine_value = platform.machine().lower()
    if machine_value in {"amd64", "x86_64", "x64"}:
        architecture = "x86_64"
    elif machine_value in {"arm64", "aarch64"}:
        architecture = "arm64"
    else:
        raise RuntimeError(f"Unsupported build architecture: {platform.machine()}")

    target = BuildTarget(system_map[system_value], architecture)
    allowed = {
        ("windows", "x86_64"),
        ("linux", "x86_64"),
        ("macos", "arm64"),
        ("macos", "x86_64"),
    }
    if (target.system, target.architecture) not in allowed:
        raise RuntimeError(f"Unsupported native release target: {target.tag}")
    if struct.calcsize("P") != 8:
        raise RuntimeError("Release builds require a 64-bit Python runtime")
    return target


def validate_python_runtime(version: str = RELEASE_PYTHON_VERSION) -> None:
    actual = platform.python_version()
    if actual != version:
        raise RuntimeError(f"Release builds require Python {version}, found {actual}")


def source_date_epoch(value: int | None = None) -> int:
    if value is not None:
        return value
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    return int(configured) if configured else DEFAULT_SOURCE_DATE_EPOCH


def validate_release_environment(
    target: BuildTarget,
    version: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    env = os.environ if environ is None else environ
    requested_version = env.get("TVIZ_VERSION")
    if requested_version and requested_version != version:
        raise RuntimeError(
            f"TVIZ_VERSION {requested_version!r} does not match product version {version!r}"
        )
    requested_target = env.get("TVIZ_TARGET")
    if requested_target and requested_target != target.tag:
        raise RuntimeError(
            f"TVIZ_TARGET {requested_target!r} does not match native build host {target.tag!r}"
        )


def require_empty_release_directory(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Release output must not be a symlink: {path}")
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"Release output must be a directory: {path}")
        entries = sorted(entry.name for entry in path.iterdir())
        if entries:
            raise RuntimeError(f"Release output must be empty; refusing to remove: {entries}")
        return
    path.mkdir(parents=True)


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(shlex.join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def resolve_executable(value: str | None, name: str) -> Path:
    configured = value or os.environ.get(f"TVIZ_{name.upper()}")
    candidate = configured or name
    found = shutil.which(candidate)
    path = Path(found or candidate).expanduser()
    if not path.is_file():
        raise FileNotFoundError(
            f"{name} was not found. Supply --{name}, set TVIZ_{name.upper()}, or add it to PATH."
        )
    if os.name != "nt" and not os.access(path, os.X_OK):
        raise PermissionError(f"{name} is not executable: {path}")
    return path.resolve()


def tool_information(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        [str(path), *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or result.stderr).strip()


def validate_ffmpeg_configuration(build_configuration: str, license_text: str) -> None:
    required = {
        "--enable-gpl",
        "--enable-version3",
        "--enable-static",
        "--disable-shared",
        "--disable-autodetect",
        "--disable-everything",
        "--disable-network",
        "--disable-ffplay",
        "--disable-doc",
        "--disable-debug",
        "--disable-x86asm",
        "--pkg-config=false",
        "--enable-ffmpeg",
        "--enable-ffprobe",
        "--enable-decoder=aac,alac,flac,mp3float,opus,pcm_s16be,pcm_s16le,rawvideo,vorbis",
        "--enable-encoder=pcm_s16le,prores_ks,qtrle",
        "--enable-demuxer=aac,aiff,flac,mov,mp3,ogg,rawvideo,wav",
        "--enable-muxer=mov,s16le",
        "--enable-parser=aac,flac,mpegaudio,opus,vorbis",
        "--enable-protocol=file,pipe",
        "--enable-filter=abuffer,abuffersink,aformat,aresample,buffer,buffersink,format,scale",
    }
    configured = set(re.findall(r"--[\w-]+(?:=[^\s'\"]+)?", build_configuration))
    missing = sorted(required - configured)
    if missing:
        raise RuntimeError(f"FFmpeg is missing required release configuration: {missing}")
    prefixes = {option for option in configured if option.startswith("--prefix=")}
    if len(prefixes) != 1:
        raise RuntimeError("FFmpeg must record exactly one installation prefix")
    unexpected = sorted(configured - required - prefixes)
    if unexpected:
        raise RuntimeError(f"FFmpeg was not built with the exact release recipe: {unexpected}")
    lowered_license = license_text.lower()
    if not all(
        fragment in lowered_license
        for fragment in ("gnu general public license", "version 3", "any later version")
    ):
        raise RuntimeError("FFmpeg must report GNU GPL version 3 or later licensing")


def _listed_components(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 1:
            names.update(parts[0].split(","))
        elif len(parts) >= 2:
            names.update(parts[1].split(","))
    return names


def validate_ffmpeg_capabilities(ffmpeg: Path) -> None:
    requirements = {
        "encoders": {"pcm_s16le", "prores_ks", "qtrle"},
        "decoders": {"aac", "alac", "flac", "mp3float", "opus", "pcm_s16be", "pcm_s16le", "rawvideo", "vorbis"},
        "demuxers": {"aac", "aiff", "flac", "mov", "mp3", "ogg", "rawvideo", "wav"},
        "muxers": {"mov", "s16le"},
        "parsers": {"aac", "flac", "mpegaudio", "opus", "vorbis"},
        "filters": {"abuffer", "abuffersink", "aformat", "aresample", "buffer", "buffersink", "format", "scale"},
    }
    for category, expected in requirements.items():
        available = _listed_components(tool_information(ffmpeg, f"-{category}"))
        missing = sorted(expected - available)
        if missing:
            raise RuntimeError(f"FFmpeg is missing required {category}: {missing}")

    protocols = {
        line.strip()
        for line in tool_information(ffmpeg, "-protocols").splitlines()
        if line.strip() and not line.rstrip().endswith(":")
    }
    missing_protocols = sorted({"file", "pipe"} - protocols)
    if missing_protocols:
        raise RuntimeError(f"FFmpeg is missing required local protocols: {missing_protocols}")
    forbidden_protocols = sorted({"http", "https", "tcp", "tls", "udp"} & protocols)
    if forbidden_protocols:
        raise RuntimeError(f"Network-disabled FFmpeg exposes network protocols: {forbidden_protocols}")


def _write_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48_000)
        audio.writeframes(struct.pack("<hh", 1200, -400) * 4_800)


def _run_ffmpeg(command: list[str], label: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(command, cwd=ROOT, input=input_data, capture_output=True, check=False)
    if result.returncode != 0:
        details = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg {label} capability test failed: {details}")
    return result.stdout


def smoke_test_ffmpeg(ffmpeg: Path, ffprobe: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="tviz-ffmpeg-") as temporary_dir:
        root = Path(temporary_dir)
        wav = root / "input.wav"
        qtrle = root / "qtrle.mov"
        prores = root / "prores.mov"
        raw = bytes((220, 30, 80, 128)) * 16 * 16
        _write_test_wav(wav)

        decoded = _run_ffmpeg(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i", str(wav), "-vn",
                "-ac", "1", "-ar", "12000", "-f", "s16le", "pipe:1",
            ],
            "audio decode",
        )
        if not decoded or len(decoded) % 2:
            raise RuntimeError("FFmpeg audio decode capability test produced invalid s16le output")

        _run_ffmpeg(
            [
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
                "-pix_fmt", "rgba", "-s", "16x16", "-r", "1", "-i", "pipe:0", "-an",
                "-c:v", "qtrle", "-pix_fmt", "argb", str(qtrle),
            ],
            "raw RGBA/qtrle MOV",
            raw,
        )
        _run_ffmpeg(
            [
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
                "-pix_fmt", "rgba", "-s", "16x16", "-r", "1", "-i", "pipe:0", "-an",
                "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                str(prores),
            ],
            "rawvideo/prores_ks alpha MOV",
            raw,
        )

        duration_probe = json.loads(
            tool_information(
                ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(wav)
            )
        )
        if float(duration_probe.get("format", {}).get("duration", 0)) <= 0:
            raise RuntimeError(f"ffprobe duration capability test failed: {duration_probe}")
        tags_probe = json.loads(
            tool_information(ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(wav))
        )
        if "format" not in tags_probe:
            raise RuntimeError(f"ffprobe tag capability test failed: {tags_probe}")


def validate_ffmpeg_pair(ffmpeg: Path, ffprobe: Path, expected_release: str) -> str:
    ffmpeg_version = tool_information(ffmpeg, "-version")
    ffprobe_version = tool_information(ffprobe, "-version")
    first_ffmpeg_line = ffmpeg_version.splitlines()[0] if ffmpeg_version else ""
    first_ffprobe_line = ffprobe_version.splitlines()[0] if ffprobe_version else ""
    ffmpeg_release = first_ffmpeg_line.replace("ffmpeg version ", "", 1).split(" ", 1)[0]
    ffprobe_release = first_ffprobe_line.replace("ffprobe version ", "", 1).split(" ", 1)[0]
    if not ffmpeg_release or ffmpeg_release != ffprobe_release:
        raise RuntimeError(
            "ffmpeg and ffprobe must come from the same native build: "
            f"{first_ffmpeg_line!r} != {first_ffprobe_line!r}"
        )
    if ffmpeg_release != expected_release:
        raise RuntimeError(f"Expected FFmpeg {expected_release}, found {ffmpeg_release}")
    ffmpeg_configuration_line = next(
        (line.strip() for line in ffmpeg_version.splitlines() if line.strip().startswith("configuration:")), ""
    )
    ffprobe_configuration_line = next(
        (line.strip() for line in ffprobe_version.splitlines() if line.strip().startswith("configuration:")), ""
    )
    if not ffmpeg_configuration_line or ffmpeg_configuration_line != ffprobe_configuration_line:
        raise RuntimeError("ffmpeg and ffprobe must have the same recorded build configuration")
    build_configuration = tool_information(ffmpeg, "-buildconf")
    license_text = tool_information(ffmpeg, "-L")
    validate_ffmpeg_configuration(build_configuration, license_text)
    return f"{ffmpeg_version}\n\n{build_configuration}\n\n{license_text}\n"


def binary_architectures(path: Path) -> set[str]:
    with path.open("rb") as handle:
        header = handle.read(4096)
        if header[:2] == b"MZ" and len(header) >= 64:
            pe_offset = int.from_bytes(header[60:64], "little")
            if pe_offset + 6 > len(header):
                handle.seek(pe_offset)
                pe_header = handle.read(6)
            else:
                pe_header = header[pe_offset : pe_offset + 6]
            if pe_header[:4] != b"PE\0\0":
                return set()
            architecture = {0x8664: "x86_64", 0xAA64: "arm64"}.get(
                int.from_bytes(pe_header[4:6], "little"), "unknown"
            )
            return {architecture}

    if header[:4] == b"\x7fELF" and len(header) >= 20:
        byte_order = "little" if header[5] == 1 else "big"
        machine = int.from_bytes(header[18:20], byte_order)
        return {{62: "x86_64", 183: "arm64"}.get(machine, "unknown")}

    thin_macho = {
        b"\xcf\xfa\xed\xfe": "little",
        b"\xfe\xed\xfa\xcf": "big",
    }
    if header[:4] in thin_macho and len(header) >= 8:
        cpu_type = int.from_bytes(header[4:8], thin_macho[header[:4]])
        return {{0x01000007: "x86_64", 0x0100000C: "arm64"}.get(cpu_type, "unknown")}

    fat_macho = {
        b"\xca\xfe\xba\xbe": ("big", 20),
        b"\xbe\xba\xfe\xca": ("little", 20),
        b"\xca\xfe\xba\xbf": ("big", 32),
        b"\xbf\xba\xfe\xca": ("little", 32),
    }
    if header[:4] in fat_macho and len(header) >= 8:
        byte_order, entry_size = fat_macho[header[:4]]
        count = int.from_bytes(header[4:8], byte_order)
        architectures = set()
        for index in range(count):
            offset = 8 + index * entry_size
            if offset + 4 > len(header):
                break
            cpu_type = int.from_bytes(header[offset : offset + 4], byte_order)
            architectures.add({0x01000007: "x86_64", 0x0100000C: "arm64"}.get(cpu_type, "unknown"))
        return architectures
    return set()


def validate_native_binary(path: Path, target: BuildTarget, label: str) -> None:
    architectures = binary_architectures(path)
    if target.architecture not in architectures:
        found = ", ".join(sorted(architectures)) or "unrecognized binary format"
        raise RuntimeError(
            f"{label} is not native for {target.tag}: expected {target.architecture}, found {found} ({path})"
        )


def _distribution_notice_files(
    distribution_name: str,
    distribution: importlib.metadata.Distribution | None = None,
) -> dict[str, Path]:
    installed = distribution or importlib.metadata.distribution(distribution_name)
    result: dict[str, Path] = {}
    for entry in installed.files or ():
        relative = Path(str(entry))
        lowered_parts = tuple(part.lower() for part in relative.parts)
        lowered_name = relative.name.lower()
        in_license_directory = "licenses" in lowered_parts
        named_notice = (
            relative.suffix.lower() in {"", ".txt", ".md", ".rst"}
            and any(word in lowered_name for word in ("license", "copying", "copyright", "notice"))
        )
        if not in_license_directory and not named_notice:
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe {distribution_name} notice path: {entry}")
        source = Path(installed.locate_file(entry))
        if not source.is_file():
            raise FileNotFoundError(f"Installed {distribution_name} notice is missing: {source}")
        result[relative.as_posix()] = source
    if not result:
        raise RuntimeError(f"Installed {distribution_name} distribution has no license notices")
    return result


def _pillow_notice_files(
    distribution: importlib.metadata.Distribution | None = None,
) -> dict[str, Path]:
    installed = distribution or importlib.metadata.distribution("Pillow")
    if installed.version != PILLOW_VERSION:
        raise RuntimeError(f"Release requires Pillow {PILLOW_VERSION}, found {installed.version}")
    notices = _distribution_notice_files("Pillow", installed)
    license_path = notices.get(PILLOW_LICENSE_PATH)
    if license_path is None:
        raise RuntimeError(
            f"Pillow {PILLOW_VERSION} is missing its expected wheel notice: {PILLOW_LICENSE_PATH}"
        )
    digest = hashlib.sha256(license_path.read_bytes()).hexdigest()
    if digest not in PILLOW_LICENSE_SHA256S:
        raise RuntimeError(
            f"Pillow {PILLOW_VERSION} has an unrecognized license payload: {digest}"
        )
    return notices


def python_license_file(prefixes: tuple[Path, ...] | None = None) -> Path:
    if prefixes is None:
        prefixes = tuple(
            Path(value)
            for value in (sys.base_prefix, sys.prefix, sys.base_exec_prefix, sys.exec_prefix)
        )
    python_minor = ".".join(RELEASE_PYTHON_VERSION.split(".")[:2])
    relative_candidates = (
        Path("LICENSE.txt"),
        Path("LICENSE"),
        Path("lib") / f"python{python_minor}" / "LICENSE.txt",
        Path("lib") / f"python{python_minor}" / "LICENSE",
        Path("Lib") / "LICENSE.txt",
        Path("Lib") / "LICENSE",
    )
    searched: list[Path] = []
    for prefix in dict.fromkeys(prefixes):
        for relative in relative_candidates:
            candidate = prefix / relative
            searched.append(candidate)
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
            if (
                "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in text
                and "This LICENSE AGREEMENT is between the Python Software Foundation" in text
            ):
                return candidate
    locations = ", ".join(str(path) for path in searched)
    raise FileNotFoundError(
        f"CPython {RELEASE_PYTHON_VERSION} PSF license was not found in: {locations}"
    )


def distribution_license_files() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for distribution_name in ("mutagen", "PyInstaller"):
        for relative, source in _distribution_notice_files(distribution_name).items():
            result[f"{distribution_name}/{relative}"] = source
    for relative, source in _pillow_notice_files().items():
        result[f"Pillow/{relative}"] = source
    result["Python-LICENSE.txt"] = python_license_file()
    return result


def _copy_staged_file(source: Path, target: Path, *, mode: int, epoch: int) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(mode)
    os.utime(target, (epoch, epoch))


def _logical_mode(path: Path, root: Path) -> int:
    relative = path.relative_to(root)
    if path.is_dir():
        return 0o755
    if relative.parts and relative.parts[0] == "bin":
        return 0o755
    if root.name.startswith("TrackVisualizerSetup-") and len(relative.parts) == 1:
        return 0o755
    return 0o644


def _file_record(path: Path, root: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "mode": f"{_logical_mode(path, root):04o}",
    }


def stage_package(
    stage_dir: Path,
    runtime: RuntimeFiles,
    target: BuildTarget,
    *,
    root: Path = ROOT,
    version: str = __version__,
    epoch: int = DEFAULT_SOURCE_DATE_EPOCH,
    ffmpeg_build_info: str = "Not recorded",
    ffmpeg_license: Path | None = None,
    ffmpeg_version: str | None = None,
    ffmpeg_source_url: str | None = None,
    ffmpeg_source_sha256: str | None = None,
    ffmpeg_build_script: Path | None = None,
    dependency_licenses: Mapping[str, Path] | None = None,
    signing: str = "unsigned",
    runtime_baseline: str | None = None,
) -> Path:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    runtime_names = {
        "engine": target.executable_name("TrackVisualizerEngine"),
        "runner": target.executable_name("TrackVisualizerRunner"),
        "ffmpeg": target.executable_name("ffmpeg"),
        "ffprobe": target.executable_name("ffprobe"),
    }
    for role in EXECUTABLE_ROLES:
        _copy_staged_file(
            getattr(runtime, role),
            stage_dir / "bin" / runtime_names[role],
            mode=0o755,
            epoch=epoch,
        )

    _copy_staged_file(
        root / "resolve_scripts" / "Track Visualizer.lua",
        stage_dir / "resources" / "Track Visualizer.lua",
        mode=0o644,
        epoch=epoch,
    )
    _copy_staged_file(root / "aplus.png", stage_dir / "resources" / "aplus.png", mode=0o644, epoch=epoch)
    _copy_staged_file(
        root / "packaging" / "THIRD_PARTY_NOTICES.txt",
        stage_dir / "THIRD_PARTY_NOTICES.txt",
        mode=0o644,
        epoch=epoch,
    )

    build_info_path = stage_dir / "licenses" / "FFMPEG_BUILD_INFO.txt"
    build_info_path.parent.mkdir(parents=True, exist_ok=True)
    build_info_path.write_text(ffmpeg_build_info.rstrip() + "\n", encoding="utf-8", newline="\n")
    build_info_path.chmod(0o644)
    os.utime(build_info_path, (epoch, epoch))
    if ffmpeg_license is not None:
        _copy_staged_file(
            ffmpeg_license,
            stage_dir / "licenses" / "FFMPEG_LICENSE.txt",
            mode=0o644,
            epoch=epoch,
        )
    if ffmpeg_build_script is not None:
        _copy_staged_file(
            ffmpeg_build_script,
            stage_dir / "licenses" / "FFMPEG_BUILD_SCRIPT.sh",
            mode=0o644,
            epoch=epoch,
        )
    source_offer = stage_dir / "licenses" / "FFMPEG_SOURCE_OFFER.txt"
    source_record = "Exact corresponding source for the bundled FFmpeg and FFprobe binaries:\n"
    source_record += f"Version: {ffmpeg_version or 'not recorded'}\n"
    source_record += f"Official source URL: {ffmpeg_source_url or 'not recorded'}\n"
    source_record += f"SHA-256: {ffmpeg_source_sha256 or 'not recorded'}\n"
    source_offer.write_text(
        source_record
        + "The official release workflow publishes the byte-identical FFmpeg source archive beside the binary assets.\n"
        + "The complete build recipe is included as licenses/FFMPEG_BUILD_SCRIPT.sh and in the project source.\n"
        + "No patches or external libraries are used. FFmpeg libraries are linked statically; operating-system "
        + "runtime libraries remain platform dependencies.\n",
        encoding="utf-8",
        newline="\n",
    )
    source_offer.chmod(0o644)
    os.utime(source_offer, (epoch, epoch))
    mutagen_source_offer = stage_dir / "licenses" / "MUTAGEN_SOURCE_OFFER.txt"
    mutagen_source_offer.write_text(
        "Exact corresponding source for the bundled Mutagen library:\n"
        f"Version: {MUTAGEN_VERSION}\n"
        f"Official PyPI source URL: {MUTAGEN_SOURCE_URL}\n"
        f"SHA-256: {MUTAGEN_SOURCE_SHA256}\n"
        "The official release workflow publishes this byte-identical source archive beside the binary assets.\n",
        encoding="utf-8",
        newline="\n",
    )
    mutagen_source_offer.chmod(0o644)
    os.utime(mutagen_source_offer, (epoch, epoch))
    for name, license_path in sorted((dependency_licenses or {}).items()):
        _copy_staged_file(
            license_path,
            stage_dir / "licenses" / name,
            mode=0o644,
            epoch=epoch,
        )

    project_license = root / "LICENSE"
    _copy_staged_file(project_license, stage_dir / "LICENSE", mode=0o644, epoch=epoch)

    staged_files = sorted(
        (path for path in stage_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(stage_dir).as_posix(),
    )
    files = [_file_record(path, stage_dir) for path in staged_files]
    manifest = {
        "schema": "davinci-track-visualizer.release.v1",
        "product": PRODUCT_NAME,
        "version": version,
        "license": "GPL-3.0-or-later",
        "target": {"os": target.system, "architecture": target.architecture},
        "runtime_baseline": runtime_baseline,
        "source_date_epoch": epoch,
        "created_utc": dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "signing": signing,
        "ffmpeg_source_url": ffmpeg_source_url,
        "ffmpeg_source_sha256": ffmpeg_source_sha256,
        "ffmpeg_version": ffmpeg_version,
        "files": files,
    }
    manifest_path = stage_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_path.chmod(0o644)
    os.utime(manifest_path, (epoch, epoch))
    return manifest_path


def _archive_paths(stage_dir: Path) -> list[Path]:
    return sorted(stage_dir.rglob("*"), key=lambda path: path.relative_to(stage_dir).as_posix())


def create_zip_archive(stage_dir: Path, artifact: Path, epoch: int) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.utcfromtimestamp(max(epoch, 315_532_800)).timetuple()[:6]
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in _archive_paths(stage_dir):
            relative = Path(stage_dir.name) / path.relative_to(stage_dir)
            mode = _logical_mode(path, stage_dir)
            info = zipfile.ZipInfo(relative.as_posix() + ("/" if path.is_dir() else ""), timestamp)
            info.create_system = 3
            info.external_attr = ((stat.S_IFDIR if path.is_dir() else stat.S_IFREG) | mode) << 16
            if path.is_dir():
                archive.writestr(info, b"")
                continue
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, archive.open(info, "w") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)


def create_tar_archive(stage_dir: Path, artifact: Path, epoch: int) -> None:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    with artifact.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in _archive_paths(stage_dir):
                    relative = (Path(stage_dir.name) / path.relative_to(stage_dir)).as_posix()
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = epoch
                    info.mode = _logical_mode(path, stage_dir)
                    if path.is_file():
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        archive.addfile(info)


def create_archive(stage_dir: Path, artifact: Path, target: BuildTarget, epoch: int) -> None:
    if artifact.exists():
        artifact.unlink()
    if target.system == "windows":
        create_zip_archive(stage_dir, artifact, epoch)
    else:
        create_tar_archive(stage_dir, artifact, epoch)


def pyinstaller_command(
    entry_point: Path,
    name: str,
    dist_dir: Path,
    work_dir: Path,
    spec_dir: Path,
    *,
    windowed: bool = False,
    additions: list[tuple[Path, str, str]] | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--noupx",
        "--log-level",
        "WARN",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(ROOT),
    ]
    if windowed:
        command.append("--windowed")
    for source, destination, kind in additions or []:
        command.extend([f"--add-{kind}", f"{source}{os.pathsep}{destination}"])
    command.append(str(entry_point))
    return command


def apply_signing_hook(path: Path, command_template: str | None) -> None:
    if not command_template:
        print(f"Unsigned artifact: {path}")
        return
    parts = shlex.split(command_template)
    if not parts:
        raise ValueError("Signing command is empty")
    replaced = [part.replace("{path}", str(path)) for part in parts]
    if all("{path}" not in part for part in parts):
        replaced.append(str(path))
    run(replaced)


def smoke_test(runtime: RuntimeFiles, setup: Path | None, stage_dir: Path) -> None:
    subprocess.run(
        [str(runtime.engine), "--help"],
        cwd=stage_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    queue_dir = runtime.runner.parent / "tmp"
    queue_dir.mkdir(parents=True, exist_ok=True)
    done_path = queue_dir / "release_smoke_done.json"
    output_path = queue_dir / "release_smoke_stdout.txt"
    task_path = queue_dir / "runner_launch_release_smoke.json"
    task_path.write_text(
        json.dumps(
            {
                "mode": "run",
                "cwd": str(stage_dir),
                "command": [str(runtime.engine), "--help"],
                "stdout_path": str(output_path),
                "done_path": str(done_path),
            }
        ),
        encoding="utf-8",
    )
    subprocess.run([str(runtime.runner)], cwd=runtime.runner.parent, check=True, timeout=60)
    result = json.loads(done_path.read_text(encoding="utf-8"))
    if result.get("returncode") != 0:
        raise RuntimeError(f"Runner queue smoke test failed: {result}")
    if setup is not None:
        subprocess.run(
            [str(setup), "--dry-run", "--no-pause"],
            cwd=stage_dir,
            check=True,
            timeout=60,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build native Track Visualizer artifacts on the current supported host"
    )
    parser.add_argument("--ffmpeg", help="Native ffmpeg executable (or set TVIZ_FFMPEG)")
    parser.add_argument("--ffprobe", help="Native ffprobe executable (or set TVIZ_FFPROBE)")
    configured_ffmpeg_license = os.environ.get("TVIZ_FFMPEG_LICENSE")
    parser.add_argument(
        "--ffmpeg-license",
        type=Path,
        default=Path(configured_ffmpeg_license) if configured_ffmpeg_license else None,
        help="Exact license text shipped by the FFmpeg provider",
    )
    parser.add_argument(
        "--ffmpeg-source-url",
        default=os.environ.get("TVIZ_FFMPEG_SOURCE_URL"),
        help="Corresponding-source URL recorded in the release manifest",
    )
    parser.add_argument(
        "--ffmpeg-source-sha256",
        default=os.environ.get("TVIZ_FFMPEG_SOURCE_SHA256"),
        help="SHA-256 of the exact FFmpeg corresponding-source archive",
    )
    parser.add_argument(
        "--ffmpeg-version",
        default=os.environ.get("TVIZ_FFMPEG_VERSION"),
        help="Required upstream FFmpeg release version",
    )
    parser.add_argument(
        "--runtime-baseline",
        default=os.environ.get("TVIZ_RUNTIME_BASELINE"),
        help="Runtime ABI or operating-system baseline recorded in the manifest",
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=Path(os.environ.get("TVIZ_RELEASE_DIR", ROOT / "release")),
    )
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build" / "release")
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument(
        "--sign-command",
        default=os.environ.get("TVIZ_SIGN_COMMAND"),
        help="Optional external signing command; {path} is replaced with each binary path",
    )
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument("--skip-smoke-tests", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    validate_python_runtime()
    target = host_target()
    validate_release_environment(target, __version__)
    release_dir = args.release_dir.resolve()
    require_empty_release_directory(release_dir)
    epoch = source_date_epoch(args.source_date_epoch)
    ffmpeg = resolve_executable(args.ffmpeg, "ffmpeg")
    ffprobe = resolve_executable(args.ffprobe, "ffprobe")
    if args.ffmpeg_license is None:
        raise RuntimeError("--ffmpeg-license is required for a redistributable release")
    if not args.ffmpeg_license.is_file():
        raise FileNotFoundError(args.ffmpeg_license)
    if not args.ffmpeg_version:
        raise RuntimeError("--ffmpeg-version is required for a reproducible release")
    if not args.ffmpeg_source_url:
        raise RuntimeError("--ffmpeg-source-url is required for a redistributable release")
    if not args.ffmpeg_source_sha256 or not re.fullmatch(r"[0-9a-f]{64}", args.ffmpeg_source_sha256):
        raise RuntimeError("--ffmpeg-source-sha256 must be a lowercase SHA-256 digest")
    validate_native_binary(ffmpeg, target, "ffmpeg")
    validate_native_binary(ffprobe, target, "ffprobe")
    ffmpeg_build_info = validate_ffmpeg_pair(ffmpeg, ffprobe, args.ffmpeg_version)
    validate_ffmpeg_capabilities(ffmpeg)
    smoke_test_ffmpeg(ffmpeg, ffprobe)
    if not (ROOT / "LICENSE").is_file():
        raise FileNotFoundError("The project LICENSE file is required in release artifacts")

    work_root = args.build_dir.resolve() / target.tag
    if work_root.exists():
        shutil.rmtree(work_root)
    dist_dir = work_root / "dist"
    pyinstaller_work = work_root / "pyinstaller"
    spec_dir = work_root / "spec"
    for directory in (dist_dir, pyinstaller_work, spec_dir):
        directory.mkdir(parents=True, exist_ok=True)

    build_env = os.environ.copy()
    build_env["SOURCE_DATE_EPOCH"] = str(epoch)
    engine_name = target.executable_name("TrackVisualizerEngine")
    runner_name = target.executable_name("TrackVisualizerRunner")
    run(
        pyinstaller_command(
            ROOT / "scripts" / "engine_entry.py",
            "TrackVisualizerEngine",
            dist_dir,
            pyinstaller_work / "engine",
            spec_dir,
        ),
        env=build_env,
    )
    run(
        pyinstaller_command(
            ROOT / "scripts" / "runner_entry.py",
            "TrackVisualizerRunner",
            dist_dir,
            pyinstaller_work / "runner",
            spec_dir,
            windowed=target.system == "windows",
        ),
        env=build_env,
    )
    built_runtime = RuntimeFiles(
        engine=dist_dir / engine_name,
        runner=dist_dir / runner_name,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    for role in ("engine", "runner"):
        path = getattr(built_runtime, role)
        if not path.is_file():
            raise FileNotFoundError(path)
        validate_native_binary(path, target, role)
        apply_signing_hook(path, args.sign_command)

    stage_name = f"{PRODUCT_NAME}-{__version__}-{target.tag}"
    stage_dir = work_root / stage_name
    stage_package(
        stage_dir,
        built_runtime,
        target,
        version=__version__,
        epoch=epoch,
        ffmpeg_build_info=ffmpeg_build_info,
        ffmpeg_license=args.ffmpeg_license,
        ffmpeg_version=args.ffmpeg_version,
        ffmpeg_source_url=args.ffmpeg_source_url,
        ffmpeg_source_sha256=args.ffmpeg_source_sha256,
        ffmpeg_build_script=ROOT / "packaging" / "scripts" / "build_ffmpeg.sh",
        dependency_licenses=distribution_license_files(),
        signing="external-hook" if args.sign_command else "unsigned",
        runtime_baseline=args.runtime_baseline,
    )
    staged_runtime = RuntimeFiles(
        engine=stage_dir / "bin" / engine_name,
        runner=stage_dir / "bin" / runner_name,
        ffmpeg=stage_dir / "bin" / target.executable_name("ffmpeg"),
        ffprobe=stage_dir / "bin" / target.executable_name("ffprobe"),
    )

    archive_path = release_dir / f"{stage_name}{target.archive_suffix}"
    create_archive(stage_dir, archive_path, target, epoch)

    setup_path: Path | None = None
    installer_archive: Path | None = None
    if not args.skip_installer:
        additions: list[tuple[Path, str, str]] = []
        for path in sorted(stage_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(stage_dir)
            destination = relative.parent.as_posix() if relative.parent != Path(".") else "."
            kind = "binary" if relative.parts[0] == "bin" else "data"
            additions.append((path, destination, kind))
        run(
            pyinstaller_command(
                ROOT / "installer" / "track_visualizer_installer.py",
                "TrackVisualizerSetup",
                dist_dir,
                pyinstaller_work / "installer",
                spec_dir,
                additions=additions,
            ),
            env=build_env,
        )
        built_setup = dist_dir / target.executable_name("TrackVisualizerSetup")
        if not built_setup.is_file():
            raise FileNotFoundError(built_setup)
        validate_native_binary(built_setup, target, "installer")
        setup_name = f"TrackVisualizerSetup-{__version__}-{target.tag}{target.executable_suffix}"
        setup_path = release_dir / setup_name
        shutil.copy2(built_setup, setup_path)
        if target.system != "windows":
            setup_path.chmod(0o755)
        apply_signing_hook(setup_path, args.sign_command)

        if target.system != "windows":
            setup_stage = work_root / f"TrackVisualizerSetup-{__version__}-{target.tag}"
            setup_stage.mkdir()
            shutil.copy2(setup_path, setup_stage / setup_path.name)
            (setup_stage / setup_path.name).chmod(0o755)
            installer_archive = release_dir / f"{setup_stage.name}.tar.gz"
            create_tar_archive(setup_stage, installer_archive, epoch)

    if not args.skip_smoke_tests:
        smoke_test(staged_runtime, setup_path, stage_dir)

    print(f"Native target: {target.tag}")
    print(f"Portable archive: {archive_path}")
    if setup_path is not None:
        print(f"Installer: {setup_path}")
    if installer_archive is not None:
        print(f"Installer archive: {installer_archive}")
    if not args.sign_command:
        print("Signing: unsigned (set --sign-command or TVIZ_SIGN_COMMAND to use an external signing tool)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
