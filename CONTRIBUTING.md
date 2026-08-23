# Contributing

## Before Opening A Change

Use an issue for behavior changes or substantial features. Security reports must follow [SECURITY.md](SECURITY.md), not the public issue tracker.

Keep compatibility claims limited to environments actually tested. The only verified Resolve environment currently documented is DaVinci Resolve Studio 20.2.1.

## Development Checks

Create a virtual environment and install runtime and development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Run the same checks as PR CI:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -c "from pathlib import Path; from luaparser import ast; ast.parse(Path(r'resolve_scripts/Track Visualizer.lua').read_text(encoding='utf-8'))"
```

Document manual Resolve testing separately; unit tests and Lua parsing do not validate behavior inside Resolve.

## Pull Requests

- Keep changes focused and explain user-visible behavior.
- Add or update tests when behavior can be tested outside Resolve.
- Do not commit generated output, private media, installers, binaries, credentials, or diagnostic logs.
- Update the changelog for user-visible changes.
- Confirm that new bundled dependencies have compatible licenses and update `THIRD_PARTY_NOTICES.md`.

Contributions are submitted under the project's `GPL-3.0-or-later` license.
