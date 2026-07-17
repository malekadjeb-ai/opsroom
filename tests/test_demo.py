#!/usr/bin/env python3
"""End-to-end: `opsroom demo` must build a loaded console from nothing. Exit 0 = green."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "base")
        os.environ["OPSROOM_NO_OPEN"] = "1"
        from opsroom import demo
        rc = demo.run()
        assert rc == 0
        html = (Path(os.environ["OPSROOM_DATA_DIR"]) / "console.html")
        text = html.read_text()
        for needle in ("SINGLE HIGHEST CASH ACTION", "UNBLOCK FIRST", "TRACK A",
                       "$8,250", "tel:5556621177", "researched targets",
                       "Trap zone", "decisions log"):
            assert needle in text, f"missing: {needle}"
        assert "src=" not in text and "fetch(" not in text
    print("demo gate: console builds with all sections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
