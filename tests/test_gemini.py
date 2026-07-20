#!/usr/bin/env python3
"""Gemini CLI collector gate: synthetic session jsonl must produce attributed events,
tolerate malformed/control lines, and re-run without duplicates. Exit 0 = green."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SID = "test-gemini-session-0001"


def session_lines():
    def row(d):
        return json.dumps(d)
    return [
        row({"sessionId": SID, "projectHash": "deadbeef", "startTime": "2026-07-18T14:02:11.000Z",
             "lastUpdated": "2026-07-18T14:02:11.000Z", "kind": "main"}),
        "{ this line is corrupt",
        row({"id": "i-001", "timestamp": "2026-07-18T14:02:14.000Z", "type": "info",
             "content": [{"text": "session started"}]}),
        row({"id": "u-001", "timestamp": "2026-07-18T14:02:15.000Z", "type": "user",
             "content": [{"text": "fix the login bug"}]}),
        row({"id": "g-001", "timestamp": "2026-07-18T14:02:20.000Z", "type": "gemini",
             "content": [{"text": "I'll look at the auth module."}], "model": "gemini-2.5-pro",
             "toolCalls": [{"id": "tc-1", "name": "read_file", "args": {"path": "src/auth.ts"},
                            "result": [{"text": "...file contents..."}], "status": "success",
                            "timestamp": "2026-07-18T14:02:21.000Z"}]}),
        row({"$set": {"lastUpdated": "2026-07-18T14:05:00.000Z", "summary": "Fixed null-check"}}),
    ]


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        project = str(Path.home() / "code" / "shopkit-plugin")
        gemini_home = Path(td) / "geminihome"
        slug_dir = gemini_home / "tmp" / "shopkit-plugin"
        chats_dir = slug_dir / "chats"
        chats_dir.mkdir(parents=True)
        (slug_dir / ".project_root").write_text(project)
        f = chats_dir / "session-2026-07-18T14-02-a1b2c3d4.jsonl"
        f.write_text("\n".join(session_lines()) + "\n")

        from opsroom import db
        from opsroom.collectors import gemini
        gemini.GEMINI_DIR = gemini_home
        con = sqlite3.connect(":memory:")
        con.executescript(db.SCHEMA)
        con.row_factory = sqlite3.Row

        r = gemini.collect(con)
        assert r["files_parsed"] == 1, r
        assert r["dropped"] == 0, r
        rows = con.execute("SELECT kind, actor, venture, project, summary FROM events ORDER BY ts").fetchall()
        kinds = [x["kind"] for x in rows]
        assert kinds == ["prompt", "response", "tool_call", "tool_result"], kinds
        assert rows[0]["actor"] == "you" and "login bug" in rows[0]["summary"], dict(rows[0])
        assert rows[1]["actor"] == "gemini", dict(rows[1])
        assert rows[2]["summary"].startswith("read_file:"), dict(rows[2])
        assert all("shopkit-plugin" in x["project"] for x in rows), [dict(x) for x in rows]
        # info-type control noise must not leak in as an event
        assert not any("session started" in (x["summary"] or "") for x in rows)

        # incremental: unchanged file re-run emits nothing new
        r2 = gemini.collect(con)
        assert r2["events_new"] == 0 and r2["files_parsed"] == 0, r2

        # appended line gets picked up without duplicating the old ones
        with open(f, "a") as fh:
            fh.write(json.dumps({"id": "u-002", "timestamp": "2026-07-18T14:06:00.000Z",
                                 "type": "user", "content": [{"text": "now add a test"}]}) + "\n")
        r3 = gemini.collect(con)
        assert r3["events_new"] == 1, r3
        total = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        assert total == 5, total

        from opsroom import enrich
        n = enrich.build_sessions(con)
        assert n == 1, n
        s = con.execute("SELECT source, prompt_count FROM sessions").fetchone()
        assert s["source"] == "gemini" and s["prompt_count"] == 2, dict(s)
    print("gemini gate: parse, attribute, skip noise/control lines, incremental, sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
