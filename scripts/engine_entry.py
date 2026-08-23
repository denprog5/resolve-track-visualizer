import sys
import os

from davinci_track_visualizer.cli import main


def _configure_stdio() -> None:
    os.environ["PYTHONIOENCODING"] = "utf-8:replace"
    os.environ["PYTHONUTF8"] = "1"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _configure_stdio()
    raise SystemExit(main())
