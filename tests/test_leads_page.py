#!/usr/bin/env python3
"""Pipeline board gate: /leads renders the WHOLE ledger segmented by stage,
search/stage/sort filters work and are whitelisted, per-row writes land (and can
land back on the board), the per-lead ▶ dispatch bakes the lead's context into
the brief, and hostile lead text renders escaped. Exit 0 = green. Fictional
fixtures (555 numbers)."""
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

        # seed 30 leads across stages
        ids = []
        for i in range(30):
            ids.append(ops.add_lead(ocon, f"Lead Number{i:02d}", f"(555) 010-{i:04d}",
                                    "full detail", f"note {i}", venture="meridian"))
        ops.touch_lead(ocon, ids[1], "quoted", 900)
        ops.touch_lead(ocon, ids[2], "quoted", 4500)
        ops.touch_lead(ocon, ids[3], "collected", 1200)   # -> won
        ops.touch_lead(ocon, ids[4], "lost")
        ops.touch_lead(ocon, ids[7], "called")            # -> contacted
        ops.lead_set_stage(ocon, ids[8], "talking")
        counts = ops.leads_stage_counts(ocon)
        assert counts["all"] == 30 and counts["won"] == 1 and counts["lost"] == 1, counts
        assert counts["quoted"] == 2 and counts["contacted"] == 1 \
            and counts["talking"] == 1 and counts["new"] == 24, counts

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        # the whole ledger renders as a segmented board — no row cap
        page = _get(base, "/leads")
        assert page.count("Lead Number") >= 30, "board capped the list"
        assert "PIPELINE — 30 leads" in page, "header count wrong"
        for needle in ("NEW · 24", "CONTACTED · 1", "TALKING · 1", "QUOTED · 2",
                       "WON · 1", "LOST · 1"):
            assert needle in page, f"stage section missing: {needle}"
        # stage chips carry live counts
        assert "new 24" in page and "quoted 2" in page, "chips missing counts"

        # ?stage=X flat view; junk stage falls back to the full board
        page = _get(base, "/leads?stage=quoted")
        assert "Lead Number01" in page and "Lead Number02" in page
        assert "Lead Number05" not in page, "stage filter leaked other stages"
        page = _get(base, "/leads?stage=evil'--")
        assert "PIPELINE — 30 leads" in page and "NEW · 24" in page, \
            "junk stage must fall back to the board"

        # search filters; query text is literal (LIKE-escaped)
        page = _get(base, "/leads?q=" + urllib.parse.quote("Number07"))
        assert "Lead Number07" in page and "Lead Number08" not in page
        page = _get(base, "/leads?q=" + urllib.parse.quote("%"))
        assert "Lead Number" not in page, "LIKE wildcard leaked through"

        # sort by quote size on the flat view: $4,500 outranks $900
        page = _get(base, "/leads?stage=quoted&sort=quoted")
        assert page.index("Lead Number02") < page.index("Lead Number01"), "quote sort"
        # junk sort falls back safely
        _get(base, "/leads?stage=quoted&sort=;drop")

        # per-row write works and the board redirect is honored (CSRF-gated)
        data = urllib.parse.urlencode({"do": "lead_touch", "id": ids[5], "kind": "called",
                                       "back": "/leads", "token": serve.TOKEN}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
        row = ops.lead_get(ocon, ids[5])
        assert row["status"] == "working" and row["stage"] == "contacted", dict(row)
        # stage move from the board's select
        data = urllib.parse.urlencode({"do": "lead_stage", "id": ids[5], "stage": "talking",
                                       "back": "/leads", "token": serve.TOKEN}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
        assert ops.lead_get(ocon, ids[5])["stage"] == "talking"

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
    print("pipeline board gate: stage segments + counts, filter/sort whitelists, "
          "per-row writes + stage moves, lead-context dispatch, XSS-escaped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
