#!/usr/bin/env python3
"""Leads workspace gate: /leads renders the WHOLE ledger (no 20-row cap), search/
status/sort filters work and are whitelisted, per-row writes land, the per-lead
▶ dispatch bakes the lead's context into the brief, and hostile lead text renders
escaped. Exit 0 = green. Fictional fixtures (555 numbers)."""
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

CONFIG = '''
[[venture]]
key = "meridian"
label = "Meridian Consulting"
offer = "The 2-week ops sprint is $12,000 flat."
'''


def _get(base, path):
    return urllib.request.urlopen(base + path, timeout=5).read().decode()


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, dispatch, ops, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        # seed 30 leads across statuses — more than the NOW-tab's 20-row cap
        ids = []
        for i in range(30):
            ids.append(ops.add_lead(ocon, f"Lead Number{i:02d}", f"(555) 010-{i:04d}",
                                    "full detail", f"note {i}", venture="meridian"))
        ops.touch_lead(ocon, ids[1], "quoted", 900)
        ops.touch_lead(ocon, ids[2], "quoted", 4500)
        ops.touch_lead(ocon, ids[3], "collected", 1200)   # -> won
        ops.touch_lead(ocon, ids[4], "lost")
        counts = ops.leads_counts(ocon)
        assert counts["all"] == 30 and counts["won"] == 1 and counts["lost"] == 1, counts
        assert counts["quoted"] == 2, counts

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        # the whole ledger renders — no 20-row cap
        page = _get(base, "/leads")
        assert page.count("Lead Number") >= 30, "workspace capped the list"
        assert "LEADS — 30 shown of 30" in page, "header count wrong"

        # search filters; query text is literal (LIKE-escaped)
        page = _get(base, "/leads?q=" + urllib.parse.quote("Number07"))
        assert "Lead Number07" in page and "Lead Number08" not in page
        assert "1 shown" in page
        page = _get(base, "/leads?q=" + urllib.parse.quote("%"))
        assert "0 shown" in page, "LIKE wildcard leaked through"

        # status chips
        page = _get(base, "/leads?status=lost")
        assert "Lead Number04" in page and "1 shown" in page
        page = _get(base, "/leads?status=quoted")
        assert "Lead Number01" in page and "Lead Number02" in page and "2 shown" in page
        # unknown status/sort values fall back safely
        page = _get(base, "/leads?status=evil'--&sort=;drop")
        assert "30 shown" in page

        # sort by quote size: the $4,500 quote outranks the $900 one
        page = _get(base, "/leads?sort=quoted")
        assert page.index("Lead Number02") < page.index("Lead Number01"), "quote sort"

        # per-row write works from the page (CSRF-gated like every write)
        data = urllib.parse.urlencode({"do": "lead_touch", "id": ids[5], "kind": "called",
                                       "token": serve.TOKEN}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
        row = ops.lead_get(ocon, ids[5])
        assert row["status"] == "working" and row["last_touch"], "called didn't land"

        # the ▶ dispatch link carries the lead id, and the brief bakes the context in
        assert f"lead={ids[6]}" in _get(base, "/leads"), "dispatch link lost the lead id"
        brief = dispatch.build_brief("Call them back", "meridian", lead_id=ids[6])
        assert "## LEAD CONTEXT" in brief and "Lead Number06" in brief
        assert f"lead id: {ids[6]}" in brief and "(555) 010-0006" in brief
        q = urllib.parse.urlencode({"task": "Call them back", "venture": "meridian",
                                    "lead": ids[6]})
        page = _get(base, f"/do?{q}")
        assert "LEAD CONTEXT" in page, "/do dropped the lead context"

        # hostile lead text renders escaped
        ops.add_lead(ocon, "<script>alert(1)</script>", "(555) 010-9999",
                     "<img src=x onerror=alert(2)>", venture="meridian")
        page = _get(base, "/leads")
        assert "<script>alert(1)</script>" not in page, "name XSS"
        assert "<img src=x" not in page, "service XSS"
        httpd.shutdown()
        ocon.close()
    print("leads workspace gate: full list, search/filter/sort whitelists, per-row "
          "writes, lead-context dispatch, XSS-escaped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
