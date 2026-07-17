"""Collector: Claude Code CLI session logs (~/.claude/projects/**/*.jsonl) + task state
(~/.claude/tasks/<sessionId>/*.json). Strictly read-only on sources."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import ventures
from . import Emitter, file_changed, record_file

CLAUDE_DIR = Path.home() / ".claude"
FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "Read"}
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _project_of(cwd: str) -> str:
    if not cwd:
        return "?"
    home = str(Path.home())
    rel = cwd[len(home):].strip("/") if cwd.startswith(home) else cwd
    return rel or "~"


def _first_line(s: str, n: int = 180) -> str:
    return (s or "").strip().split("\n")[0][:n]


def _blocks(msg) -> list:
    c = (msg or {}).get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return c if isinstance(c, list) else []


def _tool_paths(name: str, inp: dict) -> list:
    paths = []
    if isinstance(inp, dict):
        for k in ("file_path", "path", "notebook_path"):
            if isinstance(inp.get(k), str):
                paths.append(inp[k])
    return paths


def _parse_line(em: Emitter, d: dict, raw_ref: str) -> None:
    t = d.get("type")
    if t not in ("user", "assistant") or d.get("isMeta"):
        return
    ts = d.get("timestamp")
    if not ts:
        return
    base = dict(ts=ts, source="cli", session_id=d.get("sessionId"),
                venture=ventures.attribute(d.get("cwd", "")),
                project=_project_of(d.get("cwd", "")), raw_ref=raw_ref,
                is_sidechain=1 if d.get("isSidechain") else 0)
    msg = d.get("message") or {}
    if t == "user":
        texts, results = [], []
        for b in _blocks(msg):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                texts.append(b.get("text") or "")
            elif b.get("type") == "tool_result":
                results.append(b)
        text = "\n".join(x for x in texts if x).strip()
        if text and not text.startswith(("<system-reminder", "<command-name", "<local-command")):
            em.emit(kind="prompt", actor="you", summary=_first_line(text), detail=text, **base)
        for r in results:
            content = r.get("content")
            if isinstance(content, list):
                content = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
            content = str(content or "")
            failed = bool(r.get("is_error"))
            em.emit(kind="error" if failed else "tool_result", actor="claude",
                    summary=("FAILED: " if failed else "") + _first_line(content),
                    detail=content, **base)
    else:  # assistant
        if d.get("isApiErrorMessage"):
            em.emit(kind="error", actor="claude",
                    summary=f"API error {d.get('apiErrorStatus', '?')}", **base)
            return
        for b in _blocks(msg):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and (b.get("text") or "").strip():
                em.emit(kind="response", actor="claude", summary=_first_line(b["text"]),
                        detail=b["text"], **base)
            elif b.get("type") == "tool_use":
                name = b.get("name", "?")
                inp = b.get("input") or {}
                paths = _tool_paths(name, inp)
                kind = "file_edit" if name in EDIT_TOOLS else "tool_call"
                hint = paths[0] if paths else _first_line(json.dumps(inp)[:150], 120)
                em.emit(kind=kind, actor="claude", summary=f"{name}: {hint}",
                        artifacts=paths or None, **base)


def _collect_tasks(em: Emitter, con, session_meta: dict) -> None:
    tasks_dir = CLAUDE_DIR / "tasks"
    if not tasks_dir.is_dir():
        return
    for f in tasks_dir.glob("*/*.json"):
        st = f.stat()
        changed, _ = file_changed(con, str(f), st.st_mtime, st.st_size)
        if not changed and not em.dry_run:
            continue
        try:
            d = json.loads(f.read_text(errors="replace"))
        except Exception:
            continue
        sid = f.parent.name
        meta = session_meta.get(sid) or _session_meta_from_db(con, sid)
        ts = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
        em.emit(ts=ts, source="cli", kind="task", actor="claude", session_id=sid,
                venture=meta.get("venture", "unknown"), project=meta.get("project", "?"),
                summary=f"[{d.get('status', '?')}] {d.get('subject', '?')}",
                detail=d.get("description", ""), raw_ref=str(f))
        if not em.dry_run:
            record_file(con, str(f), st.st_mtime, st.st_size, 1)


def _session_meta_from_db(con, sid: str) -> dict:
    row = con.execute(
        "SELECT venture, project FROM events WHERE session_id=? AND venture!='unknown' LIMIT 1",
        (sid,)).fetchone()
    return dict(row) if row else {}


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    files = sorted((CLAUDE_DIR / "projects").glob("*/*.jsonl"))
    parsed_files = 0
    session_meta = {}
    for f in files:
        st = f.stat()
        changed, start_line = file_changed(con, str(f), st.st_mtime, st.st_size)
        if not changed:
            continue
        parsed_files += 1
        lineno = 0
        try:
            with open(f, errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if lineno <= start_line:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("sessionId") and d.get("cwd"):
                        session_meta[d["sessionId"]] = {
                            "venture": ventures.attribute(d["cwd"]),
                            "project": _project_of(d["cwd"])}
                    _parse_line(em, d, f"{f}:{lineno}")
        except OSError as e:
            print(f"  [cli] unreadable {f}: {e}")
            continue
        if not dry_run:
            record_file(con, str(f), st.st_mtime, st.st_size, lineno)
    _collect_tasks(em, con, session_meta)
    return {"files_scanned": len(files), "files_parsed": parsed_files,
            "sessions_seen": len(session_meta),
            "events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped}
