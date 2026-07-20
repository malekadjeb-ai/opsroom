"""Collector: OpenAI Codex CLI session logs (~/.codex/sessions/**/*.jsonl rollout files,
plus archived_sessions). Strictly read-only on sources. One rollout file = one session;
venture attribution follows session_meta/turn_context cwd, same rule as the Claude collector."""
import json
from pathlib import Path

from .. import ventures
from . import Emitter, file_changed, record_file

CODEX_DIR = Path.home() / ".codex"
TOOL_CALL_TYPES = {"function_call", "custom_tool_call", "local_shell_call"}
SKIP_PREFIXES = ("<permissions", "<environment_context", "<user_instructions",
                 "<recommended_plugins", "<system-reminder", "<turn_aborted")


def _project_of(cwd: str) -> str:
    if not cwd:
        return "?"
    home = str(Path.home())
    rel = cwd[len(home):].strip("/\\") if cwd.startswith(home) else cwd
    return rel or "~"


def _first_line(s: str, n: int = 180) -> str:
    return (s or "").strip().split("\n")[0][:n]


def _text_of(content) -> str:
    """Join input_text/output_text blocks; content may also be a bare string."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join((b.get("text") or "") for b in content
                     if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")).strip()


class _FileCtx:
    """Per-rollout-file session context (one session per file)."""

    def __init__(self):
        self.session_id = None
        self.cwd = ""

    def base(self, ts, raw_ref):
        return dict(ts=ts, source="codex", session_id=self.session_id,
                    venture=ventures.attribute(self.cwd),
                    project=_project_of(self.cwd), raw_ref=raw_ref)


def _parse_line(em: Emitter, ctx: _FileCtx, d: dict, raw_ref: str) -> None:
    t = d.get("type")
    p = d.get("payload") or {}
    ts = d.get("timestamp")
    if t == "session_meta":
        ctx.session_id = p.get("id") or p.get("session_id") or ctx.session_id
        ctx.cwd = p.get("cwd") or ctx.cwd
        return
    if t == "turn_context":
        ctx.cwd = p.get("cwd") or ctx.cwd
        return
    if t != "response_item" or not ts or not ctx.session_id:
        return
    pt = p.get("type")
    if pt == "message":
        role = p.get("role")
        text = _text_of(p.get("content"))
        if not text or text.startswith(SKIP_PREFIXES):
            return
        if role == "user":
            em.emit(kind="prompt", actor="you", summary=_first_line(text), detail=text,
                    **ctx.base(ts, raw_ref))
        elif role == "assistant":
            em.emit(kind="response", actor="codex", summary=_first_line(text), detail=text,
                    **ctx.base(ts, raw_ref))
        # developer/system messages are harness noise: skipped
    elif pt in TOOL_CALL_TYPES:
        name = p.get("name") or pt
        hint = _first_line(str(p.get("arguments") or p.get("input") or p.get("command") or ""), 120)
        em.emit(kind="tool_call", actor="codex", summary=f"{name}: {hint}",
                **ctx.base(ts, raw_ref))
    elif pt in ("function_call_output", "custom_tool_call_output"):
        out = p.get("output")
        text = _text_of(out) if isinstance(out, list) else str(out or "")
        if text:
            em.emit(kind="tool_result", actor="codex", summary=_first_line(text),
                    detail=text, **ctx.base(ts, raw_ref))


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    files = []
    for sub in ("sessions", "archived_sessions"):
        root = CODEX_DIR / sub
        if root.is_dir():
            files.extend(sorted(root.glob("**/*.jsonl")))
    parsed_files = 0
    sessions = set()
    for f in files:
        st = f.stat()
        changed, start_line = file_changed(con, str(f), st.st_mtime, st.st_size)
        if not changed:
            continue
        parsed_files += 1
        ctx = _FileCtx()
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
                        # already ingested: replay only session ctx (id/cwd), emit nothing
                        if d.get("type") in ("session_meta", "turn_context"):
                            _parse_line(em, ctx, d, "")
                        continue
                    _parse_line(em, ctx, d, f"{f}:{lineno}")
        except OSError as e:
            print(f"  [codex] unreadable {f}: {e}")
            continue
        if ctx.session_id:
            sessions.add(ctx.session_id)
        if not dry_run:
            record_file(con, str(f), st.st_mtime, st.st_size, lineno)
    return {"files_scanned": len(files), "files_parsed": parsed_files,
            "sessions_seen": len(sessions),
            "events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped}
