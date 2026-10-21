#!/usr/bin/env python3
"""Local web UI of the parking plate generator: a page on 127.0.0.1 that only this computer can open.

    .venv/bin/python -I -X utf8 -u scripts/webui.py [--port N] [--keep 5] [--no-browser] [--example] [--verbose]

--example: the example config only, config.toml is never read or written (screenshots, demos, tests).
The start-webui scripts in the project folder run this after setting up .venv.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))        # python -I ignores the script directory

from tissueplate.webui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
