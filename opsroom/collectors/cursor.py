"""Collector: Cursor chat/composer history. Strictly read-only (`file:...?mode=ro` SQLite
URIs, never opened for write) so this never contends with Cursor's own DB.

Cursor's local storage is undocumented, reverse-engineered, and has shifted across
versions — this targets the CURRENT (2025-2026) layout, cross-checked against the
saharmor/cursor-view and S2thend/cursor-history projects:

  <base>/globalStorage/state.vscdb  (table cursorDiskKV)
    key "bubbleId:<composerId>:<bubbleId>" -> one message: {type: 1=user/2=assistant,
    text, createdAt, toolFormerData: {name, params, result}, ...}
  <base>/workspaceStorage/<hash>/state.vscdb  (table ItemTable, standard VS Code KV)
    key "composer.composerData" -> which composer sessions belong to this workspace
    (schema for this key is the least-confirmed part of this collector; parsed
    defensively, degrading to "no attribution" rather than raising)
  <base>/workspaceStorage/<hash>/workspace.json -> {"folder": "file:///abs/path"},
    the hash -> project-path mapping, with a state.vscdb history.entries fallback.

<base> is %APPDATA%/Cursor/User (Windows), ~/Library/Application Support/Cursor/User
(macOS), or ~/.config/Cursor/User (Linux). Older Cursor versions kept chat data
entirely in the legacy ItemTable key `workbench.panel.aichat.view.aichat.chatdata`
instead of cursorDiskKV; that layout isn't covered here yet (falls through to "no
events", never crashes) — a good follow-up once someone confirms it against a real
old install, same as this collector's own schema should be reconfirmed against a
live Cursor install (this PR was written without access to one — see the
opsroom/collectors/cursor.py-vs-issue-#2 note in the PR description).
"""
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from .. import ventures
from . import Emitter, file_changed, record_file


def _base_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User"
    if sys.platform == "win32":
        import os
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "Cursor" / "User"
    return Path.home() / ".config" / "Cursor" / "User"


def _first_line(s: str, n: int = 180) -> str:
    return (s or "").strip().split("\n")[0][:n]


def _file_uri_to_path(uri: str) -> str:
    if not uri.startswith("file://"):
        return ""
    return unquote(urlparse(uri).path)


def _workspace_project(ws_dir: Path) -> str:
    wj = ws_dir / "workspace.json"
    if wj.is_file():
        try:
            data = json.loads(wj.read_text(errors="replace"))
            path = _file_uri_to_path(data.get("folder") or data.get("workspace") or "")
            if path:
                return path
        except (OSError, json.JSONDecodeError):
            pass
    db = ws_dir / "state.vscdb"
    if not db.is_file():
        return ""
    try:
        wcon = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = wcon.execute("SELECT value FROM ItemTable WHERE key='history.entries'").fetchone()
        wcon.close()
        if row:
            for entry in json.loads(row[0]):
                path = _file_uri_to_path(((entry or {}).get("editor") or {}).get("resource", ""))
                if path:
                    return str(Path(path).parent)
    except (sqlite3.DatabaseError, OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    return ""


def _composer_ids(ws_db: Path) -> set:
    """Which composer sessions were opened in this workspace. Undocumented key shape:
    tries the shapes seen in community tooling, skips (never raises) if none match."""
    try:
        wcon = sqlite3.connect(f"file:{ws_db}?mode=ro", uri=True)
        row = wcon.execute("SELECT value FROM ItemTable WHERE key='composer.composerData'").fetchone()
        wcon.close()
    except sqlite3.DatabaseError:
        return set()
    if not row:
        return set()
    try:
        data = json.loads(row[0])
    except json.JSONDecodeError:
        return set()
    ids = set()
    candidates = data.get("allComposers") if isinstance(data, dict) else data
    if isinstance(candidates, list):
        for c in candidates:
            if isinstance(c, dict):
                cid = c.get("composerId") or c.get("id")
                if cid:
                    ids.add(cid)
            elif isinstance(c, str):
                ids.add(c)
    return ids


def _iso(ts) -> str:
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
    return str(ts)


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    gdb = _base_dir() / "globalStorage" / "state.vscdb"
    if not gdb.is_file():
        return {"status": "no db", "events_new": 0, "events_seen": 0, "dropped": 0}
    st = gdb.stat()
    changed, _ = file_changed(con, str(gdb), st.st_mtime, st.st_size)
    if not changed:
        return {"events_new": 0, "events_seen": 0, "dropped": 0, "sessions_seen": 0}

    composer_project = {}
    ws_root = _base_dir() / "workspaceStorage"
    if ws_root.is_dir():
        for ws_dir in ws_root.iterdir():
            if not ws_dir.is_dir():
                continue
            project = _workspace_project(ws_dir)
            if not project:
                continue
            for cid in _composer_ids(ws_dir / "state.vscdb"):
                composer_project[cid] = project

    try:
        gcon = sqlite3.connect(f"file:{gdb}?mode=ro", uri=True)
        gcon.row_factory = sqlite3.Row
        if not gcon.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                            "name='cursorDiskKV'").fetchone():
            gcon.close()
            return {"status": "no cursorDiskKV table (older Cursor version, unsupported)",
                    "events_new": 0, "events_seen": 0, "dropped": 0}
        rows = gcon.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'").fetchall()
        gcon.close()
    except sqlite3.DatabaseError as e:
        print(f"  [cursor] unreadable {gdb}: {e}")
        return {"events_new": 0, "events_seen": 0, "dropped": 0, "sessions_seen": 0}

    sessions = set()
    for row in rows:
        parts = row["key"].split(":", 2)
        if len(parts) != 3:
            continue
        _, composer_id, _bubble_id = parts
        try:
            b = json.loads(row["value"])
        except json.JSONDecodeError:
            continue
        btype = b.get("type")
        ts = b.get("createdAt")
        if btype not in (1, 2) or not ts:
            continue
        project = composer_project.get(composer_id, "")
        session_id = f"cursor:{composer_id}"
        sessions.add(session_id)
        base = dict(ts=_iso(ts), source="cursor", session_id=session_id,
                    venture=ventures.attribute(project),
                    project=Path(project).name if project else "?", raw_ref=f"{gdb}#{row['key']}")
        text = (b.get("text") or "").strip()
        if text:
            if btype == 1:
                em.emit(kind="prompt", actor="you", summary=_first_line(text), detail=text, **base)
            else:
                em.emit(kind="response", actor="cursor", summary=_first_line(text), detail=text, **base)
        tfd = b.get("toolFormerData")
        if isinstance(tfd, dict) and tfd.get("name"):
            hint = _first_line(json.dumps(tfd.get("params") or {}), 120)
            em.emit(kind="tool_call", actor="cursor", summary=f"{tfd['name']}: {hint}", **base)
            result = tfd.get("result")
            if result:
                rtext = result if isinstance(result, str) else json.dumps(result)
                em.emit(kind="tool_result", actor="cursor", summary=_first_line(rtext),
                        detail=rtext, **base)

    if not dry_run:
        record_file(con, str(gdb), st.st_mtime, st.st_size, 0)
    return {"bubbles_scanned": len(rows), "sessions_seen": len(sessions),
            "events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped}
