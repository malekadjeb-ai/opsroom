#!/usr/bin/env python3
"""Live-dispatch surface gate: GET /tail is TS_RE-locked (path traversal dies at
the door) and re-scrubs agent output; dispatch_cancel is CSRF-gated, actually
kills the run, and records 'cancelled'; a dead run renders as the console's TOP
banner and run_ack clears it. Exit 0 = green. Fictional fixtures."""
import json
import os
import sys
import tempfile
import threading
import time
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
        from opsroom import config, db, dispatch, ops, runs, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def code_of(url):
            try:
                return urllib.request.urlopen(url, timeout=5).status
            except urllib.error.HTTPError as e:
                return e.code

        # /tail: hostile ts values die at the TS_RE door, never touch a path
        canary = Path(td) / "canary.txt"
        canary.write_text("SECRET-CANARY-CONTENT")
        for bad in ("../../canary", "../../../etc/passwd", "%2e%2e%2fcanary",
                    "20260101-000000-1/../../canary", "", "x" * 60):
            q = urllib.parse.quote(bad, safe="")
            assert code_of(f"{base}/tail?ts={q}") == 404, f"/tail accepted {bad!r}"

        # a real run: /tail returns JSON status + tail, and SCRUBS agent output
        r = dispatch.dispatch("Work the backlog", "meridian")
        deadline = time.time() + 15
        while time.time() < deadline:
            if dispatch.status(r["ts"]) not in ("", "running"):
                break
            time.sleep(0.1)
        # plant a fake secret in the log AFTER the run: the read path must scrub
        fake_key = "sk-live-Abcdefghij1234567890" + "T3Blb" + "kFJx"
        log = Path(os.environ["OPSROOM_DATA_DIR"]) / "dispatch" / f"{r['ts']}.log"
        with open(log, "a") as fh:
            fh.write(f"note to self: {fake_key}\n")
        d = json.loads(urllib.request.urlopen(
            f"{base}/tail?ts={r['ts']}", timeout=5).read())
        assert d["status"] == "done" and "Proposing" in d["tail"], d["status"]
        assert fake_key not in d["tail"], "/tail leaked a secret — scrub failed"

        # cancel: tokenless POST is refused
        data = urllib.parse.urlencode({"do": "dispatch_cancel", "ts": r["ts"]}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 403, f"tokenless cancel accepted: {code}"

        # cancel a genuinely running agent: process dies, ledger says 'cancelled'
        os.environ["OPSROOM_FAKE_SLEEP"] = "60"
        r2 = dispatch.dispatch("Long haul", "meridian")
        assert dispatch.status(r2["ts"]) == "running"
        data = urllib.parse.urlencode({"do": "dispatch_cancel", "ts": r2["ts"],
                                       "token": serve.TOKEN}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
        ocon = ops.connect()
        row = None
        for _ in range(100):
            row = runs.get(ocon, r2["ts"])
            if row and row["outcome"] == "cancelled" and \
                    dispatch._PROCS[r2["ts"]].poll() is not None:
                break
            time.sleep(0.1)
        assert row and row["outcome"] == "cancelled", dict(row) if row else None
        assert dispatch.status(r2["ts"]) == "cancelled", dispatch.status(r2["ts"])
        try:
            os.kill(row["pid"], 0)
            alive = True
        except OSError:
            alive = False
        assert not alive, "cancel reported but the agent still runs"
        os.environ.pop("OPSROOM_FAKE_SLEEP")
        runs.ack(ocon, r2["ts"])  # cancels alert? no — cancelled never alerts
        assert not any(f["ts"] == r2["ts"] for f in runs.unacked_failures(ocon)), \
            "a cancelled run must not alert — the operator did it on purpose"

        # a DEAD run is the console's TOP banner; run_ack clears it
        ts3 = "20260101-000005-1"
        ddir = Path(os.environ["OPSROOM_DATA_DIR"]) / "dispatch"
        (ddir / f"{ts3}-brief.md").write_text("# DISPATCH\n\nTASK: overnight advise\n")
        (ddir / f"{ts3}.log").write_text("")
        runs.record_launch(ocon, ts3, kind="advise", task="overnight advise", pid=999999)
        runs.sweep(ocon)
        ocon.close()
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
        body = page[page.index("<body>"):]
        first_banner = body.split("<div class='banner bad'>", 2)
        assert len(first_banner) > 1, "no banner for a dead run"
        assert "0 bytes" in first_banner[1] and f"launched={ts3}" in first_banner[1], \
            "dead-run banner missing the accounting or the log link"
        data = urllib.parse.urlencode({"do": "run_ack", "ts": ts3,
                                       "token": serve.TOKEN}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
        page2 = urllib.request.urlopen(base + "/", timeout=10).read().decode()
        assert f"launched={ts3}" not in page2[page2.index("<body>"):], \
            "run_ack did not clear the dead-run banner"

        # the /do page carries the live-tail plumbing for a running dispatch
        os.environ["OPSROOM_FAKE_SLEEP"] = "10"
        r4 = dispatch.dispatch("Watch me stream", "meridian")
        q = urllib.parse.urlencode({"task": "Watch me stream", "venture": "meridian",
                                    "launched": r4["ts"]})
        do_html = urllib.request.urlopen(f"{base}/do?{q}", timeout=10).read().decode()
        assert f"tail-{r4['ts']}" in do_html and "/tail?ts=" in do_html, \
            "live tail target/poller missing from /do"
        assert "✕ cancel" in do_html, "no cancel button on a running row"
        dispatch.cancel(r4["ts"])
        os.environ.pop("OPSROOM_FAKE_SLEEP")
        httpd.shutdown()

    print("tail/cancel gate: TS_RE door holds, tail scrubbed, cancel kills + records, "
          "dead runs go red, ack clears")
    return 0


if __name__ == "__main__":
    sys.exit(main())
