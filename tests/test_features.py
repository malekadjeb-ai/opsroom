#!/usr/bin/env python3
"""Ported-feature gate: promise extraction, capture inbox, context pack. Exit 0 = green."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        from opsroom import promises, ops, contextpack, db, state

        # promise extraction: staged asks in, narration out
        text = ("\n".join([
            "I refactored the parser and cleaned up the tests, which took a while and involved several files.",
            "6 drafts are staged — press send when you're ready.",
            "The 3 proposals are ready to send; just say the word.",
            "For example, you might consider a different approach here later on.",
            "- a bulleted narration line waiting on you that should be filtered as noise scaffolding",
            "This is blocked on you: record the Loom.",
        ]))
        asks = promises.extract_from_text(text)
        assert any("press send" in a for a in asks), asks
        assert any("say the word" in a for a in asks), asks
        assert any("record the Loom" in a for a in asks), asks
        assert not any("For example" in a for a in asks), asks
        assert not any(a.startswith("-") for a in asks), asks
        assert not any("refactored the parser" in a for a in asks), asks

        # promises persist + dedupe + status transitions
        ocon = ops.connect()
        promises._ensure(ocon)
        for a in asks:
            import hashlib
            pid = "p" + hashlib.sha1(promises._norm(a).encode()).hexdigest()[:14]
            ocon.execute("INSERT OR IGNORE INTO promises(id,ts,venture,session_id,text) "
                         "VALUES (?,?,?,?,?)", (pid, "2026-07-17T00:00:00Z", "basin", "s1", a))
        ocon.commit()
        n_open = len(promises.open_promises(ocon))
        assert n_open == len(asks), (n_open, len(asks))
        first = promises.open_promises(ocon)[0]
        promises.promise_set(ocon, first["id"], "dismiss")
        assert len(promises.open_promises(ocon)) == n_open - 1

        # capture inbox
        ops.capture(ocon, "call the accountant about Q3")
        caps = ops.captures_open(ocon)
        assert len(caps) == 1 and "accountant" in caps[0]["text"], caps
        ops.capture_set(ocon, caps[0]["id"], "file")
        assert len(ops.captures_open(ocon)) == 0

        # context pack builds and includes the live sections without raising
        con = db.connect()
        ops.capture(ocon, "a fresh unfiled thought")
        st = state.build_state(con)
        pack = contextpack.build(con, ocon, st)
        assert "OPERATOR CONTEXT PACK" in pack
        assert "SITREP" in pack and "GROUND RULE" in pack
        assert "OPEN PROMISES" in pack  # we still have open promises
        assert "a fresh unfiled thought" in pack  # inbox surfaced
        con.close()

        # v0.6.1: today_tape uses UTC bounds for the LOCAL day — an entry stamped
        # just before local midnight (UTC ts) must not smear into two days' tapes.
        from datetime import datetime, timedelta, timezone
        s, e = ops._local_day_utc_bounds()
        assert s < e and (datetime.fromisoformat(e) - datetime.fromisoformat(s)) == timedelta(days=1)
        ocon.execute("INSERT INTO cash (ts, amount, venture, what) VALUES (?,?,?,?)",
                     (e, 999, "x", "tomorrow"))  # first instant of tomorrow, exclusive
        ocon.commit()
        assert ops.today_tape(ocon)["cash"] != 999, "tomorrow's entry leaked into today's tape"

        # v0.6.1: daily_writeback no longer NameErrors — dry-run returns a real block
        from opsroom import views
        try:
            views.daily_writeback(con2 := db.connect(), dry_run=True)
        finally:
            con2.close()
        ocon.close()
    print("features gate: promises, capture, context pack, tape bounds, daily writeback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
