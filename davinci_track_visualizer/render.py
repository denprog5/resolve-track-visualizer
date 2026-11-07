"""Player card rendering.

A player is split into layers so Resolve only has to animate cheap things:

* ``card``   – everything static: shadow, panel, glass, cover, titles, brand, the unplayed
  progress track and waveform bars.
* ``played`` – the played look of the progress area (accent line/bars). Fusion reveals it from
  left to right with a rectangle mask.
* ``knob``   – the progress handle at the start position. Fusion moves it horizontally.
* time readouts – :class:`~davinci_track_visualizer.fusion_comp.TextSpec` entries drawn by
  Fusion TextPlus nodes (and by Pillow for previews).

Every layer is a full-frame RGBA image at timeline resolution with the player already at its
final position, so the Fusion composition needs no transforms besides the knob offset.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .fusion_comp import TextSpec, format_clock
from .skins import (
    SKIN_BASE_SIZES,
    SUPPORTED_SKINS,
    check_skin,
    default_design,
    effective_flags,
    normalize_design,
)

RENDERER_REVISION = 3
FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

__all__ = [
    "RENDERER_REVISION",
    "SUPPORTED_SKINS",
    "PlayerLayers",
    "TrackInfo",
    "compose_player",
    "default_design",
    "player_bounds",
    "render_preview",
    "render_track_layers",
    "sample_levels",
]


@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    cover_path: str | None = None


@dataclass
class PlayerLayers:
    card: Image.Image
    played: Image.Image | None
    knob: Image.Image | None
    progress_x1: float
    progress_x2: float
    texts: list[TextSpec] = field(default_factory=list)
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)


# --------------------------------------------------------------------------------------------
# Small helpers


def _hex_to_rgb(value: Any, fallback: str = "#FFFFFF") -> tuple[int, int, int]:
    text = str(value or fallback).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except (ValueError, IndexError):
        return _hex_to_rgb(fallback, "#FFFFFF")


def _rgba(color: Any, alpha: float) -> tuple[int, int, int, int]:
    red, green, blue = _hex_to_rgb(color)
    return red, green, blue, max(0, min(255, int(round(alpha))))


def _blank(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=max(0, radius), fill=255)
    return mask


def sample_levels(count: int, seed: int = 7) -> list[float]:
    """Deterministic, music-like placeholder levels for previews."""
    levels = []
    for index in range(max(1, count)):
        position = index / max(1, count - 1)
        envelope = 0.55 + 0.35 * math.sin(position * math.pi * 2.3 + 0.4) * math.sin(position * math.pi)
        texture = 0.5 + 0.5 * math.sin(index * 1.7 + seed) * math.cos(index * 0.61 + seed * 0.3)
        levels.append(max(0.08, min(1.0, envelope * (0.55 + 0.45 * texture))))
    return levels


def _resample(levels: Sequence[float], count: int) -> list[float]:
    if count <= 0:
        return []
    if not levels:
        return [0.08] * count
    if len(levels) == count:
        return [float(value) for value in levels]
    result = []
    source = len(levels)
    for index in range(count):
        start = index * source / count
        end = (index + 1) * source / count
        lo = int(math.floor(start))
        hi = max(lo + 1, int(math.ceil(end)))
        window = [float(levels[min(source - 1, j)]) for j in range(lo, hi)]
        result.append(max(window))
    return result


# --------------------------------------------------------------------------------------------
# Fonts


def _font_directories() -> tuple[Path, ...]:
    if sys.platform.startswith("win"):
        directories = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            directories.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return tuple(directories)
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
        Path("/usr/share/fonts"),
    )


_FAMILY_FILES = {
    "segoe ui": ("segoeui.ttf", "segoeuib.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf"),
    "times new roman": ("times.ttf", "timesbd.ttf"),
    "georgia": ("georgia.ttf", "georgiab.ttf"),
    "trebuchet ms": ("trebuc.ttf", "trebucbd.ttf"),
    "courier new": ("cour.ttf", "courbd.ttf"),
    "impact": ("impact.ttf", "impact.ttf"),
    "consolas": ("consola.ttf", "consolab.ttf"),
    "bahnschrift": ("bahnschrift.ttf", "bahnschrift.ttf"),
}
_FALLBACK_FILES = (
    ("segoeui.ttf", "segoeuib.ttf"),
    ("arial.ttf", "arialbd.ttf"),
    ("Arial.ttf", "Arial Bold.ttf"),
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
)


@lru_cache(maxsize=1)
def _font_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for directory in _font_directories():
        if not directory.is_dir():
            continue
        try:
            for path in directory.rglob("*"):
                if path.suffix.lower() in (".ttf", ".otf", ".ttc"):
                    index.setdefault(path.name.lower(), path)
        except OSError:
            continue
    return index


@lru_cache(maxsize=128)
def _font_path(family: str, bold: bool) -> str | None:
    index = _font_index()
    family_text = (family or "").strip()
    if family_text and Path(family_text).is_file():
        return family_text
    mapped = _FAMILY_FILES.get(family_text.lower())
    if mapped:
        path = index.get(mapped[1 if bold else 0].lower())
        if path:
            return str(path)
    compact = "".join(char for char in family_text.lower() if char.isalnum())
    if compact:
        candidates = []
        for name, path in index.items():
            stem = "".join(char for char in Path(name).stem.lower() if char.isalnum())
            if stem.startswith(compact):
                suffix = stem[len(compact):]
                score = 0 if suffix in ("", "regular") else 5
                if bold:
                    score = 0 if suffix in ("bold", "bd", "b") else (2 if "bold" in suffix else 6)
                elif "bold" in suffix or "black" in suffix or "italic" in suffix:
                    score = 9
                candidates.append((score, len(stem), str(path)))
        if candidates:
            return sorted(candidates)[0][2]
    for regular, heavy in _FALLBACK_FILES:
        path = index.get((heavy if bold else regular).lower())
        if path:
            return str(path)
    return None


@lru_cache(maxsize=256)
def _font(size: int, family: str = "Segoe UI", bold: bool = False) -> FontType:
    path = _font_path(family, bold)
    size = max(4, int(size))
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


def _safe_text(draw: ImageDraw.ImageDraw, text: str, font: FontType) -> str:
    try:
        draw.textlength(text, font=font)
        return text
    except UnicodeError:
        return text.encode("ascii", errors="replace").decode("ascii")


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: FontType, max_width: float) -> str:
    text = _safe_text(draw, text, font)
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "\u2026"
    try:
        draw.textlength(ellipsis, font=font)
    except UnicodeError:
        ellipsis = "..."
    while text and draw.textlength(text.rstrip() + ellipsis, font=font) > max_width:
        text = text[:-1]
    return (text.rstrip() + ellipsis) if text else ellipsis


# --------------------------------------------------------------------------------------------
# Artwork


def _crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _fallback_logo_image() -> Image.Image | None:
    candidates = []
    env_path = os.environ.get("DAVINCI_TRACK_VISUALIZER_LOGO")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path(sys.executable).resolve().parent / "aplus.png",
            Path(__file__).resolve().parents[1] / "aplus.png",
        ]
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return Image.open(candidate).convert("RGBA")
        except Exception:
            continue
    return None


def _cover_image(cover_path: str | None, size: int, tint: tuple[int, int, int]) -> Image.Image:
    size = max(1, int(size))
    if cover_path and Path(cover_path).is_file():
        try:
            image = Image.open(cover_path).convert("RGBA")
            return _crop_square(image).resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass
    base = tuple(int(channel * 0.22 + 18) for channel in tint)
    image = Image.new("RGBA", (size, size), base + (255,))
    logo = _fallback_logo_image()
    if logo:
        bbox = logo.getchannel("A").getbbox() or logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        logo.thumbnail((int(size * 0.62), int(size * 0.62)), Image.Resampling.LANCZOS)
        image.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    else:
        draw = ImageDraw.Draw(image)
        # A simple music note.
        draw.ellipse((size * 0.30, size * 0.58, size * 0.50, size * 0.76), fill=(255, 255, 255, 150))
        draw.rectangle((size * 0.46, size * 0.24, size * 0.50, size * 0.67), fill=(255, 255, 255, 150))
        draw.polygon(
            [(size * 0.50, size * 0.24), (size * 0.70, size * 0.30), (size * 0.70, size * 0.38), (size * 0.50, size * 0.32)],
            fill=(255, 255, 255, 150),
        )
    return image


# --------------------------------------------------------------------------------------------
# Placement


def _unit(width: int, height: int) -> float:
    return min(width, height) / 1080.0


def player_bounds(design: Mapping[str, Any], skin: str, width: int, height: int) -> tuple[int, int, int, int, float]:
    """Return ``(x, y, w, h, scale)`` of the player box inside a ``width``×``height`` frame."""
    base_w, base_h = SKIN_BASE_SIZES[check_skin(skin)]
    unit = _unit(width, height)
    scale = unit * float(design.get("scale", 100)) / 100.0
    box_w = max(1, int(round(base_w * scale)))
    box_h = max(1, int(round(base_h * scale)))
    if box_w > width or box_h > height:
        shrink = min(width / box_w, height / box_h)
        scale *= shrink
        box_w = max(1, int(base_w * scale))
        box_h = max(1, int(base_h * scale))
    margin_x = int(round(float(design.get("margin_x", 48)) * unit))
    margin_y = int(round(float(design.get("margin_y", 48)) * unit))
    anchor = str(design.get("anchor") or "bottom_left")
    if anchor.endswith("left"):
        x = margin_x
    elif anchor.endswith("right"):
        x = width - margin_x - box_w
    else:
        x = (width - box_w) // 2
    if anchor.startswith("top"):
        y = margin_y
    elif anchor.startswith("bottom"):
        y = height - margin_y - box_h
    else:
        y = (height - box_h) // 2
    x = max(0, min(width - box_w, x))
    y = max(0, min(height - box_h, y))
    return x, y, box_w, box_h, scale


# --------------------------------------------------------------------------------------------
# Painter


class _Painter:
    def __init__(self, width: int, height: int, design: Mapping[str, Any], skin: str, info: TrackInfo, levels: Sequence[float] | None):
        self.width = width
        self.height = height
        self.design = design
        self.skin = skin
        self.info = info
        self.levels = list(levels) if levels else sample_levels(int(design.get("bar_count", 72)))
        self.flags = effective_flags(design, skin)
        self.card = _blank(width, height)
        self.played: Image.Image | None = None
        self.knob: Image.Image | None = None
        self.progress: tuple[float, float] | None = None
        self.texts: list[TextSpec] = []
        self.x, self.y, self.w, self.h, self.s = player_bounds(design, skin, width, height)

    # coordinates -------------------------------------------------------------------------
    def px(self, value: float) -> float:
        return self.x + value * self.s

    def py(self, value: float) -> float:
        return self.y + value * self.s

    def sz(self, value: float) -> int:
        return max(1, int(round(value * self.s)))

    # layers ------------------------------------------------------------------------------
    def played_layer(self) -> Image.Image:
        if self.played is None:
            self.played = _blank(self.width, self.height)
        return self.played

    def knob_layer(self) -> Image.Image:
        if self.knob is None:
            self.knob = _blank(self.width, self.height)
        return self.knob

    # colours -----------------------------------------------------------------------------
    def color(self, key: str, alpha: float = 255) -> tuple[int, int, int, int]:
        return _rgba(self.design.get(key), alpha)

    # building blocks ---------------------------------------------------------------------
    def panel(self, rect: tuple[float, float, float, float], radius: float, *, shadow: float = 96, glass: bool | None = None, outline_key: str = "border_color") -> None:
        x1, y1, x2, y2 = (int(round(v)) for v in rect)
        r = max(0, int(round(radius)))
        if shadow > 0:
            layer = _blank(self.width, self.height)
            offset = self.sz(4)
            ImageDraw.Draw(layer).rounded_rectangle((x1, y1 + offset, x2, y2 + offset), radius=r, fill=(0, 0, 0, int(shadow)))
            self.card.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(2, self.sz(8)))))
        draw = ImageDraw.Draw(self.card)
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=r,
            fill=self.color("panel_color", self.design.get("panel_alpha", 154)),
            outline=self.color(outline_key, self.design.get("border_alpha", 82)),
            width=max(1, self.sz(1)),
        )
        if self.flags["glass"] if glass is None else glass:
            self._glass(x1, y1, x2 - x1 + 1, y2 - y1 + 1, r)

    def _glass(self, x: int, y: int, w: int, h: int, radius: int) -> None:
        strength = float(self.design.get("glass_strength", 46))
        if strength <= 0 or w < 8 or h < 8:
            return
        s = self.s
        glass = _blank(w, h)
        draw = ImageDraw.Draw(glass)
        inset = max(1, int(2 * s))
        draw.rounded_rectangle(
            (inset, inset, w - inset - 1, h - inset - 1),
            radius=max(1, radius - inset),
            outline=(255, 255, 255, int(strength * 0.45)),
            width=max(1, int(1 * s)),
        )
        shine = _blank(w, h)
        shine_draw = ImageDraw.Draw(shine)
        shine_draw.rounded_rectangle(
            (int(10 * s), int(6 * s), w - int(10 * s), int(max(12, h * 0.22))),
            radius=max(1, int(10 * s)),
            fill=(255, 255, 255, int(strength * 0.14)),
        )
        glass.alpha_composite(shine.filter(ImageFilter.GaussianBlur(max(1, int(6 * s)))))
        shade = _blank(w, h)
        ImageDraw.Draw(shade).rectangle((0, int(h * 0.58), w, h), fill=(0, 0, 0, int(strength * 0.18)))
        glass.alpha_composite(shade.filter(ImageFilter.GaussianBlur(max(3, int(10 * s)))))
        mask = _rounded_mask((w, h), radius)
        glass.putalpha(ImageChops.multiply(glass.getchannel("A"), mask))
        self.card.alpha_composite(glass, (x, y))

    def cover(self, x: float, y: float, size: float, radius: float) -> None:
        side = max(1, int(round(size)))
        image = _cover_image(self.info.cover_path, side, _hex_to_rgb(self.design.get("accent_color")))
        mask = _rounded_mask((side, side), int(round(radius)))
        image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
        self.card.alpha_composite(image, (int(round(x)), int(round(y))))

    def font(self, size_key: str, family_key: str, bold: bool = False, factor: float = 1.0) -> FontType:
        return _font(self.sz(float(self.design.get(size_key, 16)) * factor), str(self.design.get(family_key) or "Segoe UI"), bold)

    def text(self, x: float, y: float, text: str, font: FontType, fill: tuple[int, int, int, int], max_width: float, anchor: str = "la") -> None:
        draw = ImageDraw.Draw(self.card)
        fitted = _fit_text(draw, text, font, max(1.0, max_width))
        draw.text((x, y), fitted, font=font, fill=fill, anchor=anchor)

    def _glyph_box(self, font: FontType) -> tuple[float, float]:
        """Visual top and bottom of a text line relative to its baseline (accents and descenders)."""
        _, top, _, bottom = ImageDraw.Draw(self.card).textbbox((0, 0), "HgЙ", font=font, anchor="ls")
        return float(top), float(bottom)

    def stack_text(
        self,
        x: float,
        top: float,
        lines: Sequence[tuple[str, str, str, tuple[int, int, int, int], float]],
        gap: float,
        bottom: float | None = None,
        center: bool = False,
    ) -> float:
        """Draw lines top-down from ``top`` so their glyphs never overlap.

        Each line is ``(text, size_key, family_key, fill, max_width)``. When the chosen sizes do
        not fit above ``bottom`` the whole block shrinks proportionally (down to 55 %), so a large
        or tall font never runs into the next line or the progress row. With ``center`` the block
        is centred between ``top`` and ``bottom``. Returns the block bottom.
        """
        lines = [line for line in lines if line[0]]
        if not lines:
            return top
        def measure(factor: float) -> tuple[list[FontType], list[tuple[float, float]], float]:
            fonts = [self.font(size_key, family_key, factor=factor) for _, size_key, family_key, _, _ in lines]
            boxes = [self._glyph_box(font) for font in fonts]
            return fonts, boxes, sum(b - t for t, b in boxes) + gap * (len(lines) - 1)

        factor = 1.0
        fonts, boxes, height = measure(factor)
        while bottom is not None and top + height > bottom and factor > 0.55:
            factor = max(0.55, factor * min(0.97, (bottom - top) / height))
            fonts, boxes, height = measure(factor)
        y = top + max(0.0, (bottom - top - height) / 2) if center and bottom is not None else top
        for (text, _, _, fill, max_width), font, (box_top, box_bottom) in zip(lines, fonts, boxes):
            baseline = y - box_top
            self.text(x, baseline, text, font, fill, max_width, anchor="ls")
            y = baseline + box_bottom + gap
        return y - gap

    def artist_text(self) -> str:
        artist = self.info.artist or ""
        return artist.upper() if self.design.get("uppercase_artist") else artist

    def brand(self, right: float, top: float) -> None:
        if not self.flags["brand"]:
            return
        draw = ImageDraw.Draw(self.card)
        size = self.sz(13)
        font = _font(size, str(self.design.get("artist_font_family") or "Segoe UI"))
        color = self.color("secondary_text_color", 200)
        icon_r = max(3, int(size * 0.62))
        cx = right - icon_r
        cy = top + icon_r
        draw.ellipse((cx - icon_r, cy - icon_r, cx + icon_r, cy + icon_r), outline=color, width=max(1, self.sz(1.4)))
        tri = icon_r * 0.5
        draw.polygon([(cx - tri * 0.55, cy - tri), (cx - tri * 0.55, cy + tri), (cx + tri, cy)], fill=color)
        label = _safe_text(draw, str(self.design.get("brand_text") or ""), font)
        draw.text((cx - icon_r - self.sz(6), cy), label, font=font, fill=color, anchor="rm")

    def bars(self, x1: float, x2: float, base_y: float, max_h: float, *, mode: str, width_ratio: float, reflection: float = 0.0, min_pitch: float = 3.0) -> None:
        if x2 - x1 < 4:
            return
        requested = int(self.design.get("bar_count", 72))
        pitch_min = max(2.0, min_pitch * self.s)
        count = max(4, min(requested, int((x2 - x1) / pitch_min)))
        levels = _resample(self.levels, count)
        pitch = (x2 - x1) / count
        bar_w = max(1.0, pitch * width_ratio)
        track = ImageDraw.Draw(self.card)
        played = ImageDraw.Draw(self.played_layer())
        track_fill = self.color("track_color", 96)
        accent_fill = self.color("accent_color", 255)
        reflect_track = self.color("track_color", 34)
        reflect_accent = self.color("accent_color", 80)
        radius = bar_w / 2 if bar_w >= 3 else 0
        min_h = max(1.0, 1.5 * self.s)
        for index, level in enumerate(levels):
            left = x1 + index * pitch + (pitch - bar_w) / 2
            right = left + bar_w
            height = max(min_h, level * max_h)
            if mode == "mirror":
                box = (left, base_y - height / 2, right, base_y + height / 2)
            else:
                box = (left, base_y - height, right, base_y)
            for drawer, fill in ((track, track_fill), (played, accent_fill)):
                if radius:
                    drawer.rounded_rectangle(box, radius=radius, fill=fill)
                else:
                    drawer.rectangle(box, fill=fill)
            if reflection > 0 and mode != "mirror":
                gap = max(1.0, 1.5 * self.s)
                reflected = (left, base_y + gap, right, base_y + gap + height * reflection)
                track.rectangle(reflected, fill=reflect_track)
                played.rectangle(reflected, fill=reflect_accent)
        self._progress_span(x1, x2)

    def line(self, x1: float, x2: float, y: float, thickness: float, *, track_alpha: float = 80, track_key: str = "track_color", accent_key: str = "accent_color", accent_alpha: float = 235) -> None:
        half = max(0.5, thickness / 2)
        box = (x1, y - half, x2, y + half)
        radius = half if thickness >= 3 else 0
        ImageDraw.Draw(self.card).rounded_rectangle(box, radius=radius, fill=self.color(track_key, track_alpha))
        ImageDraw.Draw(self.played_layer()).rounded_rectangle(box, radius=radius, fill=self.color(accent_key, accent_alpha))
        self._progress_span(x1, x2)

    def _progress_span(self, x1: float, x2: float) -> None:
        if self.progress is None:
            self.progress = (x1, x2)
        else:
            self.progress = (min(self.progress[0], x1), max(self.progress[1], x2))

    def dot_knob(self, x: float, y: float, radius: float, color_key: str = "accent_color") -> None:
        if not self.flags["knob"]:
            return
        layer = self.knob_layer()
        glow = _blank(self.width, self.height)
        ImageDraw.Draw(glow).ellipse((x - radius * 2, y - radius * 2, x + radius * 2, y + radius * 2), fill=self.color(color_key, 70))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, radius * 0.8))))
        ImageDraw.Draw(layer).ellipse((x - radius, y - radius, x + radius, y + radius), fill=self.color(color_key, 255))

    def bar_knob(self, x: float, top: float, bottom: float, thickness: float) -> None:
        if not self.flags["knob"]:
            return
        layer = self.knob_layer()
        half = max(1.0, thickness / 2)
        glow = _blank(self.width, self.height)
        ImageDraw.Draw(glow).rounded_rectangle((x - half * 3, top, x + half * 3, bottom), radius=half * 3, fill=self.color("accent_color", 90))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, half * 2))))
        ImageDraw.Draw(layer).rounded_rectangle((x - half, top, x + half, bottom), radius=half, fill=self.color("primary_text_color", 255))

    # time readouts -----------------------------------------------------------------------
    def time_font(self) -> tuple[str, str, float]:
        family = str(self.design.get("time_font_family") or "Segoe UI")
        style = "Bold" if self.design.get("time_bold") else "Regular"
        return family, style, float(self.sz(float(self.design.get("meta_size", 15))))

    def time_width(self, sample: str) -> float:
        family, style, size = self.time_font()
        font = _font(int(size), family, style == "Bold")
        return ImageDraw.Draw(self.card).textlength(sample, font=font)

    def readout(self, kind: str, x: float, y: float, align: str, color: tuple[int, int, int, int]) -> None:
        family, style, size = self.time_font()
        self.texts.append(TextSpec(kind=kind, x=float(x), y=float(y), align=align, font=family, style=style, size_px=size, color=color))

    def time_row(self, left: float, right: float, y: float, color: tuple[int, int, int, int], *, single_align: str = "right") -> tuple[float, float]:
        """Place readouts for the configured time mode; return the free span between them."""
        if not self.flags["time"]:
            return left, right
        mode = self.design.get("time_mode")
        gap = self.sz(14)
        sample_single = {"elapsed_total": "00:00:00 / 00:00:00", "elapsed": "00:00:00", "remaining": "-00:00:00"}
        if mode == "split":
            self.readout("elapsed", left, y, "left", color)
            self.readout("total", right, y, "right", color)
            width = self.time_width("00:00:00")
            return left + width + gap, right - width - gap
        sample = sample_single.get(str(mode), "00:00:00")
        if single_align == "left":
            self.readout(str(mode), left, y, "left", color)
            return left + self.time_width(sample) + gap, right
        if single_align == "center":
            self.readout(str(mode), (left + right) / 2, y, "center", color)
            return left, right
        self.readout(str(mode), right, y, "right", color)
        return left, right - self.time_width(sample) - gap

    # result ------------------------------------------------------------------------------
    def result(self) -> PlayerLayers:
        x1, x2 = self.progress if self.progress else (0.0, 0.0)
        return PlayerLayers(
            card=self.card,
            played=self.played,
            knob=self.knob,
            progress_x1=float(x1),
            progress_x2=float(x2),
            texts=list(self.texts),
            bounds=(self.x, self.y, self.w, self.h),
        )


# --------------------------------------------------------------------------------------------
# Skins. Coordinates are in base-size units (see SKIN_BASE_SIZES) relative to the player box.


def _paint_classic(p: _Painter) -> None:
    d = p.design
    pad = 4
    card_w, card_h = 640 - pad * 2, 160 - pad * 2
    radius = p.s * float(d["corner_radius"])
    p.panel((p.px(pad), p.py(pad), p.px(pad + card_w) - 1, p.py(pad + card_h) - 1), radius)
    # Everything sits inside one inset; the square cover fills its height.
    inset = 16
    content_top, content_bottom = pad + inset, pad + card_h - inset
    if p.flags["cover"]:
        cover = content_bottom - content_top
        p.cover(p.px(pad + inset), p.py(content_top), p.s * cover, p.s * 10)
        text_x = p.px(pad + inset + cover + 20)
    else:
        text_x = p.px(pad + 24)
    text_right = p.px(pad + card_w - 20)
    p.brand(text_right, p.py(content_top))
    brand_reserve = p.sz(120) if p.flags["brand"] else 0
    indicator = p.flags["bars"] or p.flags["progress"]
    # Bottom row: waveform (with a playhead) or a line (with a dot), time on the right or at the ends.
    row_h = 28 if p.flags["bars"] else 12
    row_y = p.py(content_bottom - row_h / 2) if (indicator or p.flags["time"]) else p.py(content_bottom)
    p.stack_text(
        text_x,
        p.py(content_top + 2),
        [
            (p.artist_text() if p.flags["artist"] else "", "artist_size", "artist_font_family", p.color("secondary_text_color", 226), text_right - text_x - brand_reserve),
            (p.info.title if p.flags["title"] else "", "title_size", "title_font_family", p.color("primary_text_color"), text_right - text_x),
        ],
        gap=p.s * 6,
        bottom=(row_y - p.s * (row_h / 2 + 10)) if (indicator or p.flags["time"]) else p.py(content_bottom),
    )
    free_left, free_right = p.time_row(text_x, text_right, row_y, p.color("secondary_text_color", 225))
    if p.flags["bars"]:
        half = p.s * row_h / 2
        p.bars(free_left, free_right, row_y, half * 2, mode="mirror", width_ratio=0.5, min_pitch=4)
        p.bar_knob(free_left, row_y - half - p.sz(3), row_y + half + p.sz(3), max(2.0, p.s * 2.5))
    elif p.flags["progress"]:
        p.line(free_left, free_right, row_y, max(2.0, p.s * 4))
        p.dot_knob(free_left, row_y, p.s * 5.5)


def _minimal_timer_box(p: _Painter) -> tuple[float, float, float, float]:
    timer_w = 352 * p.s
    timer_h = 84 * p.s
    anchor = str(p.design.get("anchor"))
    right_side = not anchor.endswith("right")
    top_side = anchor.startswith("top")
    x = p.width - timer_w if right_side else 0
    y = 0 if top_side else p.height - timer_h
    return x, y, x + timer_w, y + timer_h


def _paint_minimal(p: _Painter) -> None:
    d = p.design
    timer = _minimal_timer_box(p) if (p.flags["time"] or p.flags["progress"]) else None
    card_left, card_top = p.px(0), p.py(0)
    card_right, card_bottom = p.px(640) - 1, p.py(176) - 1
    gap = p.sz(24)
    if timer and timer[1] < card_bottom and timer[3] > card_top:
        if timer[0] >= card_left:
            card_right = min(card_right, timer[0] - gap)
        else:
            card_left = max(card_left, timer[2] + gap)
    radius = p.s * float(d["corner_radius"])
    if card_right - card_left > p.sz(40):
        p.panel((card_left, card_top, card_right, card_bottom), radius, shadow=0, glass=False, outline_key="secondary_text_color")
        ImageDraw.Draw(p.card).rectangle((card_left, card_top, card_left + max(2, p.sz(7)), card_bottom), fill=p.color("secondary_text_color"))
        text_x = card_left + p.sz(24)
        max_w = card_right - text_x - p.sz(20)
        p.stack_text(
            text_x,
            card_top + p.sz(24),
            [
                (p.artist_text() if p.flags["artist"] else "", "artist_size", "artist_font_family", p.color("secondary_text_color"), max_w),
                (p.info.title.upper() if p.flags["title"] else "", "title_size", "title_font_family", p.color("primary_text_color"), max_w),
            ],
            gap=p.s * 10,
            bottom=card_bottom - p.sz(24),
            center=True,
        )
    if timer:
        x1, y1, x2, y2 = timer
        ImageDraw.Draw(p.card).rectangle((x1, y1, x2 - 1, y2 - 1), fill=p.color("primary_text_color"))
        pad = p.sz(20)
        p.time_row(x1 + pad, x2 - pad, (y1 + y2) / 2, p.color("panel_color"))
        if p.flags["progress"]:
            p.line(x1, x2, y2 - p.sz(3), max(2.0, p.s * 4), track_key="panel_color", track_alpha=60, accent_key="panel_color", accent_alpha=255)


def _paint_portrait_glass(p: _Painter) -> None:
    d = p.design
    pad = 4
    card_w, card_h = 420 - pad * 2, 640 - pad * 2
    radius = p.s * float(d["corner_radius"])
    p.panel((p.px(pad), p.py(pad), p.px(pad + card_w) - 1, p.py(pad + card_h) - 1), radius, shadow=104)
    inner = 24
    text_x = p.px(pad + inner)
    text_right = p.px(pad + card_w - inner)
    cover = card_w - inner * 2
    if p.flags["cover"]:
        p.cover(p.px(pad + inner), p.py(pad + inner), p.s * cover, p.s * 14)
        info_top = pad + inner + cover
    else:
        info_top = pad + 180
    # Bottom: the time row, with the waveform or the line just above it.
    time_y = p.py(pad + card_h - inner - 8)
    indicator_y = time_y - p.sz(30)
    indicator_top = indicator_y - p.sz(40) if p.flags["bars"] else indicator_y - p.sz(8)
    p.stack_text(
        text_x,
        p.py(info_top + 18),
        [
            (p.artist_text() if p.flags["artist"] else "", "artist_size", "artist_font_family", p.color("secondary_text_color", 226), text_right - text_x),
            (p.info.title if p.flags["title"] else "", "title_size", "title_font_family", p.color("primary_text_color"), text_right - text_x),
        ],
        gap=p.s * 8,
        bottom=indicator_top - p.sz(14),
    )
    if p.flags["bars"]:
        p.bars(text_x, text_right, indicator_y, p.s * 40, mode="up", width_ratio=0.5, reflection=0.0, min_pitch=5)
        p.bar_knob(text_x, indicator_y - p.sz(44), indicator_y + p.sz(4), max(2.0, p.s * 2.5))
    elif p.flags["progress"]:
        p.line(text_x, text_right, indicator_y, max(2.0, p.s * 4))
        p.dot_knob(text_x, indicator_y, p.s * 5.5)
    p.time_row(text_x, text_right, time_y, p.color("secondary_text_color", 225))


def _paint_compact(p: _Painter) -> None:
    d = p.design
    radius = min(p.s * float(d["corner_radius"]), p.h / 2)
    p.panel((p.px(0), p.py(0), p.px(600) - 1, p.py(96) - 1), radius, shadow=110, glass=False)
    if p.flags["cover"]:
        size = 68
        cover_radius = min(p.s * float(d["corner_radius"]) * 0.7, p.s * size / 2)
        p.cover(p.px(14), p.py(14), p.s * size, cover_radius)
        text_x = p.px(14 + size + 16)
    else:
        text_x = p.px(30)
    right = p.px(600 - 30)
    color = p.color("secondary_text_color", 225)
    title_right = right
    if p.flags["time"] and d.get("time_mode") != "split":
        title_right = p.time_row(text_x, right, p.py(30), color)[1]
    line_y = p.py(78)
    p.stack_text(
        text_x,
        p.py(14),
        [
            (p.info.title if p.flags["title"] else "", "title_size", "title_font_family", p.color("primary_text_color"), title_right - text_x),
            (p.artist_text() if p.flags["artist"] else "", "artist_size", "artist_font_family", color, title_right - text_x),
        ],
        gap=p.s * 4,
        bottom=line_y - p.sz(9) if p.flags["progress"] or d.get("time_mode") == "split" else p.py(82),
    )
    left, line_right = text_x, right
    if p.flags["time"] and d.get("time_mode") == "split":
        left, line_right = p.time_row(text_x, right, line_y, color)
    if p.flags["progress"]:
        p.line(left, line_right, line_y, max(2.0, p.s * 3))
        p.dot_knob(left, line_y, p.s * 5.5)


def _paint_wave(p: _Painter) -> None:
    d = p.design
    pad = 4
    card_w, card_h = 720 - pad * 2, 208 - pad * 2
    radius = p.s * float(d["corner_radius"])
    p.panel((p.px(pad), p.py(pad), p.px(pad + card_w) - 1, p.py(pad + card_h) - 1), radius, shadow=110)
    if p.flags["cover"]:
        # Square cover filling the card height inside the same inset as the rest of the content.
        inset = 20
        size = card_h - inset * 2
        p.cover(p.px(pad + inset), p.py(pad + inset), p.s * size, p.s * 12)
        text_x = p.px(pad + inset + size + 24)
    else:
        text_x = p.px(pad + 28)
    text_right = p.px(pad + card_w - 24)
    p.brand(text_right, p.py(pad + 20))
    brand_reserve = p.sz(120) if p.flags["brand"] else 0
    centre = p.py(pad + 128)
    half = p.s * 30
    p.stack_text(
        text_x,
        p.py(pad + 24),
        [
            (p.artist_text() if p.flags["artist"] else "", "artist_size", "artist_font_family", p.color("secondary_text_color", 226), text_right - text_x - brand_reserve),
            (p.info.title if p.flags["title"] else "", "title_size", "title_font_family", p.color("primary_text_color"), text_right - text_x),
        ],
        gap=p.s * 6,
        bottom=centre - half - p.sz(10),
    )
    if p.flags["bars"]:
        p.bars(text_x, text_right, centre, half * 2, mode="mirror", width_ratio=0.55, min_pitch=4)
        p.bar_knob(text_x, centre - half - p.sz(6), centre + half + p.sz(6), max(2.0, p.s * 3))
    p.time_row(text_x, text_right, p.py(pad + 180), p.color("secondary_text_color", 225))


_PAINTERS = {
    "classic": _paint_classic,
    "minimal": _paint_minimal,
    "portrait_glass": _paint_portrait_glass,
    "compact": _paint_compact,
    "wave": _paint_wave,
}


def compose_player(
    info: TrackInfo,
    levels: Sequence[float] | None,
    design: Mapping[str, Any] | None,
    skin: str,
    width: int,
    height: int,
) -> PlayerLayers:
    if width <= 0 or height <= 0 or width > 8192 or height > 8192:
        raise ValueError(f"Unsupported frame size {width}x{height}")
    normalized = normalize_design(design, skin)
    painter = _Painter(int(width), int(height), normalized, skin, info, levels)
    _PAINTERS[skin](painter)
    return painter.result()


def render_track_layers(
    info: TrackInfo,
    levels: Sequence[float] | None,
    design: Mapping[str, Any] | None,
    skin: str,
    width: int,
    height: int,
    out_dir: str | Path,
    stem: str,
) -> tuple[PlayerLayers, dict[str, str | None]]:
    """Render the layers of one player and write them as PNG files next to each other."""
    layers = compose_player(info, levels, design, skin, width, height)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str | None] = {"card": None, "played": None, "knob": None}
    for name, image in (("card", layers.card), ("played", layers.played), ("knob", layers.knob)):
        if image is None:
            continue
        target = directory / f"{stem}_{name}.png"
        temporary = target.with_name(f"{target.stem}.tmp{os.getpid()}.png")
        image.save(temporary, format="PNG", compress_level=6)
        os.replace(temporary, target)
        paths[name] = str(target)
    return layers, paths


# --------------------------------------------------------------------------------------------
# Previews


def _draw_readout(image: Image.Image, spec: TextSpec, text: str) -> None:
    draw = ImageDraw.Draw(image)
    font = _font(int(round(spec.size_px)), spec.font, spec.style.lower() == "bold")
    text = _safe_text(draw, text, font)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font, anchor="ls")
    if spec.align == "right":
        x = spec.x - right
    elif spec.align == "center":
        x = spec.x - (left + right) / 2
    else:
        x = spec.x - left
    y = spec.y - (top + bottom) / 2
    draw.text((x, y), text, font=font, fill=tuple(spec.color), anchor="ls")


def readout_text(kind: str, elapsed: float, total: float) -> str:
    with_hours = total >= 3600
    elapsed = max(0.0, min(total, elapsed))
    if kind == "total":
        return format_clock(total, with_hours)
    if kind == "remaining":
        return "-" + format_clock(math.ceil(total - elapsed), with_hours)
    if kind == "elapsed_total":
        return f"{format_clock(elapsed, with_hours)} / {format_clock(total, with_hours)}"
    return format_clock(elapsed, with_hours)


def flatten_player(layers: PlayerLayers, progress: float, elapsed: float, total: float) -> Image.Image:
    """Composite the layers as Fusion would at ``progress`` (0..1)."""
    progress = max(0.0, min(1.0, progress))
    frame = layers.card.copy()
    span = layers.progress_x2 - layers.progress_x1
    if layers.played is not None and span > 0:
        reveal = int(round(layers.progress_x1 + span * progress))
        if reveal > 0:
            mask = Image.new("L", frame.size, 0)
            ImageDraw.Draw(mask).rectangle((0, 0, reveal - 1, frame.height), fill=255)
            played = layers.played.copy()
            played.putalpha(ImageChops.multiply(played.getchannel("A"), mask))
            frame.alpha_composite(played)
    if layers.knob is not None:
        offset = int(round(span * progress))
        moved = _blank(*frame.size)
        moved.alpha_composite(layers.knob.crop((0, 0, frame.width - offset, frame.height)), (offset, 0))
        frame.alpha_composite(moved)
    for spec in layers.texts:
        _draw_readout(frame, spec, readout_text(spec.kind, elapsed, total))
    return frame


def _preview_background(size: tuple[int, int]) -> Image.Image:
    width, height = size
    top = (38, 44, 56)
    bottom = (14, 16, 22)
    gradient = Image.new("RGB", (1, 256))
    for row in range(256):
        t = row / 255
        gradient.putpixel((0, row), tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    background = gradient.resize((width, height), Image.Resampling.BILINEAR).convert("RGBA")
    glow = _blank(width, height)
    ImageDraw.Draw(glow).ellipse((width * 0.55, -height * 0.4, width * 1.25, height * 0.7), fill=(120, 140, 200, 46))
    background.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(4, width // 12))))
    return background


def render_preview(
    output_path: str | Path,
    design: Mapping[str, Any] | None,
    skin: str,
    *,
    frame_width: int = 1920,
    frame_height: int = 1080,
    preview_width: int = 640,
    title: str = "Track Title Preview",
    artist: str = "Artist Name",
    duration: float = 225.0,
    progress: float = 0.36,
    cover_path: str | None = None,
    crop: bool = False,
) -> Path:
    """Render the player over a neutral background, the whole frame or cropped to the player."""
    info = TrackInfo(title=title, artist=artist, cover_path=cover_path)
    layers = compose_player(info, None, design, skin, frame_width, frame_height)
    total = max(1.0, float(duration))
    progress = max(0.0, min(1.0, float(progress)))
    player = flatten_player(layers, progress, total * progress, total)
    frame = _preview_background(player.size)
    frame.alpha_composite(player)
    if crop:
        x, y, w, h = layers.bounds
        margin = int(min(frame_width, frame_height) * 0.04)
        box = (max(0, x - margin), max(0, y - margin), min(frame_width, x + w + margin), min(frame_height, y + h + margin))
        if skin == "minimal":
            box = (0, box[1], frame_width, frame_height) if box[1] > frame_height / 3 else (0, 0, frame_width, box[3])
        frame = frame.crop(box)
    if preview_width and frame.width > preview_width:
        ratio = preview_width / frame.width
        frame = frame.resize((preview_width, max(1, int(round(frame.height * ratio)))), Image.Resampling.LANCZOS)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.convert("RGB").save(target)
    return target
