#!/usr/bin/env python3
"""Migration gate: a pre-0.11 ops.db (no stage/source/intent/next_due/first_seen/
link columns) opens cleanly, the backfill derives stages ONLY from data already
in the rows, and re-opening is idempotent. Exit 0 = green."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# the leads table exactly as v0.10.x created it
OLD_SCHEMA = """
CREATE TABLE touches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, venture TEXT, target TEXT NOT NULL, kind TEXT NOT NULL, note TEXT
);
CREATE TABLE leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  added TEXT NOT NULL, name TEXT NOT NULL, phone TEXT, service TEXT, note TEXT,
  status TEXT DEFAULT 'open', last_touch TEXT, quoted REAL, collected REAL,
  venture TEXT
);
CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT);
"""

ROWS = [
    # (name, status, quoted, last_touch, note, kind_touch) -> expected stage
    ("Won Deal", "won", 500, "2026-07-01", "", None, "won"),
    ("Lost Deal", "lost", None, "2026-07-01", "", None, "lost"),
    ("Quoted Live", "working", 380, "2026-07-10", "", None, "quoted"),
    ("Reply In Note", "working", None, "2026-07-10", "reply: https://x.example", None, "talking"),
    ("Reply In Touches", "working", None, "2026-07-10", "", "replied", "talking"),
    ("Touched Once", "working", None, "2026-07-10", "called, left vm", None, "contacted"),
    ("Fresh Import", "open", None, None, "lead date 2026-07-16", None, "new"),
]


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        from opsroom import ops

        # build a raw pre-0.11 db at the exact path ops.connect() will use
        p = ops.db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(p)
        raw.executescript(OLD_SCHEMA)
        for name, status, quoted, lt, note, ktouch, _ in ROWS:
            raw.execute(
                "INSERT INTO leads (added, name, phone, note, status, quoted, last_touch)"
                " VALUES ('2026-07-05T00:00:00+00:00', ?, '555-0100', ?, ?, ?, ?)",
                (name, note, status, quoted, lt))
            if ktouch:
                raw.execute("INSERT INTO touches (ts, target, kind) VALUES (?,?,?)",
                            ("2026-07-10T00:00:00+00:00", name, ktouch))
        raw.commit()
        raw.close()

        con = ops.connect()  # migration + backfill fire here
        cols = {r[1] for r in con.execute("PRAGMA table_info(leads)")}
        for c in ("stage", "source", "intent", "next_due", "first_seen", "link"):
            assert c in cols, f"missing column {c}"

        got = {r["name"]: r for r in con.execute("SELECT * FROM leads")}
        for name, *_, want in ROWS:
            assert got[name]["stage"] == want, (name, got[name]["stage"], want)
        # source heuristic: 'lead date' note → import; else manual
        assert got["Fresh Import"]["source"] == "import"
        assert got["Touched Once"]["source"] == "manual"
        # first_seen: parsed from the flattened note when present, else added date
        assert got["Fresh Import"]["first_seen"] == "2026-07-16", dict(got["Fresh Import"])
        assert got["Won Deal"]["first_seen"] == "2026-07-05"
        assert ops.kv_get(con, "leads_v11_backfill") == "1"

        # idempotent: touch a stage by hand, reopen, backfill must NOT rerun
        con.execute("UPDATE leads SET stage='quoted' WHERE name='Fresh Import'")
        con.commit()
        con.close()
        con2 = ops.connect()
        assert con2.execute("SELECT stage FROM leads WHERE name='Fresh Import'") \
            .fetchone()["stage"] == "quoted", "backfill reran and clobbered a stage"

        # lead_set_stage: whitelist + status mirror; touch_lead never demotes
        lid = con2.execute("SELECT id FROM leads WHERE name='Quoted Live'").fetchone()["id"]
        assert ops.lead_set_stage(con2, lid, "talking") is True
        assert ops.lead_set_stage(con2, lid, "junkstage") is False
        assert ops.lead_set_stage(con2, 99999, "new") is False
        row = ops.lead_get(con2, lid)
        assert row["stage"] == "talking" and row["status"] == "working", dict(row)
        ops.touch_lead(con2, lid, "called")     # contact touch must not demote
        assert ops.lead_get(con2, lid)["stage"] == "talking"
        ops.touch_lead(con2, lid, "quoted", 450)
        assert ops.lead_get(con2, lid)["stage"] == "quoted"
        ops.touch_lead(con2, lid, "collected", 450)
        row = ops.lead_get(con2, lid)
        assert row["stage"] == "won" and row["status"] == "won", dict(row)

        # add_lead: junk stage/source fall back, status mirrors stage
        nid = ops.add_lead(con2, "New Guy", "555-0199", stage="bogus", source="bogus")
        row = ops.lead_get(con2, nid)
        assert row["stage"] == "new" and row["source"] == "manual" \
            and row["status"] == "open", dict(row)

        counts = ops.leads_stage_counts(con2)
        assert counts["all"] == 8 and counts["won"] == 2, counts
        buckets = ops.leads_by_stage(con2)
        assert {s for s in buckets} == set(ops.STAGES)
        assert sum(len(v) for v in buckets.values()) == 8
        con2.close()
    print("migration gate: pre-0.11 db opens, stage backfill honest, idempotent, "
          "stage verbs whitelisted + status mirrored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
