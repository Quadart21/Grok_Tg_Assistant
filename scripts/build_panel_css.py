#!/usr/bin/env python3
"""Split panel CSS into logical sections."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "panel" / "style.css"
OUT = ROOT / "web" / "panel" / "css"

SECTIONS = {
    "base.css": (1, 62),
    "layout.css": (63, 251),
    "components.css": (252, 639),
    "pages.css": (640, 843),
    "responsive.css": (844, None),
}


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    OUT.mkdir(parents=True, exist_ok=True)

    for name, (start, end) in SECTIONS.items():
        chunk = lines[start - 1 :] if end is None else lines[start - 1 : end]
        (OUT / name).write_text("".join(chunk), encoding="utf-8")

    imports = "\n".join(f'@import url("css/{name}");' for name in SECTIONS)
    SRC.write_text(f"/* Kot_Teamlead — собрано из css/ */\n{imports}\n", encoding="utf-8")
    print("OK")


if __name__ == "__main__":
    main()
