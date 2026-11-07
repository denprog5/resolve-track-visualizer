"""Skin catalogue: player skins, design defaults, built-in palettes and validation.

The Lua script mirrors ``SKIN_BASE_SIZES``, ``SKIN_FEATURES``, ``design defaults`` and
``PALETTES`` for its UI; ``tests/test_lua_catalog.py`` keeps both copies identical. The engine
is authoritative: every design that reaches it goes through :func:`normalize_design`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

DESIGN_SCHEMA = 2

SUPPORTED_SKINS = ("classic", "minimal", "portrait_glass", "compact", "wave")
ANCHORS = ("bottom_left", "bottom_center", "bottom_right", "top_left", "top_center", "top_right", "center")
TIME_MODES = ("elapsed_total", "split", "elapsed", "remaining", "none")
PROGRESS_BASES = ("track", "clip")
# Skins with the "progress_style" feature draw one progress indicator: the waveform or a line.
PROGRESS_STYLES = ("wave", "line")

# Player size in pixels at 100 % scale on a 1080-line frame.
SKIN_BASE_SIZES: dict[str, tuple[int, int]] = {
    "classic": (640, 160),
    "minimal": (640, 176),
    "portrait_glass": (420, 640),
    "compact": (600, 96),
    "wave": (720, 208),
}

# Elements a skin can draw. Toggles for anything else are ignored.
SKIN_FEATURES: dict[str, tuple[str, ...]] = {
    "classic": ("cover", "artist", "title", "brand", "time", "progress", "knob", "bars", "glass", "progress_style"),
    "minimal": ("artist", "title", "time", "progress"),
    "portrait_glass": ("cover", "artist", "title", "time", "progress", "knob", "bars", "glass", "progress_style"),
    "compact": ("cover", "artist", "title", "time", "progress", "knob"),
    "wave": ("cover", "artist", "title", "brand", "time", "bars", "knob", "glass"),
}

COLOR_KEYS = (
    "panel_color",
    "border_color",
    "primary_text_color",
    "secondary_text_color",
    "accent_color",
    "track_color",
)
PALETTE_KEYS = (
    "panel_color",
    "panel_alpha",
    "border_color",
    "border_alpha",
    "primary_text_color",
    "secondary_text_color",
    "accent_color",
    "track_color",
    "glass_strength",
)
BOOL_KEYS = (
    "show_cover",
    "show_artist",
    "show_title",
    "show_brand",
    "show_time",
    "show_progress",
    "show_knob",
    "show_bars",
    "glass_enabled",
    "uppercase_artist",
    "time_bold",
)
INT_RANGES: dict[str, tuple[int, int]] = {
    "panel_alpha": (0, 255),
    "border_alpha": (0, 255),
    "glass_strength": (0, 100),
    "scale": (25, 400),
    "margin_x": (0, 2000),
    "margin_y": (0, 2000),
    "corner_radius": (0, 64),
    "title_size": (8, 96),
    "artist_size": (8, 96),
    "meta_size": (8, 96),
    "bar_count": (8, 200),
}
ENUMS: dict[str, tuple[str, ...]] = {
    "anchor": ANCHORS,
    "time_mode": TIME_MODES,
    "progress_basis": PROGRESS_BASES,
    "progress_style": PROGRESS_STYLES,
}
TEXT_LIMITS: dict[str, int] = {
    "brand_text": 40,
    "title_font_family": 80,
    "artist_font_family": 80,
    "time_font_family": 80,
}

_COMMON_DEFAULTS: dict[str, Any] = {
    "anchor": "bottom_left",
    "scale": 100,
    "margin_x": 48,
    "margin_y": 48,
    "brand_text": "aplus.fm",
    "show_cover": True,
    "show_artist": True,
    "show_title": True,
    "show_brand": True,
    "show_time": True,
    "show_progress": True,
    "show_knob": True,
    "show_bars": True,
    "glass_enabled": True,
    "uppercase_artist": False,
    "time_bold": False,
    "time_mode": "elapsed_total",
    "progress_basis": "track",
    "progress_style": "wave",
    "bar_count": 72,
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
    "meta_size": 15,
    "title_font_family": "Segoe UI",
    "artist_font_family": "Segoe UI",
    "time_font_family": "Segoe UI",
}

_SKIN_OVERRIDES: dict[str, dict[str, Any]] = {
    "classic": {
        "title_size": 26,
        "artist_size": 16,
        "meta_size": 14,
    },
    "minimal": {
        "panel_color": "#241704",
        "panel_alpha": 224,
        "border_color": "#F2A900",
        "border_alpha": 255,
        "primary_text_color": "#FFD84A",
        "secondary_text_color": "#F2A900",
        "accent_color": "#FFD84A",
        "track_color": "#F2A900",
        "glass_enabled": False,
        "glass_strength": 0,
        "corner_radius": 2,
        "title_size": 32,
        "artist_size": 16,
        "meta_size": 30,
        "uppercase_artist": True,
        "time_bold": True,
        "show_progress": False,
        "title_font_family": "Impact",
        "artist_font_family": "Courier New",
    },
    "portrait_glass": {
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
        "time_mode": "split",
        "show_knob": False,
        "uppercase_artist": True,
    },
    "compact": {
        "panel_color": "#0E1714",
        "panel_alpha": 214,
        "border_color": "#7CE0C3",
        "border_alpha": 60,
        "primary_text_color": "#F2FFF9",
        "secondary_text_color": "#A7E8D3",
        "accent_color": "#4FE3B5",
        "track_color": "#A7E8D3",
        "glass_enabled": False,
        "glass_strength": 0,
        "corner_radius": 48,
        "title_size": 24,
        "artist_size": 16,
        "meta_size": 15,
    },
    "wave": {
        "panel_color": "#0B0F1A",
        "panel_alpha": 176,
        "border_color": "#AEBBDD",
        "border_alpha": 70,
        "primary_text_color": "#F3F6FF",
        "secondary_text_color": "#AEBBDD",
        "accent_color": "#7AA2FF",
        "track_color": "#AEBBDD",
        "corner_radius": 18,
        "glass_strength": 55,
        "title_size": 30,
        "artist_size": 17,
        "meta_size": 15,
        "time_mode": "split",
        "bar_count": 96,
        "uppercase_artist": True,
    },
}

PALETTES: dict[str, dict[str, Any]] = {
    "Default": {"panel_color": "#121619", "panel_alpha": 154, "border_color": "#FFFFFF", "border_alpha": 82, "primary_text_color": "#F5F7F8", "secondary_text_color": "#EEF3F5", "accent_color": "#EBEEF0", "track_color": "#EBEEF0", "glass_strength": 46},
    "Violet": {"panel_color": "#1A1028", "panel_alpha": 158, "border_color": "#B77CFF", "border_alpha": 82, "primary_text_color": "#FFF4D6", "secondary_text_color": "#DCCBFF", "accent_color": "#FFB454", "track_color": "#DCCBFF", "glass_strength": 68},
    "Ice": {"panel_color": "#101C23", "panel_alpha": 150, "border_color": "#B8F2FF", "border_alpha": 74, "primary_text_color": "#F7FDFF", "secondary_text_color": "#C9F5FF", "accent_color": "#70E7FF", "track_color": "#D7F9FF", "glass_strength": 72},
    "Amber": {"panel_color": "#21160D", "panel_alpha": 156, "border_color": "#FFB86B", "border_alpha": 76, "primary_text_color": "#FFF2DB", "secondary_text_color": "#FFD29A", "accent_color": "#FF9D3B", "track_color": "#FFD29A", "glass_strength": 60},
    "Neon": {"panel_color": "#090B16", "panel_alpha": 178, "border_color": "#00E5FF", "border_alpha": 118, "primary_text_color": "#FF3DF2", "secondary_text_color": "#9AF7FF", "accent_color": "#00F5D4", "track_color": "#43506B", "glass_strength": 72},
    "Ultraviolet": {"panel_color": "#10091E", "panel_alpha": 176, "border_color": "#8D5CFF", "border_alpha": 112, "primary_text_color": "#F4EEFF", "secondary_text_color": "#C4A7FF", "accent_color": "#FF4FD8", "track_color": "#655089", "glass_strength": 76},
    "Acid": {"panel_color": "#0D120B", "panel_alpha": 184, "border_color": "#B8FF3D", "border_alpha": 108, "primary_text_color": "#E8FF65", "secondary_text_color": "#B8FF3D", "accent_color": "#F4FF00", "track_color": "#52612E", "glass_strength": 58},
    "Crimson": {"panel_color": "#16090A", "panel_alpha": 190, "border_color": "#E04444", "border_alpha": 116, "primary_text_color": "#FFF1E8", "secondary_text_color": "#FF7A66", "accent_color": "#FF2E2E", "track_color": "#692929", "glass_strength": 48},
    "Steel": {"panel_color": "#111417", "panel_alpha": 194, "border_color": "#A9B2BC", "border_alpha": 104, "primary_text_color": "#F1F3F5", "secondary_text_color": "#A9B2BC", "accent_color": "#D5DADE", "track_color": "#4A5158", "glass_strength": 42},
    "Ember": {"panel_color": "#170D08", "panel_alpha": 188, "border_color": "#FF6A2A", "border_alpha": 110, "primary_text_color": "#FFE1C2", "secondary_text_color": "#FF9A52", "accent_color": "#FF3D00", "track_color": "#71321C", "glass_strength": 52},
    "GoldSignal": {"panel_color": "#241704", "panel_alpha": 224, "border_color": "#F2A900", "border_alpha": 255, "primary_text_color": "#FFD84A", "secondary_text_color": "#F2A900", "accent_color": "#FFD84A", "track_color": "#F2A900", "glass_strength": 0},
    "Mint": {"panel_color": "#0E1714", "panel_alpha": 214, "border_color": "#7CE0C3", "border_alpha": 60, "primary_text_color": "#F2FFF9", "secondary_text_color": "#A7E8D3", "accent_color": "#4FE3B5", "track_color": "#A7E8D3", "glass_strength": 0},
    "Lavender": {"panel_color": "#171125", "panel_alpha": 164, "border_color": "#C4B5FD", "border_alpha": 92, "primary_text_color": "#FFF8ED", "secondary_text_color": "#D8CCF2", "accent_color": "#A78BFA", "track_color": "#D8CCF2", "glass_strength": 70},
    "Midnight": {"panel_color": "#0B0F1A", "panel_alpha": 176, "border_color": "#AEBBDD", "border_alpha": 70, "primary_text_color": "#F3F6FF", "secondary_text_color": "#AEBBDD", "accent_color": "#7AA2FF", "track_color": "#AEBBDD", "glass_strength": 55},
}
DEFAULT_PALETTES = {
    "classic": "Default",
    "minimal": "GoldSignal",
    "portrait_glass": "Lavender",
    "compact": "Mint",
    "wave": "Midnight",
}

_HEX = re.compile(r"^#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def check_skin(skin: Any) -> str:
    if not isinstance(skin, str) or skin not in SUPPORTED_SKINS:
        raise ValueError(f"Unsupported skin {skin!r}; expected one of {', '.join(SUPPORTED_SKINS)}")
    return skin


def default_design(skin: str = "classic") -> dict[str, Any]:
    check_skin(skin)
    design = dict(_COMMON_DEFAULTS)
    design.update(_SKIN_OVERRIDES[skin])
    return design


def normalize_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    match = _HEX.match(text)
    if not match:
        return fallback
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return "#" + digits.upper()


def _to_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return fallback


def _to_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number in (float("inf"), float("-inf")):
        return fallback
    return max(minimum, min(maximum, int(round(number))))


def _migrate_progress_style(source: dict[str, Any], skin: str) -> None:
    """Designs saved before ``progress_style`` toggled the waveform and the line separately."""
    if "progress_style" not in SKIN_FEATURES[skin] or "progress_style" in source:
        return
    bars = _to_bool(source.get("show_bars"), True)
    line = _to_bool(source.get("show_progress"), True)
    if not bars and not line:
        source["show_progress"] = False
        return
    source["progress_style"] = "line" if line and not bars else "wave"
    source["show_progress"] = True


def normalize_design(design: Mapping[str, Any] | None, skin: str) -> dict[str, Any]:
    """Merge user overrides over the skin defaults and coerce every known key to its type."""
    check_skin(skin)
    defaults = default_design(skin)
    source = dict(design or {})
    if design:
        _migrate_progress_style(source, skin)
    result: dict[str, Any] = {}
    for key, fallback in defaults.items():
        value = source.get(key, fallback)
        if key in COLOR_KEYS:
            result[key] = normalize_color(value, fallback)
        elif key in BOOL_KEYS:
            result[key] = _to_bool(value, fallback)
        elif key in INT_RANGES:
            low, high = INT_RANGES[key]
            result[key] = _to_int(value, fallback, low, high)
        elif key in ENUMS:
            result[key] = value if value in ENUMS[key] else fallback
        elif key in TEXT_LIMITS:
            text = str(value if value is not None else "").strip()
            if key.endswith("font_family") and not text:
                text = fallback
            result[key] = text[: TEXT_LIMITS[key]]
        else:  # pragma: no cover - every default key is classified above
            result[key] = value
    return result


def effective_flags(design: Mapping[str, Any], skin: str) -> dict[str, bool]:
    """Which elements are drawn: the user's toggle AND the skin's capability."""
    features = set(SKIN_FEATURES[check_skin(skin)])
    if "progress_style" in features:
        # One indicator: "Show progress" turns it on, the style picks the waveform or the line.
        shown = bool(design.get("show_progress"))
        wave = design.get("progress_style") != "line"
        return {
            "cover": bool(design.get("show_cover")),
            "artist": bool(design.get("show_artist")),
            "title": bool(design.get("show_title")),
            "brand": "brand" in features and bool(design.get("show_brand")) and bool(str(design.get("brand_text") or "").strip()),
            "time": bool(design.get("show_time")) and design.get("time_mode") != "none",
            "progress": shown and not wave,
            "knob": bool(design.get("show_knob")),
            "bars": shown and wave,
            "glass": bool(design.get("glass_enabled")),
        }
    return {
        "cover": "cover" in features and bool(design.get("show_cover")),
        "artist": "artist" in features and bool(design.get("show_artist")),
        "title": "title" in features and bool(design.get("show_title")),
        "brand": "brand" in features and bool(design.get("show_brand")) and bool(str(design.get("brand_text") or "").strip()),
        "time": "time" in features and bool(design.get("show_time")) and design.get("time_mode") != "none",
        "progress": "progress" in features and bool(design.get("show_progress")),
        "knob": "knob" in features and bool(design.get("show_knob")),
        "bars": "bars" in features and bool(design.get("show_bars")),
        "glass": "glass" in features and bool(design.get("glass_enabled")),
    }


def catalog() -> dict[str, Any]:
    """Everything the UI needs, as plain JSON-compatible data."""
    return {
        "schema": DESIGN_SCHEMA,
        "skins": list(SUPPORTED_SKINS),
        "anchors": list(ANCHORS),
        "time_modes": list(TIME_MODES),
        "progress_bases": list(PROGRESS_BASES),
        "progress_styles": list(PROGRESS_STYLES),
        "base_sizes": {skin: list(size) for skin, size in SKIN_BASE_SIZES.items()},
        "features": {skin: list(features) for skin, features in SKIN_FEATURES.items()},
        "defaults": {skin: default_design(skin) for skin in SUPPORTED_SKINS},
        "palettes": {name: dict(values) for name, values in PALETTES.items()},
        "default_palettes": dict(DEFAULT_PALETTES),
        "palette_keys": list(PALETTE_KEYS),
        "palette_order": list(PALETTES),
        "color_keys": list(COLOR_KEYS),
        "bool_keys": list(BOOL_KEYS),
        "int_ranges": {key: list(bounds) for key, bounds in INT_RANGES.items()},
        "enums": {key: list(values) for key, values in ENUMS.items()},
        "text_limits": dict(TEXT_LIMITS),
    }
