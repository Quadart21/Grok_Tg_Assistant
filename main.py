#!/usr/bin/env python3
"""Kot_Teamlead — локальная веб-панель управления Telegram."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.web_server import run_web_panel


def main() -> None:
    run_web_panel(ROOT, open_browser=True)


if __name__ == "__main__":
    main()
