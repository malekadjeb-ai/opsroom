#!/usr/bin/env python3
"""Cursor collector gate: synthetic globalStorage/workspaceStorage state.vscdb files
must produce attributed events via the workspace.json -> composer.composerData ->
cursorDiskKV chain, skip unattributable/malformed rows, and re-run without duplicates.
Exit 0 = green."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COMPOSER_ID = "cmp-0001"


def seed(base: Path, project_dir: str, extra_bubble=None):
    ws_dir = base / "workspaceStorage" / "abc123"
    global_dir = base / "globalStorage"
    ws_dir.mkdir(parents=True, exist_ok=True)
    global_dir.mkdir(parents=True, exist_ok=True)

    (ws_dir / "workspace.json").write_text(json.dumps({"folder": f"file://{project_dir}"}))
    wcon = sqlite3.connect(ws_dir / "state.vscdb")
    wcon.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    wcon.execute("INSERT OR REPLACE INTO ItemTable VALUES (?,?)",
                ("composer.composerData", json.dumps({"allComposers": [{"composerId": COMPOSER_ID}]})))
    wcon.commit()
    wcon.close()

    gcon = sqlite3.connect(global_dir / "state.vscdb")
    gcon.execute("CREATE TABLE IF NOT EXISTS cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    if extra_bubble is None:
        gcon.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?,?)",
                    (f"bubbleId:{COMPOSER_ID}:b1", json.dumps({
                        "bubbleId": "b1", "type": 1, "createdAt": "2026-07-18T14:02:15.000Z",
                        "text": "add a retry with exponential backoff"})))
        gcon.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?,?)",
                    (f"bubbleId:{COMPOSER_ID}:b2", json.dumps({
                        "bubbleId": "b2", "type": 2, "createdAt": "2026-07-18T14:02:20.000Z",
                        "text": "Added exponential backoff to the http client.",
                        "toolFormerData": {"name": "edit_file",
                                           "params": {"file_path": "http_client.py"},
                                           "result": "applied"}})))
        # a row with the right key shape but corrupt JSON must not crash the parser
        gcon.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?,?)",
                    (f"bubbleId:{COMPOSER_ID}:bad", "{not json"))
        # a row with the wrong key shape (missing the composerId segment) must be skipped too
        gcon.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?,?)",
                    ("bubbleId:malformed", "{}"))
    else:
        bid, text, ts = extra_bubble
        gcon.execute("INSERT OR REPLACE INTO cursorDiskKV VALUES (?,?)",
                    (f"bubbleId:{COMPOSER_ID}:{bid}", json.dumps({
                        "bubbleId": bid, "type": 1, "createdAt": ts, "text": text})))
    gcon.commit()
    gcon.close()


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        project_dir = str(Path.home() / "code" / "shopkit-plugin")
        base = Path(td) / "cursorhome"
        seed(base, project_dir)

        from opsroom import db
        from opsroom.collectors import cursor
        cursor._base_dir = lambda: base
        con = sqlite3.connect(":memory:")
        con.executescript(db.SCHEMA)
        con.row_factory = sqlite3.Row

        r = cursor.collect(con)
        assert r["dropped"] == 0, r
        rows = con.execute("SELECT kind, actor, venture, project, summary FROM events ORDER BY ts").fetchall()
        kinds = [x["kind"] for x in rows]
        assert kinds == ["prompt", "response", "tool_call", "tool_result"], kinds
        assert rows[0]["actor"] == "you" and "backoff" in rows[0]["summary"], dict(rows[0])
        assert rows[2]["summary"].startswith("edit_file:"), dict(rows[2])
        assert all("shopkit-plugin" in x["project"] for x in rows), [dict(x) for x in rows]

        # incremental: unchanged global db re-run emits nothing new
        r2 = cursor.collect(con)
        assert r2["events_new"] == 0, r2

        # a new bubble appended to the global db is picked up without duplicating the old ones
        seed(base, project_dir, extra_bubble=("b3", "now add a test", "2026-07-18T14:06:00.000Z"))
        r3 = cursor.collect(con)
        assert r3["events_new"] == 1, r3
        total = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        assert total == 5, total

        from opsroom import enrich
        n = enrich.build_sessions(con)
        assert n == 1, n
        s = con.execute("SELECT source, prompt_count FROM sessions").fetchone()
        assert s["source"] == "cursor" and s["prompt_count"] == 2, dict(s)
    print("cursor gate: parse, attribute via workspace.json+composerData, skip malformed, "
          "incremental, sessions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
