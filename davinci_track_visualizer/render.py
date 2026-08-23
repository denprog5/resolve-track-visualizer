from __future__ import annotations

import math
import os
import sys
import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .metadata import TrackMetadata, safe_stem


LIVE_DYNAMIC_SCHEMA = "davinci_track_visualizer.live_dynamic"
LIVE_DYNAMIC_SCHEMA_VERSION = 3
STATIC_RENDERER_REVISION = 2
SUPPORTED_SKINS = ("classic", "minimal", "portrait_glass")
STATIC_SKIN_REVISIONS = {
    "classic": 1,
    "minimal": 1,
    "portrait_glass": 1,
}


def _creationflags() -> int:
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def default_design(skin: str = "classic") -> dict[str, Any]:
    design = {
        "brand_text": "aplus.fm",
        "show_cover": True,
        "show_brand": True,
        "show_time": True,
        "show_progress": True,
        "show_knob": True,
        "glass_enabled": True,
        "panel_color": "#121619",
        "panel_alpha": 154,
        "border_color": "#FFFFFF",
        "border_alpha": 82,
        "primary_text_color": "#F5F7F8",
        "secondary_text_color": "#EEF3F5",
        "accent_color": "#EBEEF0",
        "track_color": "#EBEEF0",
        "corner_radius": 14,
        "glass_strength": 46,
        "title_size": 32,
        "artist_size": 18,
        "meta_size": 16,
        "title_font_family": "Segoe UI",
        "artist_font_family": "Segoe UI",
    }
    if skin == "minimal":
        design.update(
            {
                "panel_color": "#241704",
                "panel_alpha": 224,
                "border_color": "#F2A900",
                "border_alpha": 255,
                "primary_text_color": "#FFD84A",
                "secondary_text_color": "#F2A900",
                "corner_radius": 2,
                "title_size": 32,
                "artist_size": 16,
                "meta_size": 28,
                "title_font_family": "Impact",
                "artist_font_family": "Courier New",
            }
        )
    elif skin == "portrait_glass":
        design.update(
            {
                "panel_color": "#171125",
                "panel_alpha": 164,
                "border_color": "#C4B5FD",
                "border_alpha": 92,
                "primary_text_color": "#FFF8ED",
                "secondary_text_color": "#D8CCF2",
                "accent_color": "#A78BFA",
                "track_color": "#D8CCF2",
                "corner_radius": 24,
                "glass_strength": 70,
                "title_size": 30,
                "artist_size": 17,
                "meta_size": 15,
            }
        )
    return design


@dataclass
class RenderSettings:
    width: int = 640
    height: int = 160
    fps: int = 30
    bars: int = 56
    codec: str = "qtrle"
    design: dict[str, Any] = field(default_factory=default_design)
    player_width: int | None = None
    player_height: int | None = None
    margin: int = 48
    bake_position: bool = False
    skin: str = "classic"

    def __post_init__(self) -> None:
        if self.skin not in SUPPORTED_SKINS:
            raise ValueError(f"Unsupported skin {self.skin!r}; expected one of {', '.join(SUPPORTED_SKINS)}")


@dataclass
class RenderedTrack:
    source_path: str
    overlay_path: str
    title: str
    artist: str
    album: str
    duration: float
    cover_path: str | None
    frame_count: int
    job_id: str | None = None
    record_frame: int | None = None
    source_start_time: float | None = None
    timeline_item_name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def format_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _merged_design(settings: RenderSettings) -> dict[str, Any]:
    design = default_design(settings.skin)
    if settings.design:
        design.update(settings.design)
    return design


def _effective_design(settings: RenderSettings) -> dict[str, Any]:
    design = _merged_design(settings)
    if settings.skin == "minimal":
        design.update(
            {
                "show_cover": False,
                "show_brand": False,
                "show_time": True,
                "show_progress": False,
                "show_knob": False,
                "glass_enabled": False,
            }
        )
    elif settings.skin == "portrait_glass":
        design.update(
            {
                "show_cover": True,
                "show_brand": False,
                "show_time": True,
                "show_progress": True,
                "show_knob": False,
                "glass_enabled": True,
            }
        )
    return design


def static_renderer_revision(skin: str) -> dict[str, int]:
    if skin not in STATIC_SKIN_REVISIONS:
        raise ValueError(f"Unsupported skin {skin!r}")
    return {
        "renderer": STATIC_RENDERER_REVISION,
        "skin": STATIC_SKIN_REVISIONS[skin],
    }


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _hex_to_rgb(value: Any, fallback: str = "#FFFFFF") -> tuple[int, int, int]:
    text = str(value or fallback).strip()
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:
        text = "#" + "".join(char * 2 for char in text[1:])
    if len(text) != 7:
        text = fallback
    try:
        return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
    except Exception:
        return _hex_to_rgb(fallback, "#FFFFFF")


def _rgba(color: Any, alpha: Any, fallback: str = "#FFFFFF") -> tuple[int, int, int, int]:
    r, g, b = _hex_to_rgb(color, fallback)
    return r, g, b, _int(alpha, 255, 0, 255)


def _masked_alpha(image: Image.Image, mask: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    image.putalpha(ImageChops.multiply(alpha, mask))
    return image


def _classic_layout(settings: RenderSettings, design: dict[str, Any]) -> dict[str, Any]:
    outer_w = settings.player_width if settings.bake_position and settings.player_width else settings.width
    outer_h = settings.player_height if settings.bake_position and settings.player_height else settings.height
    outer_x = settings.margin if settings.bake_position else 0
    outer_y = settings.height - settings.margin - outer_h if settings.bake_position else 0
    scale = outer_h / 160.0
    pad = max(3, int(4 * scale))
    card_x = outer_x + pad
    card_y = outer_y + pad
    card_w = outer_w - pad * 2
    card_h = outer_h - pad * 2
    show_cover = _bool(design.get("show_cover"))
    if show_cover:
        cover_size = max(72, int(card_h - 32 * scale))
        cover_x = card_x + int(14 * scale)
        cover_y = int((card_h - cover_size) / 2)
        cover_y = card_y + cover_y
        text_x = cover_x + cover_size + int(22 * scale)
    else:
        cover_size = 0
        cover_x = 0
        cover_y = 0
        text_x = card_x + int(26 * scale)
    text_right = card_x + card_w - int(24 * scale)
    reserve_right = int(112 * scale) if _bool(design.get("show_time")) else int(12 * scale)
    meta_size = _int(design.get("meta_size"), 12, 8, 30)
    time_font_size = max(8, int(meta_size * scale))
    time_box_w = max(1, int(112 * scale))
    time_box_h = max(1, int(24 * scale))
    time_box_x = text_right - time_box_w
    time_box_y = card_y + int(98 * scale)
    return {
        "scale": scale,
        "pad": pad,
        "outer_x": outer_x,
        "outer_y": outer_y,
        "outer_w": outer_w,
        "outer_h": outer_h,
        "card_x": card_x,
        "card_y": card_y,
        "card_w": card_w,
        "card_h": card_h,
        "radius": max(4, int(_int(design.get("corner_radius"), 14, 0, 64) * scale)),
        "show_cover": show_cover,
        "cover_size": cover_size,
        "cover_x": cover_x,
        "cover_y": cover_y,
        "text_x": text_x,
        "text_right": text_right,
        "max_text_w": max(120, text_right - text_x - reserve_right),
        "line_y": card_y + card_h - int(20 * scale),
        "time_box_x": time_box_x,
        "time_box_y": time_box_y,
        "time_box_w": time_box_w,
        "time_box_h": time_box_h,
        "time_font_size": time_font_size,
        "progress_x1": text_x,
        "progress_x2": text_right,
        "progress_y": card_y + card_h - int(20 * scale),
        "progress_line_width": max(1, int(2 * scale)),
        "knob_radius": max(3, int(4 * scale)),
    }


def _minimal_layout(settings: RenderSettings, design: dict[str, Any]) -> dict[str, Any]:
    outer_w = settings.player_width if settings.bake_position and settings.player_width else settings.width
    outer_h = settings.player_height if settings.bake_position and settings.player_height else settings.height
    outer_x = settings.margin if settings.bake_position else 0
    outer_y = settings.height - settings.margin - outer_h if settings.bake_position else 0
    scale = max(0.05, min(outer_w / 640.0, outer_h / 176.0))
    gap = max(1, int(24 * scale))
    timer_w = max(1, min(settings.width, int(352 * scale)))
    timer_h = max(1, min(settings.height, int(84 * scale)))
    # The timer is a separate frame-corner element, matching the reference layout.
    timer_right = settings.width
    timer_bottom = settings.height
    timer_x = max(0, timer_right - timer_w)
    timer_y = max(0, timer_bottom - timer_h)
    card_w = max(1, min(outer_w, timer_x - gap - outer_x))
    card_h = max(1, outer_h)
    text_pad = max(1, min(card_w // 3, int(24 * scale)))
    time_pad = max(1, min(timer_w // 3, int(20 * scale)))
    return {
        "scale": scale,
        "pad": 0,
        "outer_x": outer_x,
        "outer_y": outer_y,
        "outer_w": outer_w,
        "outer_h": outer_h,
        "card_x": outer_x,
        "card_y": outer_y,
        "card_w": card_w,
        "card_h": card_h,
        "radius": max(1, int(_int(design.get("corner_radius"), 14, 0, 64) * scale)),
        "show_cover": False,
        "cover_size": 0,
        "cover_x": 0,
        "cover_y": 0,
        "text_x": outer_x + text_pad,
        "text_right": outer_x + card_w - text_pad,
        "max_text_w": max(1, card_w - text_pad * 2),
        "line_y": max(0, timer_bottom - 1),
        "timer_x": timer_x,
        "timer_y": timer_y,
        "timer_w": timer_w,
        "timer_h": timer_h,
        "time_box_x": timer_x + time_pad,
        "time_box_y": timer_y,
        "time_box_w": max(1, timer_w - time_pad * 2),
        "time_box_h": timer_h,
        "time_font_size": max(8, int(_int(design.get("meta_size"), 16, 8, 30) * scale)),
        "progress_x1": timer_x,
        "progress_x2": timer_x + timer_w,
        "progress_y": max(0, timer_bottom - 1),
        "progress_line_width": max(1, int(2 * scale)),
        "knob_radius": max(1, int(4 * scale)),
    }


def _portrait_glass_layout(settings: RenderSettings, design: dict[str, Any]) -> dict[str, Any]:
    outer_w = settings.player_width if settings.bake_position and settings.player_width else settings.width
    outer_h = settings.player_height if settings.bake_position and settings.player_height else settings.height
    outer_x = settings.margin if settings.bake_position else 0
    outer_y = settings.height - settings.margin - outer_h if settings.bake_position else 0
    scale = max(0.05, min(outer_w / 420.0, outer_h / 640.0))
    pad = max(1, int(4 * scale))
    card_x = outer_x + pad
    card_y = outer_y + pad
    card_w = max(1, outer_w - pad * 2)
    card_h = max(1, outer_h - pad * 2)
    inner = max(1, min(card_w // 3, card_h // 3, int(24 * scale)))
    lower_reserve = max(1, int(180 * scale))
    cover_size = max(1, min(card_w - inner * 2, card_h - inner * 2, card_h - inner * 2 - lower_reserve))
    cover_x = card_x + max(0, (card_w - cover_size) // 2)
    cover_y = card_y + inner
    text_x = card_x + inner
    text_right = card_x + card_w - inner
    progress_y = min(card_y + card_h - 1, card_y + card_h - max(1, int(28 * scale)))
    time_box_h = max(1, int(32 * scale))
    time_box_y = max(card_y, progress_y - max(1, int(52 * scale)))
    return {
        "scale": scale,
        "pad": pad,
        "outer_x": outer_x,
        "outer_y": outer_y,
        "outer_w": outer_w,
        "outer_h": outer_h,
        "card_x": card_x,
        "card_y": card_y,
        "card_w": card_w,
        "card_h": card_h,
        "radius": max(1, int(_int(design.get("corner_radius"), 20, 0, 64) * scale)),
        "show_cover": True,
        "cover_size": cover_size,
        "cover_x": cover_x,
        "cover_y": cover_y,
        "text_x": text_x,
        "text_right": text_right,
        "max_text_w": max(1, text_right - text_x),
        "artist_y": cover_y + cover_size + max(1, int(22 * scale)),
        "title_y": cover_y + cover_size + max(1, int(52 * scale)),
        "line_y": progress_y,
        "time_box_x": text_x,
        "time_box_y": time_box_y,
        "time_box_w": max(1, text_right - text_x),
        "time_box_h": time_box_h,
        "time_font_size": max(8, int(_int(design.get("meta_size"), 16, 8, 30) * scale)),
        "progress_x1": text_x,
        "progress_x2": max(text_x + 1, text_right),
        "progress_y": progress_y,
        "progress_line_width": max(1, int(3 * scale)),
        "knob_radius": max(1, int(4 * scale)),
    }


def _layout(settings: RenderSettings, design: dict[str, Any]) -> dict[str, Any]:
    if settings.skin == "classic":
        return _classic_layout(settings, design)
    if settings.skin == "minimal":
        return _minimal_layout(settings, design)
    return _portrait_glass_layout(settings, design)


def _font_directories() -> tuple[Path, ...]:
    if sys.platform.startswith("win"):
        return (Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",)
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Fonts",
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"),
        )
    return (
        Path.home() / ".local" / "share" / "fonts",
        Path.home() / ".fonts",
        Path("/usr/local/share/fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation2"),
        Path("/usr/share/fonts/truetype/liberation"),
    )


@lru_cache(maxsize=64)
def _font_candidates_cached(family_text: str, bold: bool, light: bool) -> tuple[str, ...]:
    candidates = []
    family_map = {
        "segoe ui": "segoeuib.ttf" if bold else "segoeuil.ttf" if light else "segoeui.ttf",
        "arial": "arialbd.ttf" if bold else "arial.ttf",
        "calibri": "calibrib.ttf" if bold else "calibri.ttf",
        "tahoma": "tahomabd.ttf" if bold else "tahoma.ttf",
        "verdana": "verdanab.ttf" if bold else "verdana.ttf",
        "times new roman": "timesbd.ttf" if bold else "times.ttf",
        "georgia": "georgiab.ttf" if bold else "georgia.ttf",
        "trebuchet ms": "trebucbd.ttf" if bold else "trebuc.ttf",
        "courier new": "courbd.ttf" if bold else "cour.ttf",
        "impact": "impact.ttf",
    }
    if family_text:
        family_path = Path(family_text)
        if family_path.exists():
            candidates.append(str(family_path))
        mapped = family_map.get(family_text.lower())
        if mapped:
            candidates.extend(str(directory / mapped) for directory in _font_directories())
        candidates.extend([family_text, f"{family_text}.ttf", f"{family_text}.otf"])
        compact = "".join(ch for ch in family_text.lower() if ch.isalnum())
        for fonts_dir in _font_directories():
            if not compact or not fonts_dir.exists():
                continue
            try:
                for font_file in list(fonts_dir.glob("*.ttf")) + list(fonts_dir.glob("*.otf")):
                    stem = "".join(ch for ch in font_file.stem.lower() if ch.isalnum())
                    if compact in stem or stem in compact:
                        candidates.append(str(font_file))
            except OSError:
                pass
    return tuple(candidates)


def _font_candidates(family: Any, bold: bool, light: bool) -> list[str]:
    return list(_font_candidates_cached(str(family or "").strip(), bold, light))


def _font(size: int, bold: bool = False, light: bool = False, family: Any = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    candidates.extend(_font_candidates(family, bold, light))
    if bold:
        candidates.extend([
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ])
    elif light:
        candidates.extend([
            r"C:\Windows\Fonts\segoeuil.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ])
    else:
        candidates.extend([
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ])

    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _font_safe_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> str:
    try:
        draw.textlength(text, font=font)
        return text
    except UnicodeError:
        return text.encode("ascii", errors="replace").decode("ascii")


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = _font_safe_text(draw, text, font)
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def _fit_font(draw: ImageDraw.ImageDraw, text: str, size: int, min_size: int, max_width: int, light: bool = False) -> ImageFont.ImageFont:
    for candidate_size in range(size, min_size - 1, -1):
        font = _font(candidate_size, light=light)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font(min_size, light=light)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _cover_image(metadata: TrackMetadata, size: int) -> Image.Image:
    if metadata.cover_path and Path(metadata.cover_path).exists():
        try:
            image = Image.open(metadata.cover_path).convert("RGBA")
            image = _crop_square(image).resize((size, size), Image.Resampling.LANCZOS)
            return image
        except Exception:
            pass

    logo = _fallback_logo_image()
    if logo:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        bbox = logo.getchannel("A").getbbox() or logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        max_w = int(size * 0.62)
        max_h = int(size * 0.62)
        logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        logo_x = (size - logo.width) // 2
        logo_y = (size - logo.height) // 2
        image.alpha_composite(logo, (logo_x, logo_y))
    else:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((size * 0.28, size * 0.22, size * 0.72, size * 0.66), fill=(255, 255, 255, 55))
        draw.rectangle((size * 0.62, size * 0.42, size * 0.68, size * 0.84), fill=(255, 255, 255, 80))
        draw.ellipse((size * 0.46, size * 0.70, size * 0.68, size * 0.92), fill=(255, 255, 255, 80))
    return image


def _fallback_logo_image() -> Image.Image | None:
    candidates = []
    env_path = os.environ.get("DAVINCI_TRACK_VISUALIZER_LOGO")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([
        Path.cwd() / "aplus.png",
        Path(sys.executable).resolve().parent / "aplus.png",
        Path(__file__).resolve().parents[1] / "aplus.png",
    ])

    for candidate in candidates:
        try:
            if candidate.exists():
                return Image.open(candidate).convert("RGBA")
        except Exception:
            continue
    return None


def _crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _draw_glass(frame: Image.Image, settings: RenderSettings, design: dict[str, Any], layout: dict[str, Any]) -> None:
    card_w = int(layout["card_w"])
    card_h = int(layout["card_h"])
    card_x = int(layout["card_x"])
    card_y = int(layout["card_y"])
    radius = int(layout["radius"])
    scale = float(layout["scale"])
    mask = _rounded_mask((card_w, card_h), radius)
    glass = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass)
    strength = _int(design.get("glass_strength"), 64, 0, 100)

    inner = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    inner_draw = ImageDraw.Draw(inner)
    inner_draw.rounded_rectangle(
        (int(2 * scale), int(2 * scale), card_w - int(3 * scale), card_h - int(3 * scale)),
        radius=max(1, radius - int(2 * scale)),
        outline=(255, 255, 255, int(strength * 0.52)),
        width=max(1, int(1 * scale)),
    )
    inner_draw.rounded_rectangle(
        (int(5 * scale), int(5 * scale), card_w - int(6 * scale), card_h - int(6 * scale)),
        radius=max(1, radius - int(5 * scale)),
        outline=(0, 0, 0, int(strength * 0.32)),
        width=max(1, int(1 * scale)),
    )
    glass.alpha_composite(inner)

    shine = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    shine_draw = ImageDraw.Draw(shine)
    shine_draw.rounded_rectangle(
        (int(10 * scale), int(8 * scale), card_w - int(10 * scale), int(34 * scale)),
        radius=max(1, int(10 * scale)),
        fill=(255, 255, 255, int(strength * 0.16)),
    )
    shine_draw.line((int(16 * scale), int(10 * scale), card_w - int(16 * scale), int(10 * scale)), fill=(255, 255, 255, int(strength * 0.70)), width=max(1, int(1 * scale)))
    shine = shine.filter(ImageFilter.GaussianBlur(max(1, int(5 * scale))))
    glass.alpha_composite(shine)

    shadow = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rectangle((0, int(card_h * 0.55), card_w, card_h), fill=(0, 0, 0, int(strength * 0.16)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, int(9 * scale))))
    glass.alpha_composite(shadow)

    try:
        noise = Image.effect_noise((card_w, card_h), 12).convert("L")
        noise_alpha = noise.point(lambda px: 2 if px > 172 else 0)
        noise_layer = Image.new("RGBA", (card_w, card_h), (255, 255, 255, 0))
        noise_layer.putalpha(noise_alpha)
        glass.alpha_composite(noise_layer)
    except Exception:
        pass

    frame.alpha_composite(_masked_alpha(glass, mask), (card_x, card_y))


def _draw_classic_static(
    frame: Image.Image,
    metadata: TrackMetadata,
    settings: RenderSettings,
) -> None:
    draw = ImageDraw.Draw(frame)
    design = _effective_design(settings)
    layout = _layout(settings, design)
    scale = float(layout["scale"])
    card_w = int(layout["card_w"])
    card_h = int(layout["card_h"])
    card_x = int(layout["card_x"])
    card_y = int(layout["card_y"])
    radius = int(layout["radius"])

    shadow = Image.new("RGBA", (settings.width, settings.height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (card_x, card_y + int(3 * scale), card_x + card_w - 1, card_y + card_h + int(2 * scale)),
        radius=radius,
        fill=(0, 0, 0, 96),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, int(5 * scale))))
    frame.alpha_composite(shadow)

    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_w - 1, card_y + card_h - 1),
        radius=radius,
        fill=_rgba(design.get("panel_color"), design.get("panel_alpha"), "#121619"),
        outline=_rgba(design.get("border_color"), design.get("border_alpha"), "#FFFFFF"),
        width=max(1, int(1 * scale)),
    )
    if _bool(design.get("glass_enabled")):
        _draw_glass(frame, settings, design, layout)

    if layout["show_cover"]:
        cover_size = int(layout["cover_size"])
        cover_x = int(layout["cover_x"])
        cover_y = int(layout["cover_y"])
        cover = _cover_image(metadata, cover_size)
        mask = _rounded_mask((cover_size, cover_size), int(8 * scale))
        cover = cover.copy()
        cover.putalpha(ImageChops.multiply(cover.getchannel("A"), mask))
        frame.alpha_composite(cover, (cover_x, cover_y))

    text_x = int(layout["text_x"])
    max_text_w = int(layout["max_text_w"])
    artist_size = _int(design.get("artist_size"), 14, 8, 36)
    title_size = _int(design.get("title_size"), 24, 10, 48)
    meta_size = _int(design.get("meta_size"), 12, 8, 30)
    artist_font = _font(max(8, int(artist_size * scale)), family=design.get("artist_font_family"))
    title_font = _font(max(10, int(title_size * scale)), family=design.get("title_font_family"))
    label_font = _font(max(8, int(meta_size * scale)))

    artist = _fit_text(draw, metadata.artist.upper(), artist_font, max_text_w)
    title = _fit_text(draw, metadata.title, title_font, max_text_w)
    draw.text((text_x, card_y + int(26 * scale)), artist, font=artist_font, fill=_rgba(design.get("secondary_text_color"), 226, "#EEF3F5"))
    draw.text((text_x, card_y + int(53 * scale)), title, font=title_font, fill=_rgba(design.get("primary_text_color"), 255, "#F5F7F8"))

    if _bool(design.get("show_brand")):
        label = _font_safe_text(draw, str(design.get("brand_text") or "aplus.fm"), label_font)
        label_w = draw.textlength(label, font=label_font)
        draw.text((card_x + card_w - label_w - int(20 * scale), card_y + int(16 * scale)), label, font=label_font, fill=_rgba(design.get("secondary_text_color"), 235, "#EEF3F5"))


def _draw_minimal_static(
    frame: Image.Image,
    metadata: TrackMetadata,
    settings: RenderSettings,
) -> None:
    draw = ImageDraw.Draw(frame)
    design = _effective_design(settings)
    layout = _layout(settings, design)
    scale = float(layout["scale"])
    card_x = int(layout["card_x"])
    card_y = int(layout["card_y"])
    card_w = int(layout["card_w"])
    card_h = int(layout["card_h"])
    radius = int(layout["radius"])

    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_w - 1, card_y + card_h - 1),
        radius=radius,
        fill=_rgba(design.get("panel_color"), design.get("panel_alpha"), "#121619"),
        outline=_rgba(design.get("secondary_text_color"), design.get("border_alpha"), "#EEF3F5"),
        width=max(1, int(1 * scale)),
    )
    draw.rectangle(
        (card_x, card_y, card_x + max(2, int(7 * scale)), card_y + card_h - 1),
        fill=_rgba(design.get("secondary_text_color"), 255, "#F2A900"),
    )

    artist_size = _int(design.get("artist_size"), 18, 8, 36)
    title_size = _int(design.get("title_size"), 32, 10, 48)
    artist_font = _font(max(8, int(artist_size * scale)), family=design.get("artist_font_family"))
    title_font = _font(max(10, int(title_size * scale)), family=design.get("title_font_family"))
    text_x = int(layout["text_x"])
    max_text_w = int(layout["max_text_w"])
    artist = _fit_text(draw, metadata.artist.upper(), artist_font, max_text_w)
    title = _fit_text(draw, metadata.title.upper(), title_font, max_text_w)
    draw.text(
        (text_x, card_y + max(1, int(42 * scale))),
        artist,
        font=artist_font,
        fill=_rgba(design.get("secondary_text_color"), 255, "#EEF3F5"),
    )
    draw.text(
        (text_x, card_y + max(1, int(72 * scale))),
        title,
        font=title_font,
        fill=_rgba(design.get("primary_text_color"), 255, "#F5F7F8"),
    )

    timer_x = int(layout["timer_x"])
    timer_y = int(layout["timer_y"])
    timer_w = int(layout["timer_w"])
    timer_h = int(layout["timer_h"])
    draw.rounded_rectangle(
        (timer_x, timer_y, timer_x + timer_w - 1, timer_y + timer_h - 1),
        radius=0,
        fill=_rgba(design.get("primary_text_color"), 255, "#F5F7F8"),
    )


def _draw_portrait_glass_static(
    frame: Image.Image,
    metadata: TrackMetadata,
    settings: RenderSettings,
) -> None:
    draw = ImageDraw.Draw(frame)
    design = _effective_design(settings)
    layout = _layout(settings, design)
    scale = float(layout["scale"])
    card_x = int(layout["card_x"])
    card_y = int(layout["card_y"])
    card_w = int(layout["card_w"])
    card_h = int(layout["card_h"])
    radius = int(layout["radius"])

    shadow = Image.new("RGBA", (settings.width, settings.height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (card_x, card_y + max(1, int(5 * scale)), card_x + card_w - 1, card_y + card_h - 1),
        radius=radius,
        fill=(0, 0, 0, 104),
    )
    frame.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(2, int(8 * scale)))))
    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_w - 1, card_y + card_h - 1),
        radius=radius,
        fill=_rgba(design.get("panel_color"), design.get("panel_alpha"), "#121619"),
        outline=_rgba(design.get("border_color"), design.get("border_alpha"), "#FFFFFF"),
        width=max(1, int(1 * scale)),
    )
    _draw_glass(frame, settings, design, layout)

    cover_size = int(layout["cover_size"])
    cover_x = int(layout["cover_x"])
    cover_y = int(layout["cover_y"])
    cover = _cover_image(metadata, cover_size)
    cover_mask = _rounded_mask((cover_size, cover_size), max(1, int(14 * scale)))
    cover = cover.copy()
    cover.putalpha(ImageChops.multiply(cover.getchannel("A"), cover_mask))
    frame.alpha_composite(cover, (cover_x, cover_y))

    text_x = int(layout["text_x"])
    max_text_w = int(layout["max_text_w"])
    artist_size = _int(design.get("artist_size"), 18, 8, 36)
    title_size = _int(design.get("title_size"), 32, 10, 48)
    artist_font = _font(max(8, int(artist_size * scale)), family=design.get("artist_font_family"))
    title_font = _font(max(10, int(title_size * scale)), family=design.get("title_font_family"))
    artist = _fit_text(draw, metadata.artist.upper(), artist_font, max_text_w)
    title = _fit_text(draw, metadata.title, title_font, max_text_w)
    draw.text(
        (text_x, int(layout["artist_y"])),
        artist,
        font=artist_font,
        fill=_rgba(design.get("secondary_text_color"), 226, "#EEF3F5"),
    )
    draw.text(
        (text_x, int(layout["title_y"])),
        title,
        font=title_font,
        fill=_rgba(design.get("primary_text_color"), 255, "#F5F7F8"),
    )


def _draw_card_static(
    frame: Image.Image,
    metadata: TrackMetadata,
    settings: RenderSettings,
) -> None:
    if settings.skin == "classic":
        _draw_classic_static(frame, metadata, settings)
    elif settings.skin == "minimal":
        _draw_minimal_static(frame, metadata, settings)
    else:
        _draw_portrait_glass_static(frame, metadata, settings)


def _dynamic_spec(metadata: TrackMetadata, settings: RenderSettings) -> dict[str, Any]:
    design = _effective_design(settings)
    layout = _layout(settings, design)
    scale = float(layout["scale"])
    time_box = {
        "x": int(layout["time_box_x"]),
        "y": int(layout["time_box_y"]),
        "width": int(layout["time_box_w"]),
        "height": int(layout["time_box_h"]),
    }
    time_color = design.get("panel_color") if settings.skin == "minimal" else design.get("secondary_text_color")
    time_fallback = "#121619" if settings.skin == "minimal" else "#EEF3F5"
    time_alpha = 255 if settings.skin == "minimal" else 220
    accent_color = list(_hex_to_rgb(design.get("accent_color"), "#EBEEF0"))
    return {
        "schema": LIVE_DYNAMIC_SCHEMA,
        "version": LIVE_DYNAMIC_SCHEMA_VERSION,
        "skin": settings.skin,
        "canvas": {
            "width": int(settings.width),
            "height": int(settings.height),
        },
        "duration_seconds": float(metadata.duration),
        "total_duration_label": format_mmss(metadata.duration),
        "player": {
            "x": int(layout["outer_x"]),
            "y": int(layout["outer_y"]),
            "width": int(layout["outer_w"]),
            "height": int(layout["outer_h"]),
            "margin": int(settings.margin),
            "bake_position": bool(settings.bake_position),
            "scale": scale,
            "card_x": int(layout["card_x"]),
            "card_y": int(layout["card_y"]),
            "card_width": int(layout["card_w"]),
            "card_height": int(layout["card_h"]),
        },
        "time": {
            "box": time_box,
            "x": time_box["x"] + time_box["width"],
            "y": time_box["y"] + time_box["height"] / 2.0,
            "anchor": "right_center",
            "horizontal_alignment": "right",
            "vertical_alignment": "center",
            "fusion_horizontal_justification": "right",
            "fusion_vertical_justification": "center",
            "font_family": "Segoe UI",
            "font_size": int(layout["time_font_size"]),
            "color": list(_hex_to_rgb(time_color, time_fallback)),
            "alpha": time_alpha,
        },
        "progress": {
            "x1": int(layout["progress_x1"]),
            "x2": int(layout["progress_x2"]),
            "y": int(layout["progress_y"]),
            "line_width": int(layout["progress_line_width"]),
            "track_color": list(_hex_to_rgb(design.get("track_color"), "#EBEEF0")),
            "track_alpha": 104,
            "accent_color": accent_color,
            "accent_alpha": 218,
            "knob_radius": int(layout["knob_radius"]),
            "knob_alpha": 235,
        },
        "show_time": _bool(design.get("show_time")),
        "show_progress": _bool(design.get("show_progress")),
        "show_knob": _bool(design.get("show_knob")),
    }


def _draw_dynamic_spec(
    frame: Image.Image,
    metadata: TrackMetadata,
    current_time: float,
    spec: dict[str, Any],
) -> None:
    draw = ImageDraw.Draw(frame)
    duration = max(0.001, metadata.duration)
    progress_value = max(0.0, min(1.0, current_time / duration))

    if spec["show_time"]:
        time_spec = spec["time"]
        time_text = f"{format_mmss(current_time)} / {format_mmss(metadata.duration)}"
        time_font = _font(int(time_spec["font_size"]), bold=spec.get("skin") == "minimal")
        time_text = _font_safe_text(draw, time_text, time_font)
        position = (float(time_spec["x"]), float(time_spec["y"]))
        fill = tuple(time_spec["color"]) + (int(time_spec["alpha"]),)
        try:
            draw.text(position, time_text, font=time_font, fill=fill, anchor="rm")
        except (TypeError, ValueError):
            text_width = draw.textlength(time_text, font=time_font)
            box = time_spec["box"]
            draw.text(
                (float(time_spec["x"]) - text_width, float(box["y"])),
                time_text,
                font=time_font,
                fill=fill,
            )

    if spec["show_progress"]:
        progress = spec["progress"]
        line_x1 = int(progress["x1"])
        line_x2 = int(progress["x2"])
        line_y = int(progress["y"])
        knob_x = line_x1 + int((line_x2 - line_x1) * progress_value)
        track_fill = tuple(progress["track_color"]) + (int(progress["track_alpha"]),)
        accent_fill = tuple(progress["accent_color"]) + (int(progress["accent_alpha"]),)
        draw.line((line_x1, line_y, line_x2, line_y), fill=track_fill, width=int(progress["line_width"]))
        draw.line((line_x1, line_y, knob_x, line_y), fill=accent_fill, width=int(progress["line_width"]))
        if spec["show_knob"]:
            knob_r = int(progress["knob_radius"])
            knob_fill = tuple(progress["accent_color"]) + (int(progress["knob_alpha"]),)
            draw.ellipse((knob_x - knob_r, line_y - knob_r, knob_x + knob_r, line_y + knob_r), fill=knob_fill)


def _draw_card_dynamic(
    frame: Image.Image,
    metadata: TrackMetadata,
    current_time: float,
    settings: RenderSettings,
) -> None:
    _draw_dynamic_spec(frame, metadata, current_time, _dynamic_spec(metadata, settings))


def render_live_carrier(
    metadata: TrackMetadata,
    output_path: str | Path,
    settings: RenderSettings,
) -> tuple[Path, dict[str, Any]]:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    frame = Image.new("RGBA", (settings.width, settings.height), (0, 0, 0, 0))
    _draw_card_static(frame, metadata, settings)
    frame.save(target, format="PNG")

    return target, _dynamic_spec(metadata, settings)


def _draw_card(
    frame: Image.Image,
    metadata: TrackMetadata,
    levels: list[float],
    current_time: float,
    settings: RenderSettings,
) -> None:
    _draw_card_static(frame, metadata, settings)
    _draw_card_dynamic(frame, metadata, current_time, settings)


def draw_frame(
    metadata: TrackMetadata,
    levels: list[float],
    current_time: float,
    settings: RenderSettings,
) -> Image.Image:
    frame = Image.new("RGBA", (settings.width, settings.height), (0, 0, 0, 0))
    _draw_card(frame, metadata, levels, current_time, settings)
    return frame


def _preview_background(size: tuple[int, int]) -> Image.Image:
    width, height = size
    background = Image.new("RGBA", size, (27, 30, 36, 255))
    draw = ImageDraw.Draw(background)
    cell = max(16, min(width, height) // 10)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            fill = (34, 38, 45, 255) if ((x // cell) + (y // cell)) % 2 == 0 else (24, 27, 33, 255)
            draw.rectangle((x, y, min(width, x + cell), min(height, y + cell)), fill=fill)
    return background


def render_style_preview(
    output_path: str | Path,
    settings: RenderSettings,
    title: str = "Track Title Preview",
    artist: str = "Artist Name",
    duration: float = 225.0,
    progress: float = 0.36,
    cover_path: str | None = None,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    preview_settings = RenderSettings(
        width=settings.width if settings.bake_position else settings.player_width or settings.width,
        height=settings.height if settings.bake_position else settings.player_height or settings.height,
        fps=1,
        bars=0,
        codec=settings.codec,
        design=settings.design,
        player_width=settings.player_width if settings.bake_position else None,
        player_height=settings.player_height if settings.bake_position else None,
        margin=settings.margin if settings.bake_position else 0,
        bake_position=settings.bake_position,
        skin=settings.skin,
    )
    metadata = TrackMetadata(
        source_path="preview",
        title=title,
        artist=artist,
        album="Preview",
        duration=max(1.0, float(duration)),
        cover_path=cover_path,
    )
    current_time = metadata.duration * max(0.0, min(1.0, float(progress)))
    player = draw_frame(metadata, [], current_time, preview_settings)
    frame = _preview_background(player.size)
    frame.alpha_composite(player)
    frame.convert("RGB").save(target)
    return target


def render_overlay(
    metadata: TrackMetadata,
    levels: list[float],
    output_dir: str | Path,
    settings: RenderSettings,
    ffmpeg: str = "ffmpeg",
    output_stem: str | None = None,
    job_id: str | None = None,
    record_frame: int | None = None,
    source_start_time: float | None = None,
    timeline_item_name: str | None = None,
    frame_count_override: int | None = None,
    progress_callback=None,
) -> RenderedTrack:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(output_stem or f"{metadata.artist}_{metadata.title}")
    target = output / f"{stem}_overlay.mov"
    frame_count = frame_count_override or max(1, int(math.ceil(metadata.duration * settings.fps)))

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{settings.width}x{settings.height}",
        "-r",
        str(settings.fps),
        "-i",
        "pipe:0",
        "-an",
    ]
    if settings.codec == "prores4444":
        cmd.extend(["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le"])
    else:
        cmd.extend(["-c:v", "qtrle", "-pix_fmt", "argb"])
    cmd.append(str(target))

    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_creationflags())
    assert process.stdin is not None
    progress_step = max(1, frame_count // 20)
    base_frame = Image.new("RGBA", (settings.width, settings.height), (0, 0, 0, 0))
    _draw_card_static(base_frame, metadata, settings)
    try:
        for frame_idx in range(frame_count):
            current_time = min(metadata.duration, frame_idx / float(settings.fps))
            frame = base_frame.copy()
            _draw_card_dynamic(frame, metadata, current_time, settings)
            process.stdin.write(frame.tobytes("raw", "RGBA"))
            done = frame_idx + 1
            if progress_callback and (done == 1 or done == frame_count or done % progress_step == 0):
                progress_callback(done, frame_count)
    finally:
        process.stdin.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed while rendering {target}: {stderr}")

    return RenderedTrack(
        source_path=metadata.source_path,
        overlay_path=str(target),
        title=metadata.title,
        artist=metadata.artist,
        album=metadata.album,
        duration=metadata.duration,
        cover_path=metadata.cover_path,
        frame_count=frame_count,
        job_id=job_id,
        record_frame=record_frame,
        source_start_time=source_start_time,
        timeline_item_name=timeline_item_name,
    )
