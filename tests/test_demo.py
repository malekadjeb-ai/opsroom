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
        rc = demo.run(serve_console=False)
        assert rc == 0
        html = (Path(os.environ["OPSROOM_DATA_DIR"]) / "console.html")
        text = html.read_text()
        for needle in ("SINGLE HIGHEST CASH ACTION", "UNBLOCK FIRST", "TRACK A",
                       "$8,250", "tel:5556621177", "researched targets",
                       "Trap zone", "decisions log"):
            assert needle in text, f"missing: {needle}"
        assert "src=" not in text and "fetch(" not in text

        # the PRODUCT is the live console: serve the seeded portfolio and prove the
        # demo shows a loaded, read-WRITE operator surface, not a static snapshot
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from opsroom import serve
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        live = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
        httpd.shutdown()
        for needle in ("DO NOW", "$8,250", "Dana Reyes", "LEADS worklist — 5 open",
                       "TODAY'S PACE", "Summit Fabrication"):
            assert needle in live, f"live demo missing: {needle}"
        assert live.count("<form") >= 10, "live demo must be read-WRITE, not words on a screen"
    print("demo gate: static console + live served demo with a seeded ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
