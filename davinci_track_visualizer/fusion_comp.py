"""Generate Fusion compositions (``.comp``) for Track Visualizer overlays.

Each overlay clip on the timeline gets one composition, imported with
``TimelineItem:ImportFusionComp``. The composition never reads the carrier clip; it
draws everything from files the engine rendered:

* ``Card``   – the static card (panel, cover, titles, unplayed waveform/progress track).
* ``Played`` – the played state of the progress area (accent bars/line). It is merged over
  the card through a rectangle mask whose width follows playback.
* ``Knob``   – an optional progress handle, moved horizontally by a Transform.
* ``Time*``  – TextPlus readouts whose text is an expression of the composition time.

Composition ``time`` 0 is the first frame of the timeline item. All animation uses
expressions, so a one-hour clip costs the same as a ten-second one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

TIME_FORMATS = ("elapsed_total", "elapsed", "remaining", "total")


@dataclass(frozen=True)
class TextSpec:
    """One time readout. Coordinates are frame pixels, origin top-left."""

    kind: str  # one of TIME_FORMATS
    x: float
    y: float  # vertical centre of the text line
    align: str = "left"  # left | center | right
    font: str = "Segoe UI"
    style: str = "Regular"
    size_px: float = 16.0  # em height in pixels
    color: tuple[int, int, int, int] = (255, 255, 255, 255)
    tracking: float = 0.0


@dataclass(frozen=True)
class CompSpec:
    width: int
    height: int
    fps: float
    clip_frames: int
    card_path: str
    played_path: str | None = None
    knob_path: str | None = None
    # Progress area in frame pixels (x1..x2). The played layer is revealed left to right.
    progress_x1: float = 0.0
    progress_x2: float = 0.0
    # Playback timing: elapsed = offset_seconds + time / fps, clamped to total_seconds.
    offset_seconds: float = 0.0
    total_seconds: float = 1.0
    texts: tuple[TextSpec, ...] = field(default_factory=tuple)
    # Pixel to em ratio Fusion uses for TextPlus ``Size`` (Size = em_px / width * factor).
    text_size_factor: float = 1.70


def lua_string(value: str) -> str:
    out = ['"']
    for char in str(value):
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif code < 32:
            out.append(f"\\{code:03d}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _number(value: float) -> str:
    number = float(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return repr(round(number, 9))


def _expr_number(value: float) -> str:
    return repr(round(float(value), 9))


def elapsed_expression(spec: CompSpec) -> str:
    """Seconds of the source track at the current composition frame (float, clamped)."""
    return (
        f"math.min({_expr_number(spec.total_seconds)}, math.max(0, "
        f"{_expr_number(spec.offset_seconds)} + time / {_expr_number(spec.fps)}))"
    )


def progress_expression(spec: CompSpec) -> str:
    total = max(0.001, float(spec.total_seconds))
    return f"({elapsed_expression(spec)} / {_expr_number(total)})"


def _clock_parts(seconds_expr: str, with_hours: bool) -> tuple[str, str]:
    """Return (format, args) that render ``seconds_expr`` (already floored) as a clock."""
    if with_hours:
        return (
            "%d:%02d:%02d",
            f"math.floor(({seconds_expr}) / 3600), math.floor(({seconds_expr}) / 60) % 60, ({seconds_expr}) % 60",
        )
    return "%02d:%02d", f"math.floor(({seconds_expr}) / 60), ({seconds_expr}) % 60"


def format_clock(seconds: float, with_hours: bool) -> str:
    """Python twin of the Fusion clock format, used for static labels and tests."""
    whole = max(0, int(seconds))
    if with_hours:
        return f"{whole // 3600}:{(whole // 60) % 60:02d}:{whole % 60:02d}"
    return f"{whole // 60:02d}:{whole % 60:02d}"


def text_expression(spec: CompSpec, kind: str) -> str:
    if kind not in TIME_FORMATS:
        raise ValueError(f"Unsupported time readout {kind!r}")
    with_hours = float(spec.total_seconds) >= 3600
    total_label = format_clock(spec.total_seconds, with_hours)
    if kind == "total":
        return f"Text({lua_string(total_label)})"
    elapsed = f"math.floor({elapsed_expression(spec)})"
    if kind == "remaining":
        # Ceil keeps "-00:00" for the last fraction of a second only.
        remaining = f"math.max(0, math.ceil({_expr_number(spec.total_seconds)} - {elapsed_expression(spec)}))"
        fmt, args = _clock_parts(remaining, with_hours)
        return f"Text(string.format({lua_string('-' + fmt)}, {args}))"
    fmt, args = _clock_parts(elapsed, with_hours)
    if kind == "elapsed_total":
        return f"Text(string.format({lua_string(fmt + ' / ' + total_label.replace('%', '%%'))}, {args}))"
    return f"Text(string.format({lua_string(fmt)}, {args}))"


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0

    def line(self, text: str) -> None:
        self.lines.append("\t" * self.depth + text)

    def open(self, text: str) -> None:
        self.line(text)
        self.depth += 1

    def close(self, text: str = "},") -> None:
        self.depth -= 1
        self.line(text)


def _input_value(writer: _Writer, name: str, value: Any) -> None:
    key = name if name.isidentifier() else f"[{lua_string(name)}]"
    if isinstance(value, tuple):
        rendered = "{ " + ", ".join(_number(part) for part in value) + " }"
    elif isinstance(value, str):
        rendered = lua_string(value)
    else:
        rendered = _number(value)
    writer.line(f"{key} = Input {{ Value = {rendered}, }},")


def _input_expression(writer: _Writer, name: str, expression: str) -> None:
    writer.line(f"{name} = Input {{ Expression = {lua_string(expression)}, }},")


def _input_link(writer: _Writer, name: str, source_op: str, source: str = "Output") -> None:
    writer.line(f"{name} = Input {{ SourceOp = {lua_string(source_op)}, Source = {lua_string(source)}, }},")


def _view(writer: _Writer, x: int, y: int) -> None:
    writer.line(f"ViewInfo = OperatorInfo {{ Pos = {{ {x}, {y} }} }},")


def _loader(writer: _Writer, name: str, path: str, x: int, y: int) -> None:
    writer.open(f"{name} = Loader {{")
    writer.open("Clips = {")
    writer.open("Clip {")
    writer.line('ID = "Clip1",')
    writer.line(f"Filename = {lua_string(path)},")
    writer.line('FormatID = "PNGFormat",')
    writer.line("StartFrame = -1,")
    writer.line("LengthSetManually = true,")
    for key in ("TrimIn", "TrimOut", "ExtendFirst", "ExtendLast", "Loop", "AspectMode", "Depth", "TimeCode", "GlobalStart", "GlobalEnd"):
        writer.line(f"{key} = 0,")
    writer.close("},")
    writer.close("},")
    writer.open("Inputs = {")
    _input_value(writer, "Clip1.PNGFormat.PostMultiply", 1)
    writer.close("},")
    _view(writer, x, y)
    writer.close("},")


def _merge(writer: _Writer, name: str, background: str, foreground: str, x: int, y: int, mask: str | None = None) -> None:
    writer.open(f"{name} = Merge {{")
    writer.open("Inputs = {")
    _input_link(writer, "Background", background)
    _input_link(writer, "Foreground", foreground)
    _input_value(writer, "PerformDepthMerge", 0)
    if mask:
        _input_link(writer, "EffectMask", mask, "Mask")
    writer.close("},")
    _view(writer, x, y)
    writer.close("},")


def _rgba01(color: Iterable[int]) -> tuple[float, float, float, float]:
    parts = list(color) + [255] * 4
    return tuple(max(0, min(255, int(part))) / 255.0 for part in parts[:4])  # type: ignore[return-value]


_JUSTIFY = {"left": -1, "center": 0, "right": 1}


def build_comp(spec: CompSpec) -> str:
    if spec.width <= 0 or spec.height <= 0:
        raise ValueError("Composition size must be positive")
    if spec.clip_frames <= 0:
        raise ValueError("clip_frames must be positive")
    width = float(spec.width)
    height = float(spec.height)
    last = int(spec.clip_frames) - 1

    writer = _Writer()
    writer.open("Composition {")
    writer.line("CurrentTime = 0,")
    writer.line(f"RenderRange = {{ 0, {last} }},")
    writer.line(f"GlobalRange = {{ 0, {last} }},")
    writer.line("HiQ = true,")
    writer.open("Tools = {")

    _loader(writer, "Card", spec.card_path, 0, 0)
    current = "Card"
    column = 1
    progress_w = max(0.0, float(spec.progress_x2) - float(spec.progress_x1))

    if spec.played_path and progress_w > 0:
        _loader(writer, "Played", spec.played_path, column * 110, -66)
        reveal_width = f"({_expr_number(progress_w / width)} * {progress_expression(spec)})"
        writer.open("Reveal = RectangleMask {")
        writer.open("Inputs = {")
        _input_value(writer, "UseFrameFormatSettings", 1)
        _input_value(writer, "Height", 4)
        _input_expression(writer, "Width", reveal_width)
        _input_expression(
            writer,
            "Center",
            f"Point({_expr_number(float(spec.progress_x1) / width)} + {reveal_width} / 2, 0.5)",
        )
        writer.close("},")
        _view(writer, column * 110, -132)
        writer.close("},")
        _merge(writer, "PlayedMerge", current, "Played", column * 110, 0, mask="Reveal")
        current = "PlayedMerge"
        column += 1

    if spec.knob_path and progress_w > 0:
        _loader(writer, "Knob", spec.knob_path, column * 110, -66)
        writer.open("KnobMove = Transform {")
        writer.open("Inputs = {")
        _input_expression(
            writer,
            "Center",
            f"Point(0.5 + {_expr_number(progress_w / width)} * {progress_expression(spec)}, 0.5)",
        )
        _input_link(writer, "Input", "Knob")
        writer.close("},")
        _view(writer, column * 110, -33)
        writer.close("},")
        _merge(writer, "KnobMerge", current, "KnobMove", column * 110, 0)
        current = "KnobMerge"
        column += 1

    for index, text in enumerate(spec.texts, start=1):
        name = f"Time{index}"
        red, green, blue, alpha = _rgba01(text.color)
        writer.open(f"{name} = TextPlus {{")
        writer.open("Inputs = {")
        _input_value(writer, "UseFrameFormatSettings", 1)
        _input_value(writer, "Width", spec.width)
        _input_value(writer, "Height", spec.height)
        _input_expression(writer, "StyledText", text_expression(spec, text.kind))
        _input_value(writer, "Font", text.font)
        _input_value(writer, "Style", text.style)
        _input_value(writer, "Size", float(text.size_px) / width * float(spec.text_size_factor))
        _input_value(writer, "Center", (float(text.x) / width, 1.0 - float(text.y) / height))
        _input_value(writer, "HorizontalLeftCenterRight", _JUSTIFY.get(text.align, -1))
        _input_value(writer, "HorizontalJustificationNew", 3)
        _input_value(writer, "VerticalTopCenterBottom", 0)
        _input_value(writer, "VerticalJustificationNew", 3)
        if text.tracking:
            _input_value(writer, "CharacterSpacing", 1.0 + float(text.tracking))
        _input_value(writer, "Red1", red)
        _input_value(writer, "Green1", green)
        _input_value(writer, "Blue1", blue)
        _input_value(writer, "Alpha1", alpha)
        writer.close("},")
        _view(writer, column * 110, -66)
        writer.close("},")
        merge_name = f"{name}Merge"
        _merge(writer, merge_name, current, name, column * 110, 0)
        current = merge_name
        column += 1

    writer.open("MediaOut1 = Saver {")
    writer.open("Inputs = {")
    _input_value(writer, "Index", "0")
    _input_link(writer, "Input", current)
    writer.close("},")
    _view(writer, column * 110, 0)
    writer.close("},")

    writer.close("},")  # Tools
    writer.close("}")
    return "\n".join(writer.lines) + "\n"


def write_comp(path: str | Path, spec: CompSpec) -> Path:
    import os

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(build_comp(spec), encoding="utf-8", newline="\n")
    os.replace(temporary, target)
    return target
