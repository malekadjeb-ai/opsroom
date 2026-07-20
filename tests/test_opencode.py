#!/usr/bin/env python3
"""OpenCode collector gate: synthetic opencode.db must produce attributed events,
skip harness-only part types, and re-run without duplicates. Exit 0 = green."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SID = "ses_test0001"


def seed(db_path, project_dir, extra_ms=None):
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE IF NOT EXISTS project (id TEXT PRIMARY KEY, worktree TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS session (id TEXT PRIMARY KEY, project_id TEXT, directory TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS message (id TEXT PRIMARY KEY, session_id TEXT, data TEXT)")
    con.execute("""CREATE TABLE IF NOT EXISTS part (id TEXT PRIMARY KEY, message_id TEXT,
                   session_id TEXT, time_created INTEGER, data TEXT)""")
    if extra_ms is None:
        con.execute("INSERT INTO project VALUES (?,?)", ("prj_1", project_dir))
        con.execute("INSERT INTO session VALUES (?,?,?)", (SID, "prj_1", project_dir))
        con.execute("INSERT INTO message VALUES (?,?,?)",
                    ("msg_1", SID, json.dumps({"role": "user"})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                    ("prt_1", "msg_1", SID, 1752345600000,
                     json.dumps({"type": "text", "text": "fix the webhook retry bug"})))
        con.execute("INSERT INTO message VALUES (?,?,?)",
                    ("msg_2", SID, json.dumps({"role": "assistant"})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                    ("prt_2", "msg_2", SID, 1752345601000, json.dumps({"type": "step-start"})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                    ("prt_3", "msg_2", SID, 1752345602000,
                     json.dumps({"type": "tool", "tool": "edit",
                                "state": {"status": "completed",
                                          "input": {"file_path": "webhook.py"},
                                          "output": "Edited webhook.py"}})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                    ("prt_4", "msg_2", SID, 1752345603000,
                     json.dumps({"type": "text", "text": "Fixed: retries now use backoff."})))
    else:
        con.execute("INSERT INTO message VALUES (?,?,?)",
                    ("msg_3", SID, json.dumps({"role": "user"})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                    ("prt_5", "msg_3", SID, extra_ms,
                     json.dumps({"type": "text", "text": "now add a test"})))
    con.commit()
    con.close()


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        project_dir = str(Path.home() / "code" / "shopkit-plugin")
        oc_home = Path(td) / "opencodehome"
        oc_home.mkdir(parents=True)
        db_path = oc_home / "opencode.db"
        seed(str(db_path), project_dir)

        from opsroom import db
        from opsroom.collectors import opencode
        opencode._db_path = lambda: db_path
        con = sqlite3.connect(":memory:")
        con.executescript(db.SCHEMA)
        con.row_factory = sqlite3.Row

        r = opencode.collect(con)
        assert r["dropped"] == 0, r
        rows = con.execute("SELECT kind, actor, venture, project, summary FROM events ORDER BY ts").fetchall()
        kinds = [x["kind"] for x in rows]
        assert kinds == ["prompt", "tool_call", "tool_result", "response"], kinds
        assert rows[0]["actor"] == "you" and "webhook" in rows[0]["summary"], dict(rows[0])
        assert rows[1]["summary"].startswith("edit:"), dict(rows[1])
        assert all("shopkit-plugin" in x["project"] for x in rows), [dict(x) for x in rows]

        # incremental: unchanged db re-run emits nothing new
        r2 = opencode.collect(con)
        assert r2["events_new"] == 0, r2

        # a new part appended (db mtime/size change) is picked up without duplicating
        seed(str(db_path), project_dir, extra_ms=1752345700000)
        r3 = opencode.collect(con)
        assert r3["events_new"] == 1, r3
        total = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        assert total == 5, total

        from opsroom import enrich
        n = enrich.build_sessions(con)
        assert n == 1, n
        s = con.execute("SELECT source, prompt_count FROM sessions").fetchone()
        assert s["source"] == "opencode" and s["prompt_count"] == 2, dict(s)
    print("opencode gate: parse, attribute, skip step markers, incremental, sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
