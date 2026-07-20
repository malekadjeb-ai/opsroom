"""Collector: Google Gemini CLI session logs (~/.gemini/tmp/<slug>/chats/**/*.jsonl).
Strictly read-only on sources. One JSONL file = one session (subagent sessions nest one
level deeper under chats/<parentSessionId>/); venture attribution follows the project's
absolute path via the sibling .project_root marker file, same rule as the Codex collector.

Format confirmed against gemini-cli source (packages/core/src/services/chatRecordingService.ts,
projectRegistry.ts) as of the 0.51.0 release: a metadata line ({sessionId, startTime, kind, ...})
followed by message lines ({id, timestamp, type: user|gemini|info|error|warning, content, ...}),
plus occasional control lines ({"$set": {...}} / {"$rewindTo": id}) that this collector skips —
a /chat rewind in Gemini CLI will not retroactively remove events already ingested here.
"""
import json
from pathlib import Path

from .. import ventures
from . import Emitter, file_changed, record_file

GEMINI_DIR = Path.home() / ".gemini"
NOISE_TYPES = {"info", "error", "warning"}


def _project_root_for(f: Path) -> str:
    for parent in f.parents:
        marker = parent / ".project_root"
        if marker.is_file():
            try:
                return marker.read_text(errors="replace").strip()
            except OSError:
                return ""
        if parent.name == "tmp":
            break
    return ""


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join((c.get("text") or "") for c in content if isinstance(c, dict)).strip()


def _first_line(s: str, n: int = 180) -> str:
    return (s or "").strip().split("\n")[0][:n]


class _FileCtx:
    def __init__(self, project: str):
        self.session_id = None
        self.project = project or "?"
        self.venture = ventures.attribute(project)

    def base(self, ts, raw_ref):
        return dict(ts=ts, source="gemini", session_id=self.session_id,
                    venture=self.venture, project=self.project, raw_ref=raw_ref)


def _parse_line(em: Emitter, ctx: _FileCtx, d: dict, raw_ref: str) -> None:
    if "sessionId" in d and "startTime" in d:
        ctx.session_id = d.get("sessionId") or ctx.session_id
        return
    if "$set" in d or "$rewindTo" in d:
        return  # metadata patch / rewind marker: not an event
    t = d.get("type")
    ts = d.get("timestamp")
    if not ts or not ctx.session_id or t in NOISE_TYPES:
        return
    text = _text_of(d.get("content"))
    if t == "user":
        if text:
            em.emit(kind="prompt", actor="you", summary=_first_line(text), detail=text,
                    **ctx.base(ts, raw_ref))
    elif t == "gemini":
        if text:
            em.emit(kind="response", actor="gemini", summary=_first_line(text), detail=text,
                    **ctx.base(ts, raw_ref))
        for tc in d.get("toolCalls") or []:
            if not isinstance(tc, dict):
                continue
            name = tc.get("name") or tc.get("displayName") or "tool"
            tc_ts = tc.get("timestamp") or ts
            hint = _first_line(json.dumps(tc.get("args") or {}), 120)
            em.emit(kind="tool_call", actor="gemini", summary=f"{name}: {hint}",
                    **ctx.base(tc_ts, raw_ref))
            result_text = _text_of(tc.get("result"))
            if result_text:
                em.emit(kind="tool_result", actor="gemini", summary=_first_line(result_text),
                        detail=result_text, **ctx.base(tc_ts, raw_ref))


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    files = sorted(GEMINI_DIR.glob("tmp/*/chats/**/*.jsonl")) if GEMINI_DIR.is_dir() else []
    parsed_files = 0
    sessions = set()
    for f in files:
        st = f.stat()
        changed, start_line = file_changed(con, str(f), st.st_mtime, st.st_size)
        if not changed:
            continue
        parsed_files += 1
        ctx = _FileCtx(_project_root_for(f))
        lineno = 0
        try:
            with open(f, errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        d = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if lineno <= start_line:
                        if "sessionId" in d and "startTime" in d:
                            _parse_line(em, ctx, d, "")
                        continue
                    _parse_line(em, ctx, d, f"{f}:{lineno}")
        except OSError as e:
            print(f"  [gemini] unreadable {f}: {e}")
            continue
        if ctx.session_id:
            sessions.add(ctx.session_id)
        if not dry_run:
            record_file(con, str(f), st.st_mtime, st.st_size, lineno)
    return {"files_scanned": len(files), "files_parsed": parsed_files,
            "sessions_seen": len(sessions),
            "events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped}
