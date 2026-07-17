#!/usr/bin/env python3
"""Inbox gate: lead + reply drop importers — dedup rails, the reply->call-today
cadence, the exactly-once touch, malformed drops fail soft. Fictional fixtures
only (555 numbers, .example emails). Exit 0 = green."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


LEADS = {"leads": [
    {"name": "Kestrel Detailing", "phone": "(555) 010-0199", "service": "full detail",
     "note": "asked about pricing", "date": "2026-07-16", "link": "https://leads.example/k1"},
    {"name": "", "phone": "555-010-0245", "service": "interior"},
    {"name": "No Phone Person"},                       # unverifiable -> skipped
], "missed_calls": 3}

REPLIES = {"replies": [
    {"msg_id": "m-001", "date": "2026-07-16", "venture": "meridian",
     "target": "Kestrel Detailing", "from_name": "Sam", "from_email": "sam@kestrel.example",
     "subject": "Re: ops sprint", "snippet": "sounds good, can we talk Thursday?",
     "link": "https://mail.example/m-001"},
    {"from_email": "pat@harbor.example", "date": "2026-07-15", "subject": "Re: proposal"},
    {"snippet": "no email and no id"},                 # unverifiable -> skipped
]}


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        from opsroom import inbox, ops
        ocon = ops.connect()

        # ---- leads: import, dedup, missed-call count
        drop = Path(td) / "leads.json"
        drop.write_text(json.dumps(LEADS))
        r = inbox.import_leads(ocon, drop)
        assert r == {"added": 2, "skipped": 0, "missed_calls": 3}, r
        r = inbox.import_leads(ocon, drop)  # re-import: nothing doubles
        assert r["added"] == 0 and r["skipped"] == 2, r
        leads = ops.leads_open(ocon)
        assert len(leads) == 2, [dict(x) for x in leads]
        named = {x["name"] for x in leads}
        assert "Kestrel Detailing" in named and "interior lead" in named, named
        k = next(x for x in leads if x["name"] == "Kestrel Detailing")
        assert "lead date 2026-07-16" in k["note"] and "leads.example" in k["note"], k["note"]
        assert ops.kv_get(ocon, "missed_calls") == "3"
        # same phone, different formatting -> still a dupe
        drop.write_text(json.dumps({"leads": [{"name": "K again", "phone": "5550100199"}]}))
        r = inbox.import_leads(ocon, drop)
        assert r["added"] == 0 and r["skipped"] == 1, r

        # ---- replies: import, exactly-once touch, call-today follow-up
        drop2 = Path(td) / "replies.json"
        drop2.write_text(json.dumps(REPLIES))
        r = inbox.merge_replies(ocon, json.loads(drop2.read_text()))
        assert r == {"added": 2, "skipped": 0}, r
        opens = inbox.open_replies(ocon)
        assert len(opens) == 2
        due = ops.followups_due(ocon)
        assert len(due) == 2 and all("call now" in d["note"] for d in due), \
            [dict(d) for d in due]
        tape = ops.today_tape(ocon)
        assert tape["touches"] == 2, tape
        # re-ingest: the touch/follow-up NEVER double-counts
        r = inbox.import_replies(ocon, drop2)
        assert r["added"] == 0 and r["skipped"] == 2, r
        assert ops.today_tape(ocon)["touches"] == 2
        assert len(ops.followups_due(ocon)) == 2
        # handled clears it from the board
        inbox.reply_set(ocon, opens[0]["id"], "handled")
        assert len(inbox.open_replies(ocon)) == 1

        # ---- malformed drops fail soft, never raise
        bad = Path(td) / "bad.json"
        bad.write_text("{nope")
        assert inbox.import_leads(ocon, bad)["error"]
        assert inbox.import_replies(ocon, bad)["error"]
        assert inbox.import_leads(ocon, Path(td) / "missing.json")["error"]
        bad.write_text('["a list, not an object"]')
        assert inbox.import_replies(ocon, bad)["error"]

        # ---- watch_tick ingests on mtime change only
        lp = inbox.leads_drop_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps({"leads": [{"name": "Tick Lead", "phone": "555-010-0777"}]}))
        assert inbox.watch_tick(ocon) is True
        assert inbox.watch_tick(ocon) is False  # unchanged file: no re-ingest
        ocon.close()
    print("inbox gate: lead dedup, reply exactly-once, call-today cadence, fail-soft drops")
    return 0


if __name__ == "__main__":
    sys.exit(main())
