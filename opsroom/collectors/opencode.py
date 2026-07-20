"""Collector: OpenCode (github.com/anomalyco/opencode, npm opencode-ai) session history.

Confirmed against source at tag v1.18.3: despite older docs describing a flat per-session
JSON tree, current OpenCode persists everything in one SQLite database,
~/.local/share/opencode/opencode.db (xdg-basedir always resolves there, even on macOS,
unless XDG_DATA_HOME is set) — `project`/`session` tables hold real columns, `message`/
`part` rows carry most fields inside a JSON `data` blob. This collector reads that DB
directly, read-only (`file:...?mode=ro`), so it never contends with OpenCode's own writer.
Venture attribution follows the session's recorded working directory, falling back to the
project's worktree root, same rule as the other collectors.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .. import ventures
from . import Emitter, file_changed, record_file

NOISE_PART_TYPES = {"reasoning", "file", "step-start", "step-finish", "snapshot",
                    "patch", "agent", "subtask", "retry", "compaction"}


def _db_path() -> Path:
    import os
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "opencode" / "opencode.db"


def _label(path: str) -> str:
    return Path(path).name if path else "?"


def _first_line(s: str, n: int = 180) -> str:
    return (s or "").strip().split("\n")[0][:n]


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    db_path = _db_path()
    if not db_path.is_file():
        return {"status": "no db", "events_new": 0, "events_seen": 0, "dropped": 0}
    st = db_path.stat()
    changed, last_ms = file_changed(con, str(db_path), st.st_mtime, st.st_size)
    if not changed:
        return {"events_new": 0, "events_seen": 0, "dropped": 0, "sessions_seen": 0}
    try:
        oc = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        oc.row_factory = sqlite3.Row
    except sqlite3.OperationalError as e:
        print(f"  [opencode] unreadable {db_path}: {e}")
        return {"events_new": 0, "events_seen": 0, "dropped": 0, "sessions_seen": 0}
    sessions = {}
    rows = []
    try:
        projects = {r["id"]: r["worktree"] for r in oc.execute("SELECT id, worktree FROM project")}
        for r in oc.execute("SELECT id, project_id, directory FROM session"):
            path = r["directory"] or projects.get(r["project_id"], "")
            sessions[r["id"]] = path
        rows = oc.execute(
            """SELECT p.session_id AS session_id, p.time_created AS time_created,
                      p.data AS part_data, m.data AS message_data
               FROM part p JOIN message m ON m.id = p.message_id
               WHERE p.time_created > ? ORDER BY p.time_created, p.id""",
            (last_ms or 0,)).fetchall()
    except sqlite3.DatabaseError as e:
        print(f"  [opencode] schema mismatch in {db_path}: {e}")
        oc.close()
        return {"events_new": 0, "events_seen": 0, "dropped": 0, "sessions_seen": 0}
    finally:
        oc.close()
    seen_sessions = set()
    new_watermark = last_ms or 0
    for row in rows:
        new_watermark = max(new_watermark, row["time_created"] or 0)
        try:
            part = json.loads(row["part_data"])
            msg = json.loads(row["message_data"])
        except (TypeError, json.JSONDecodeError):
            continue
        sid = row["session_id"]
        path = sessions.get(sid, "")
        base = dict(ts=_iso(row["time_created"]), source="opencode", session_id=sid,
                    venture=ventures.attribute(path), project=_label(path),
                    raw_ref=f"{db_path}#part={sid}:{row['time_created']}")
        seen_sessions.add(sid)
        ptype = part.get("type")
        role = msg.get("role")
        if ptype == "text":
            text = (part.get("text") or "").strip()
            if not text:
                continue
            if role == "user":
                em.emit(kind="prompt", actor="you", summary=_first_line(text), detail=text, **base)
            elif role == "assistant":
                em.emit(kind="response", actor="opencode", summary=_first_line(text),
                        detail=text, **base)
        elif ptype == "tool":
            state = part.get("state") or {}
            name = part.get("tool") or "tool"
            hint = _first_line(json.dumps(state.get("input") or {}), 120)
            em.emit(kind="tool_call", actor="opencode", summary=f"{name}: {hint}", **base)
            output = state.get("output")
            if output:
                em.emit(kind="tool_result", actor="opencode", summary=_first_line(str(output)),
                        detail=str(output), **base)
        elif ptype in NOISE_PART_TYPES or ptype is None:
            continue
    if not dry_run:
        record_file(con, str(db_path), st.st_mtime, st.st_size, new_watermark)
    return {"parts_scanned": len(rows), "sessions_seen": len(seen_sessions),
            "events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped}
