"""Regenerate the SKIN_CATALOG table embedded in the Resolve Lua script.

The Lua panel mirrors the Python skin catalog (skins, defaults, palettes,
ranges) so it can build the UI and sanitize settings without calling the
engine. Run this after changing ``davinci_track_visualizer/skins.py``;
``tests/test_lua_catalog.py`` fails while the two are out of sync.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from davinci_track_visualizer.skins import catalog  # noqa: E402

LUA_SCRIPT = ROOT / "resolve_scripts" / "Track Visualizer.lua"
BEGIN = "-- BEGIN GENERATED SKIN_CATALOG (scripts/sync_lua_catalog.py)"
END = "-- END GENERATED SKIN_CATALOG"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if", "in",
    "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
}


def lua_literal(value: Any, indent: int = 0) -> str:
    pad = "    " * indent
    inner = "    " * (indent + 1)
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        if not value.isascii():
            raise ValueError(f"catalog strings must be ASCII: {value!r}")
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        if all(not isinstance(item, (dict, list, tuple)) for item in value):
            return "{ " + ", ".join(lua_literal(item) for item in value) + " }"
        rows = [f"{inner}{lua_literal(item, indent + 1)}," for item in value]
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = []
        for key in sorted(value):
            name = str(key)
            if _IDENTIFIER.match(name) and name not in _LUA_KEYWORDS:
                label = name
            else:
                label = f"[{lua_literal(name)}]"
            rows.append(f"{inner}{label} = {lua_literal(value[key], indent + 1)},")
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    raise TypeError(f"unsupported catalog value: {type(value).__name__}")


def generated_block() -> str:
    return f"{BEGIN}\nlocal SKIN_CATALOG = {lua_literal(catalog())}\n{END}"


def sync(text: str) -> str:
    start = text.find(BEGIN)
    stop = text.find(END)
    if start < 0 or stop < start:
        raise ValueError("generated SKIN_CATALOG markers are missing from the Lua script")
    return text[:start] + generated_block() + text[stop + len(END):]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the Lua script is out of date")
    parser.add_argument("--script", type=Path, default=LUA_SCRIPT)
    args = parser.parse_args(argv)
    current = args.script.read_text(encoding="utf-8")
    updated = sync(current)
    if args.check:
        if updated != current:
            print(f"{args.script} is out of date; run scripts/sync_lua_catalog.py", file=sys.stderr)
            return 1
        return 0
    if updated != current:
        args.script.write_bytes(updated.encode("utf-8"))
        print(f"updated {args.script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
