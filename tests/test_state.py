#!/usr/bin/env python3
"""state parser gate: table parsing must survive format drift, and build_state must
never raise when notes are unreadable. Exit 0 = green."""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(name, cond, detail=""):
    if not cond:
        FAILURES.append(f"FAIL {name}: {detail}")


NOTE = """---
title: Sprint Dashboard
type: dashboard
updated: 2026-07-16
---

# Dash

## Live state
| Metric | Value | As of |
|---|---|---|
| Days to goal | **19** | 2026-07-16 |
| Cash collected vs $50K | **$8,250 collected** | 2026-07-12 |
| Acme pipeline | 2 proposals out. Blocking: case study | 2026-07-16 |
| Open leads | ~14 unanswered, aged ~6 days | 2026-07-11 |
| Baseline revenue | ~$2.1K/mo recurring | note |

## Today's one move
Finish the case study.

Second paragraph ignored.

Honest band: realistic $28-39K, stretch $55K.
"""

CONFIG = """[goal]
amount = 50000
deadline = "2026-08-04"
label = "test sprint"

[paths]
scan_roots = ["{root}"]
notes_roots = ["{notes}"]
dashboard_note = "{note}"
pipeline_dir = "{pipes}"

[[venture]]
key = "acme"
label = "Acme"
track = "A"
trap = false
live_prefix = "acme"
keywords = ["acme"]

[[venture]]
key = "sideq"
label = "Side Quest"
trap = true
keywords = ["side quest", "sideq"]
"""


def main():
    from opsroom import state
    p = state.parse_dashboard(NOTE)
    check("updated", p["updated"] == "2026-07-16", p["updated"])
    check("five rows", len(p["rows"]) == 5, p["rows"])
    check("bold stripped", state.live_find(p["rows"], "days to goal")["raw"] == "19")
    check("find cash", state.live_find(p["rows"], "cash")["raw"].startswith("$8,250"))
    check("find leads by substring", state.live_find(p["rows"], "lead")["raw"].startswith("~14"))
    check("one move first para", p["one_move"] == "Finish the case study.", p["one_move"])
    check("band", p["band"].startswith("realistic"), p["band"])

    check("money 0", state._money("$0 tracked") == 0)
    check("money K", state._money("$4K") == 4000)
    check("money comma", state._money("$8,250 collected") == 8250)
    check("money M", state._money("$1.5M") == 1_500_000)
    check("money none", state._money("no dollars") is None)
    t = date(2026, 7, 16)
    check("aged + elapsed", state._aged_days("aged ~10 days", "2026-07-11", t) == 15)
    check("aged no as_of", state._aged_days("aged ~10 days", "", t) == 10)

    tbl = state.parse_md_tables("""# T
| # | Company | Type | Location | Phone |
|---|---|---|---|---|
| 1 | Cobalt | 3PL | Reno | (555) 201-4410 |
| 2 | | | | |
""")
    check("table parsed", len(tbl) == 1 and len(tbl[0]["rows"]) == 1, tbl)
    check("header keys", tbl[0]["rows"][0]["Company"] == "Cobalt")

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "cfg").mkdir(); (tdp / "data").mkdir(); (tdp / "notes").mkdir(); (tdp / "pipes").mkdir()
        note = tdp / "notes" / "dash.md"
        note.write_text(NOTE)
        (tdp / "notes" / "Decisions Log.md").write_text(
            "- **2026-07-16** — Sent the Acme proposal — done.\n"
            "- **2026-07-12** — Paused side quest (trap).\n")
        (tdp / "pipes" / "acme-targets.md").write_text("""# Acme
## TOUCH LOG
| Target | Channel | Status | Draft/next |
|---|---|---|---|
| Cobalt | email | DRAFTED | send |
| Kestrel | PHONE | on call sheet | (555) 883-4409 |
""")
        (tdp / "cfg" / "config.toml").write_text(CONFIG.format(
            root=td, notes=tdp / "notes", note=note, pipes=tdp / "pipes"))
        os.environ["OPSROOM_CONFIG_DIR"] = str(tdp / "cfg")
        os.environ["OPSROOM_DATA_DIR"] = str(tdp / "data")
        from opsroom import config, db, ventures
        config.load(force=True)
        ventures.refresh()
        db.DB_DIR = tdp / "data"
        db.DB_PATH = db.DB_DIR / "activity.db"
        con = db.connect()
        s = state.build_state(con)
        check("days computed", s["days_to_goal"] == (date(2026, 8, 4) - date.today()).days)
        check("cash parsed", s["cash_usd"] == 8250, s["cash_usd"])
        check("leads", s["leads_n"] == 14, s["leads_n"])
        check("venture live", s["venture_live"]["acme"]["raw"].startswith("2 proposals"))
        check("unblock stays first", s["next"]["acme"][0].startswith("UNBLOCK FIRST"), s["next"]["acme"])
        check("leads land second (no track-C owner -> first revenue venture)",
              "open leads NEWEST FIRST" in s["next"]["acme"][1], s["next"]["acme"])
        check("touch actions", any("Send draft" in a for a in s["next"]["acme"]), s["next"]["acme"])
        check("trap frozen", s["next"]["sideq"][0].startswith("FROZEN"))
        check("history", len(s["history"].get("acme", [])) == 1, s["history"])
        check("rollup all", {v["key"] for v in s["ventures"]} == {"acme", "sideq"})
        # degrade: point the note somewhere unreadable, cache must carry it
        (tdp / "cfg" / "config.toml").write_text(CONFIG.format(
            root=td, notes=tdp / "notes", note=tdp / "gone" / "x.md", pipes=tdp / "pipes"))
        config.load(force=True)
        ventures.refresh()
        s2 = state.build_state(con)
        check("degraded flagged", bool(s2["degraded"]), s2["degraded"])
        check("cache fallback", s2["cash_usd"] == 8250, s2["cash_usd"])
        con.close()
        os.environ.pop("OPSROOM_CONFIG_DIR"); os.environ.pop("OPSROOM_DATA_DIR")

    if FAILURES:
        print("\n".join(FAILURES))
        print(f"\nstate gate: {len(FAILURES)} FAILURE(S)")
        return 1
    print("state gate: all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
