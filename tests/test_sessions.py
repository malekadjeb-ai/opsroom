#!/usr/bin/env python3
"""Sessions gate: the live-agent registry reader surfaces fresh sessions, labels
cowork/background distinctly, drops stale ones, and never raises on junk. Fictional
fixtures. Exit 0 = green."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "cfg")
        from opsroom import sessions
        reg = Path(td) / "reg"
        reg.mkdir()

        now_ms = 1_000_000_000_000
        # patch "now" by controlling freshness window: use age via updatedAt vs a big window
        (reg / "a.json").write_text(json.dumps({
            "sessionId": "a", "cwd": "/x/proj", "kind": "cowork",
            "name": "ship the thing", "status": "busy", "updatedAt": now_ms}))
        (reg / "b.json").write_text(json.dumps({
            "sessionId": "b", "cwd": "/x/proj", "kind": "interactive",
            "name": "poke around", "status": "idle", "updatedAt": now_ms - 5 * 60 * 1000}))
        (reg / "stale.json").write_text(json.dumps({
            "sessionId": "c", "cwd": "/x", "kind": "interactive",
            "name": "old", "updatedAt": now_ms - 10 * 60 * 60 * 1000}))  # 10h old
        (reg / "junk.json").write_text("{not json")
        (reg / "notdict.json").write_text("[1,2,3]")

        # freshness window measured from real now; our fixtures use a fixed epoch far
        # in the past, so use a window that reaches them: pass a huge window and assert
        # cowork labelling + junk resilience via a monkeypatched _age_seconds.
        sessions._age_seconds = lambda ms: 0 if ms and ms >= now_ms - 6 * 60 * 1000 else 1e9
        rows = sessions.live(reg)
        names = {r["name"] for r in rows}
        assert "ship the thing" in names and "poke around" in names, names
        assert "old" not in names, "stale session not dropped"
        cowork = [r for r in rows if r["is_cowork"]]
        assert len(cowork) == 1 and cowork[0]["name"] == "ship the thing", cowork
        assert cowork[0]["kind"] == "cowork" and cowork[0]["status"] == "busy"

        summ = sessions.summary(reg)
        assert summ["live"] == 2 and summ["cowork"] == 1, summ

        # missing registry / junk-only never raises
        assert sessions.live(Path(td) / "nope") == []
        print("sessions gate: live filter, cowork labelling, stale drop, junk-safe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
