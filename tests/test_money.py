#!/usr/bin/env python3
"""Money gate: spend ledger + per-venture P&L + the path-to-goal simulator.
Net math must be honest (in − out), the simulator must bake live numbers, and
the /act spend write must land. Fictional fixtures. Exit 0 = green."""
import os
import sys
import tempfile
import threading
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

[[venture]]
key = "shoptool"
label = "Shoptool"
trap = true
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import db, ops, serve, ventures
        ventures.refresh()
        con = db.connect()
        con.close()
        ocon = ops.connect()

        # ledger math: in − out, per venture and total
        ops.log_cash(ocon, 8000, "meridian", "sprint deposit")
        ops.log_cash(ocon, 500, "meridian", "workshop")
        ops.log_spend(ocon, 1200, "meridian", "ads")
        ops.log_spend(ocon, 300, "shoptool", "hosting")
        assert ops.cash_total(ocon) == 8500
        assert ops.spend_total(ocon) == 1500
        roi = {r["venture"]: r for r in ops.roi_rows(ocon)}
        assert roi["meridian"]["net"] == 7300, roi
        assert roi["shoptool"]["net"] == -300, roi

        # served MONEY tab: P&L cells, both ledgers, ROI table, simulator with live numbers
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "net (P&amp;L)" in html and "$7,000" in html, "net cell wrong"  # 8500-1500
        assert "Spend ledger" in html and "−$1,200" in html
        assert "per-venture P&amp;L" in html and "−$300" in html
        assert "simulator" in html and "cash:8500,goal:50000" in html, "sim numbers not baked"
        assert "Meridian Consulting closes" in html, "revenue venture missing from sim"
        assert "Shoptool closes" not in html, "trap venture leaked into the simulator"

        # /act spend write lands and moves the P&L
        data = urllib.parse.urlencode({"do": "spend", "amount": "250", "venture": "meridian",
                                       "what": "tooling", "token": serve.TOKEN}).encode()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        try:
            r = opener.open(urllib.request.Request(base + "/act", data), timeout=5)
            code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 303, f"spend write failed: {code}"
        assert ops.spend_total(ocon) == 1750
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "$6,750" in html, "net did not move after spend write"
        httpd.shutdown()

        # v0.6.1: a lead's collection is attributed to ITS venture, not a "leads" bucket
        lid = ops.add_lead(ocon, "Harbor Co", "5550100001", "sprint", venture="meridian")
        ops.touch_lead(ocon, lid, "collected", 2000)
        roi2 = {r["venture"]: r for r in ops.roi_rows(ocon)}
        assert "leads" not in roi2, roi2
        assert roi2["meridian"]["collected"] == 10500, roi2  # 8500 + 2000
        ocon.close()
    print("money gate: spend ledger, per-venture P&L, simulator bake, /act spend, lead ROI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
