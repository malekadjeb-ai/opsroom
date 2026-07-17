#!/usr/bin/env python3
"""Codex collector gate: synthetic rollout jsonl must produce attributed events,
tolerate malformed lines, and re-run without duplicates. Exit 0 = green."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SID = "test-codex-session-0001"


def rollout_lines(cwd):
    def row(t, payload, ts="2026-07-17T06:11:31.411Z"):
        return json.dumps({"timestamp": ts, "type": t, "payload": payload})
    return [
        row("session_meta", {"id": SID, "cwd": cwd}),
        row("turn_context", {"turn_id": "t1", "cwd": cwd}),
        "{ this line is corrupt",
        row("response_item", {"type": "message", "role": "developer",
                              "content": [{"type": "input_text", "text": "<permissions instructions>"}]}),
        row("response_item", {"type": "message", "role": "user",
                              "content": [{"type": "input_text", "text": "fix the webhook retry bug"}]},
            ts="2026-07-17T06:12:00.000Z"),
        row("response_item", {"type": "function_call", "name": "shell",
                              "arguments": "{\"cmd\": \"pytest\"}"},
            ts="2026-07-17T06:13:00.000Z"),
        row("response_item", {"type": "function_call_output", "call_id": "c1",
                              "output": "3 passed"},
            ts="2026-07-17T06:13:30.000Z"),
        row("response_item", {"type": "message", "role": "assistant",
                              "content": [{"type": "output_text", "text": "Fixed: retries now use backoff."}]},
            ts="2026-07-17T06:14:00.000Z"),
    ]


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        cwd = str(Path.home() / "code" / "shopkit-plugin")
        codex_home = Path(td) / "codexhome"
        day = codex_home / "sessions" / "2026" / "07" / "17"
        day.mkdir(parents=True)
        f = day / "rollout-2026-07-17T06-11-30-x.jsonl"
        f.write_text("\n".join(rollout_lines(cwd)) + "\n")

        from opsroom import db
        from opsroom.collectors import codex
        codex.CODEX_DIR = codex_home
        con = sqlite3.connect(":memory:")
        con.executescript(db.SCHEMA)
        con.row_factory = sqlite3.Row

        r = codex.collect(con)
        assert r["files_parsed"] == 1, r
        assert r["dropped"] == 0, r
        rows = con.execute("SELECT kind, actor, venture, summary FROM events ORDER BY ts").fetchall()
        kinds = [x["kind"] for x in rows]
        assert kinds == ["prompt", "tool_call", "tool_result", "response"], kinds
        assert rows[0]["actor"] == "you" and "webhook" in rows[0]["summary"], dict(rows[0])
        assert rows[3]["actor"] == "codex", dict(rows[3])
        # developer/permission messages must not leak in
        assert not any("<permissions" in (x["summary"] or "") for x in rows)
        # every event carries the cwd-derived project (venture is 'unknown' without config; path flows through)
        proj = con.execute("SELECT DISTINCT project FROM events").fetchall()
        assert len(proj) == 1 and "shopkit-plugin" in proj[0]["project"], [dict(p) for p in proj]

        # incremental: unchanged file re-run emits nothing new
        r2 = codex.collect(con)
        assert r2["events_new"] == 0 and r2["files_parsed"] == 0, r2

        # appended line gets picked up without duplicating the old ones
        with open(f, "a") as fh:
            fh.write(json.dumps({"timestamp": "2026-07-17T06:15:00.000Z", "type": "response_item",
                                 "payload": {"type": "message", "role": "user",
                                             "content": [{"type": "input_text", "text": "now add a test"}]}}) + "\n")
        r3 = codex.collect(con)
        assert r3["events_new"] == 1, r3
        total = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        assert total == 5, total

        # sessions build from codex events with the right source
        from opsroom import enrich
        n = enrich.build_sessions(con)
        assert n == 1, n
        s = con.execute("SELECT source, prompt_count FROM sessions").fetchone()
        assert s["source"] == "codex" and s["prompt_count"] == 2, dict(s)
    print("codex gate: parse, attribute, skip noise, incremental, sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
