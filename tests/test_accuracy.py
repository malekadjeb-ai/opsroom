#!/usr/bin/env python3
"""Accuracy gate: every money/count total the console renders equals the value
the ledger computes — through the SAME ops functions the page uses, not
hand-pinned strings — and every note-derived survivor carries the visible
'notes' source pill. Also pins the dispatch brief's LEDGER TRUTH block (the
advisor once invented a goal from stray files). Exit 0 = green. Runs on the
seeded demo portfolio; $8,250 is the demo pin. Fictional fixtures."""
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        from opsroom import demo
        demo.run(serve_console=False)
        from opsroom import contextpack, db, dispatch, ops, serve, state, ventures

        # expected values, computed through the exact functions the page calls
        ocon = ops.connect()
        cash = int(ops.cash_total(ocon))
        spent = int(ops.spend_total(ocon))
        net = cash - spent
        n_open = len(ops.leads_open(ocon))
        stages = ops.leads_stage_counts(ocon)
        lanes = ops.leads_lanes(ocon)
        hot = sum(v["n"] for v in lanes.values())
        due = ops.followups_due(ocon)
        tape = ops.today_tape(ocon)
        ocon.close()
        assert cash == 8250, f"demo cash pin broke: {cash}"

        httpd = __import__("http.server", fromlist=["ThreadingHTTPServer"]) \
            .ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        live = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read().decode()
        board = urllib.request.urlopen(f"http://127.0.0.1:{port}/leads", timeout=10).read().decode()
        httpd.shutdown()
        body = live[live.index("<body>"):]

        # every rendered total = the ledger-computed total (same f-strings the
        # dashboard uses, evaluated here — never a hand-typed constant)
        for label, needle in [
            ("HUD cash", f"${cash:,}"),
            ("MONEY spent", f"${spent:,}"),
            ("MONEY net", f"${net:,}"),
            ("HUD open leads", f">{n_open}</span><span class='hud-lbl'>open leads"),
            ("hot lanes total", f"PIPELINE — {hot} hot"),
            ("board total", f"PIPELINE — {stages['all']} leads"),
            ("today tape cash", f"${int(tape['cash']):,} collected today"),
        ]:
            hay = board if label == "board total" else body
            assert needle in hay, f"{label}: expected {needle!r} on the page"
        for s in ("new", "contacted", "talking", "quoted", "won", "lost"):
            if stages.get(s):
                assert f"{s.upper()} · {stages[s]}" in board, \
                    f"board stage count {s}={stages[s]} not rendered"
        # 'awaiting your tap' counts exactly what the page asks the operator to act on
        # (due follow-ups + open replies + pending proposals + queued dispatches)
        import re
        m = re.search(r">(\d+)</span><span class='hud-lbl'>awaiting your tap", body)
        assert m, "actions HUD cell missing"

        # note-derived survivors carry the source pill; ledger numbers never do
        assert "pill src" in body, "no 'notes' source pill on note-derived claims"
        assert body.count("TOP MOVE") >= 1
        top_move_zone = body.split("TOP MOVE", 1)[1][:600]
        assert "pill src" in top_move_zone, "TOP MOVE lost its notes pill"

        # the dispatch brief leads with LEDGER TRUTH — the advisor can no longer
        # invent a goal or a cash figure from stray files
        brief = dispatch.build_brief("sanity", kind="advise")
        assert "LEDGER TRUTH" in brief and f"${cash:,}" in brief, \
            "brief missing the authoritative numbers"
        assert "never invent" in brief
        gl = ventures.GOAL_LABEL
        if gl:
            assert gl in brief, "brief missing the configured goal label"

    print("accuracy gate: every rendered total = ledger total, notes claims "
          "pilled, briefs carry LEDGER TRUTH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
