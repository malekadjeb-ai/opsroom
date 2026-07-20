#!/usr/bin/env python3
"""Aider collector gate: synthetic .aider.chat.history.md (discovered via the git repo
scan) must produce attributed prompt/response/tool_result events, skip tool-confirmation
noise, and re-run without duplicates across a second launch. Exit 0 = green."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TURN_1 = (
    "\n# aider chat started at 2026-07-19 09:14:03\n\n\n"
    "#### add a retry with exponential backoff to the http client\n"
    "> Add retry with exponential backoff? (Y)es/(N)o/(D)on't ask again [Yes]: y\n\n"
    "I'll add exponential backoff retry logic to `http_client.py`.\n\n"
    "> Applied edit to http_client.py\n"
)
TURN_2 = (
    "\n# aider chat started at 2026-07-19 09:20:00\n\n\n"
    "#### now add a test\n\n"
    "Sure, adding a test now.\n\n"
    "> Applied edit to test_http_client.py\n"
)


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        scan_root = Path(td) / "scanroot"
        repo_dir = scan_root / "shopkit-plugin"
        (repo_dir / ".git").mkdir(parents=True)
        hist = repo_dir / ".aider.chat.history.md"
        hist.write_text(TURN_1)

        import sqlite3
        from opsroom import db, ventures
        from opsroom.collectors import aider
        ventures.SCAN_ROOTS = [str(scan_root)]
        con = sqlite3.connect(":memory:")
        con.executescript(db.SCHEMA)
        con.row_factory = sqlite3.Row

        r = aider.collect(con)
        assert r["files_parsed"] == 1, r
        assert r["dropped"] == 0, r
        rows = con.execute("SELECT kind, actor, venture, project, summary FROM events ORDER BY ts").fetchall()
        kinds = [x["kind"] for x in rows]
        assert kinds == ["prompt", "response", "tool_result"], kinds
        assert rows[0]["actor"] == "you" and "retry" in rows[0]["summary"], dict(rows[0])
        assert rows[1]["actor"] == "aider" and "backoff" in rows[1]["summary"], dict(rows[1])
        assert rows[2]["summary"] == "Applied edit to http_client.py", dict(rows[2])
        assert all("shopkit-plugin" in x["project"] for x in rows), [dict(x) for x in rows]
        # the (Y)es/(N)o confirmation prompt must not leak into the user's prompt text
        assert not any("Yes" in (x["summary"] or "") and x["kind"] == "prompt" for x in rows)

        # incremental: unchanged file re-run emits nothing new
        r2 = aider.collect(con)
        assert r2["events_new"] == 0 and r2["files_parsed"] == 0, r2

        # a second aider launch appended to the same repo's history is picked up in full
        with open(hist, "a") as fh:
            fh.write(TURN_2)
        r3 = aider.collect(con)
        assert r3["events_new"] == 3, r3
        total = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        assert total == 6, total

        from opsroom import enrich
        n = enrich.build_sessions(con)
        assert n == 2, n  # each aider launch is its own session (no cross-launch timestamp)
    print("aider gate: parse turns, attribute, skip tool-confirmation noise, incremental, sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
