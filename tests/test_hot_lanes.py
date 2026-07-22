#!/usr/bin/env python3
"""Hot-lanes gate: ops.leads_lanes buckets the ledger into REPLIED / DUE TODAY /
NEW TODAY / QUOTED-going-cold with no double-counting, LOCAL-date semantics
(an 11pm lead is today, not UTC-tomorrow), the cold boundary at 3 days, and the
NOW page renders all four lanes through the same _lead_row grammar as the
board. Exit 0 = green. Fictional fixtures."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[goal]
amount = 50000
deadline = "2099-12-31"
label = "Q3 $50K sprint"

[[venture]]
key = "meridian"
label = "Meridian Consulting"
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, ops, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        today = datetime.now().astimezone().date()
        now_utc = datetime.now(timezone.utc)

        def backdate(lid, days, col="last_touch"):
            ocon.execute(f"UPDATE leads SET {col}=? WHERE id=?",
                         ((now_utc - timedelta(days=days)).isoformat(), lid))
            ocon.commit()

        # one lead per lane
        replied = ops.add_lead(ocon, "Talky Corp", "5550001111", stage="talking")
        due = ops.add_lead(ocon, "Cadence Co", "5550002222",
                           next_due=today.isoformat(), first_seen="2020-01-01")
        overdue = ops.add_lead(ocon, "Overdue LLC", "5550003333",
                               next_due=(today - timedelta(days=2)).isoformat(),
                               first_seen="2020-01-01")
        new = ops.add_lead(ocon, "Fresh Inc", "5550004444")  # first_seen defaults today
        cold = ops.add_lead(ocon, "Chilly Quotes", "5550005555", stage="quoted",
                            first_seen="2020-01-01")
        backdate(cold, 4)
        warm = ops.add_lead(ocon, "Warm Quotes", "5550006666", stage="quoted",
                            first_seen="2020-01-01")
        backdate(warm, 2)  # touched 2d ago: NOT cold (boundary is 3)
        # a won lead in a hot state never lanes (closed is closed)
        wonl = ops.add_lead(ocon, "Won Already", "5550007777", stage="talking")
        ops.lead_set_stage(ocon, wonl, "won")

        lanes = ops.leads_lanes(ocon)
        names = {k: [r["name"] for r in v["rows"]] for k, v in lanes.items()}
        assert names["replied"] == ["Talky Corp"], names
        assert set(names["due"]) == {"Cadence Co", "Overdue LLC"}, names
        assert lanes["due"]["rows"][0]["name"] == "Overdue LLC", "overdue must sort first"
        assert names["new"] == ["Fresh Inc"], names
        assert names["cold"] == ["Chilly Quotes"], f"cold boundary broken: {names}"
        assert "Warm Quotes" not in names["cold"], "2-day-old touch is not cold"

        # LOCAL-date semantics: a lead whose UTC 'added' is tomorrow (11pm local
        # in a negative-offset zone) still counts as first-seen TODAY when
        # first_seen carries the local date add_lead now writes
        row = ocon.execute("SELECT first_seen FROM leads WHERE id=?", (new,)).fetchone()
        assert row["first_seen"] == today.isoformat(), \
            f"first_seen {row['first_seen']!r} is not the local date"
        # and _local_date converts stored-UTC timestamps to local calendar days
        utc_ts = datetime(2026, 1, 2, 4, 30, tzinfo=timezone.utc).isoformat()
        local = datetime(2026, 1, 2, 4, 30, tzinfo=timezone.utc).astimezone().date()
        assert ops._local_date(utc_ts) == local.isoformat()
        assert ops._local_date("2026-01-02") == "2026-01-02"  # bare dates pass through

        # no double-counting: a lead that's replied AND due lanes once, as replied
        both = ops.add_lead(ocon, "Busy Bee", "5550008888", stage="talking",
                            next_due=today.isoformat(), first_seen="2020-01-01")
        lanes = ops.leads_lanes(ocon)
        hits = sum("Busy Bee" in [r["name"] for r in v["rows"]] for v in lanes.values())
        assert hits == 1, f"Busy Bee laned {hits} times"
        assert "Busy Bee" in [r["name"] for r in lanes["replied"]["rows"]]
        ocon.close()

        # the NOW page renders the lanes with counts, links into the board, and
        # the SAME row grammar (inline stage select = _lead_row's signature move)
        page = serve._page().decode()
        body = page[page.index("<body>"):]
        for needle in ("REPLIED · 2", "DUE TODAY · 2", "NEW TODAY · 1",
                       "GOING COLD · 1", "full board", "/leads?stage=talking"):
            assert needle in body, f"NOW lanes missing: {needle}"
        lanes_html = body.split("id='lanes'")[1].split("</div>")[0:]
        assert "Chilly Quotes" in body and "Talky Corp" in body
        assert body.count("name='do' value='lead_stage'") >= 4, \
            "lane rows lost their inline actions — not _lead_row"

    print("hot-lanes gate: four ledger lanes, local dates, 3-day cold boundary, "
          "no double counts, _lead_row grammar on NOW")
    return 0


if __name__ == "__main__":
    sys.exit(main())
