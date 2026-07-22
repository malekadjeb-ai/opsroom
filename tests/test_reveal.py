#!/usr/bin/env python3
"""Reveal gate: the 📂 reveal verb only ever opens SERVER-derived paths — the
client sends names (brief/log/config/data) plus a TS_RE-validated ts, never a
path; junk names and hostile ts values are refused; the verb is CSRF-gated
like every write; and the HOW-DISPATCH-RUNS panel tells the truth about the
configured command. Exit 0 = green. Fictional fixtures."""
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        fake = ROOT / "tests" / "fake_agent.py"
        (cfg_dir / "config.toml").write_text(f'''
[goal]
amount = 50000
deadline = "2099-12-31"
label = "Q3 $50K sprint"

[[venture]]
key = "meridian"
label = "Meridian Consulting"

[agent]
enabled = true
command = ["{sys.executable}", "{fake}"]
''')
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        for k in ("OPSROOM_FAKE_EXIT", "OPSROOM_FAKE_SILENT", "OPSROOM_FAKE_SLEEP"):
            os.environ.pop(k, None)
        from opsroom import config, db, dispatch, ops, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ops.connect().close()

        revealed = []
        serve._reveal_target = lambda p: revealed.append(str(p))

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def post(fields, token=True):
            if token:
                fields = {**fields, "token": serve.TOKEN}
            data = urllib.parse.urlencode(fields).encode()
            req = urllib.request.Request(base + "/act", data)
            req.add_header("Origin", f"http://127.0.0.1:{port}")
            try:
                return urllib.request.urlopen(req, timeout=5).status
            except urllib.error.HTTPError as e:
                return e.code

        # CSRF-gated like every write
        assert post({"do": "reveal", "what": "config"}, token=False) == 403
        # config + data folder reveal by NAME — server derives the path
        assert post({"do": "reveal", "what": "config"}) in (200, 303)
        assert revealed[-1] == str(cfg_dir / "config.toml")
        assert post({"do": "reveal", "what": "data"}) in (200, 303)
        assert revealed[-1] == str(config.data_dir())
        # a real run's log, by ts name only
        r = dispatch.dispatch("Reveal me", "meridian")
        import time
        for _ in range(50):
            if dispatch.status(r["ts"]) not in ("", "running"):
                break
            time.sleep(0.1)
        assert post({"do": "reveal", "what": "log", "ts": r["ts"]}) in (200, 303)
        assert revealed[-1].endswith(f"{r['ts']}.log")
        n = len(revealed)
        # junk names and hostile ts values are refused, nothing revealed
        for bad in ({"do": "reveal", "what": "shadow"},
                    {"do": "reveal", "what": "log", "ts": "../../etc/passwd"},
                    {"do": "reveal", "what": "log", "ts": ""},
                    {"do": "reveal", "what": "log", "ts": "20990101-000000-1"},
                    {"do": "reveal", "what": "/etc/passwd"}):
            assert post(bad) == 400, f"reveal accepted {bad}"
        assert len(revealed) == n, "a refused reveal still opened something"

        # the HOW-DISPATCH-RUNS panel tells the truth on /do
        page = urllib.request.urlopen(base + "/do?task=x", timeout=5).read().decode()
        assert "HOW DISPATCH RUNS" in page and "not the desktop app" in page
        assert esc_free(page, sys.executable), "panel must show the real resolved command"
        assert "runs ledger" in page and "reveal" in page
        httpd.shutdown()

    print("reveal gate: names not paths, TS_RE door holds, CSRF gated, "
          "how-it-runs panel truthful")
    return 0


def esc_free(page: str, needle: str) -> bool:
    import html
    return needle in page or html.escape(needle) in page


if __name__ == "__main__":
    sys.exit(main())
