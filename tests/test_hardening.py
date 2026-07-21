#!/usr/bin/env python3
"""Hardening gate: the 2026-07-18 audit fixes stay fixed. Money parsing with k/m
suffixes, no-$0-collected, clickjacking headers, scrubbed /context, drop-mtime
persistence across restarts, newest-first leads. Fictional fixtures. Exit 0 = green."""
import json
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

CONFIG = '''
[goal]
amount = 50000
deadline = "2099-01-01"
label = "$50K sprint"

[[venture]]
key = "meridian"
label = "Meridian Consulting"
track = "A"
trap = false
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import db, inbox, ops, serve, state, ventures
        ventures.refresh()
        con = db.connect()
        con.close()
        ocon = ops.connect()

        # ---- the operator money parser: suffixes, commas, cents, refunds
        cases = {"$4k": 4000, "4K": 4000, "1.5k": 1500, "$2m": 2_000_000,
                 "24,000": 24000, "$.50": 0.5, "-100": -100, "$1,250.75": 1250.75}
        for raw, want in cases.items():
            got = serve._money(raw)
            assert got == want, f"_money({raw!r}) = {got}, want {want}"
        assert serve._money("") is None and serve._money("call them") is None

        # note-cash without a $ still counts (static console parity)
        assert state._money("24,000 collected") == 24000

        # newest lead first: speed to lead
        ops.add_lead(ocon, "Old Lead", "5550100001", "sprint", venture="meridian")
        ocon.execute("UPDATE leads SET added='2020-01-01T00:00:00+00:00' WHERE name='Old Lead'")
        ocon.commit()
        ops.add_lead(ocon, "Fresh Lead", "5550100002", "sprint", venture="meridian")
        opens = ops.leads_open(ocon)
        assert opens[0]["name"] == "Fresh Lead", "leads_open must be newest first"

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        # ---- clickjacking: the console must refuse to be framed
        r = urllib.request.urlopen(base + "/", timeout=5)
        csp = r.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp, f"CSP missing frame-ancestors: {csp}"
        assert r.headers.get("X-Frame-Options") == "DENY", "X-Frame-Options missing"

        # ---- the auto-reload poller must be able to fetch /version: without
        # connect-src 'self', default-src 'none' blocks it and pages never refresh
        assert "connect-src 'self'" in csp, f"CSP missing connect-src 'self': {csp}"

        # ---- /context is scrubbed like the dispatch brief
        # fake secret assembled from parts so the repo never contains a
        # secret-shaped literal (GitHub push protection pattern-matches these)
        fake_key = "sk-live-Abcdefghij1234567890" + "T3Blb" + "kFJx"
        (Path(td) / "data").mkdir(exist_ok=True)
        ops.capture(ocon, f"rotate key {fake_key} yes")
        ctx = urllib.request.urlopen(base + "/context", timeout=5).read().decode()
        assert fake_key not in ctx, "/context leaked a secret"

        # ---- collected with no $ is an error, never a silent no-op
        lid = opens[0]["id"]

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect())

        def act(**fields):
            data = urllib.parse.urlencode({**fields, "token": serve.TOKEN}).encode()
            try:
                return opener.open(urllib.request.Request(base + "/act", data), timeout=5).status
            except urllib.error.HTTPError as e:
                return e.code

        assert act(do="lead_touch", id=lid, kind="collected", amount="") == 400
        assert ops.cash_total(ocon) == 0, "a $0 'collected' wrote cash"
        row = ocon.execute("SELECT status FROM leads WHERE id=?", (lid,)).fetchone()
        assert row["status"] != "won", "a $0 'collected' marked the lead won"
        assert act(do="lead_touch", id=lid, kind="collected", amount="$2k") == 303
        assert ops.cash_total(ocon) == 2000, "the $2k suffix didn't land in the ledger"
        httpd.shutdown()

        # ---- drop mtimes persist: a restart must not resurrect cleared missed calls
        drop = Path(os.environ["OPSROOM_DATA_DIR"]) / "drops"
        drop.mkdir(parents=True, exist_ok=True)
        lp = inbox.leads_drop_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps({"leads": [], "missed_calls": 9}))
        assert inbox.watch_tick(ocon) is not None
        assert ops.kv_get(ocon, "missed_calls") == "9"
        ops.kv_set(ocon, "missed_calls", "0")  # operator clears the banner
        inbox._MTIMES.clear()  # simulate a server restart
        inbox.watch_tick(ocon)
        assert ops.kv_get(ocon, "missed_calls") == "0", \
            "restart re-imported the stale drop and resurrected missed calls"

        # junk missed_calls must not crash or loop
        lp.write_text(json.dumps({"leads": [], "missed_calls": "lots"}))
        inbox._MTIMES.clear()
        r = inbox.import_leads(ocon, lp)
        assert r.get("missed_calls") == 0 and not r.get("error"), r
        ocon.close()
    print("hardening gate: money parser, $0-collected guard, frame-ancestors, "
          "scrubbed /context, persisted drop mtimes, newest-first leads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
