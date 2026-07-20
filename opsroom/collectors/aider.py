"""Collector: Aider session history (.aider.chat.history.md at each git repo's root).
Strictly read-only on sources. Discovery piggybacks on the git collector's repo scan
(same roots opsroom already walks for commits), so venture attribution is the repo path,
same rule as the other collectors.

Format, confirmed against aider's source (aider/io.py): one repo-wide append-only
markdown log. `# aider chat started at YYYY-MM-DD HH:MM:SS` marks a new launch; every
line of a user turn is separately prefixed `#### `; the assistant's raw response follows
unprefixed; `> Applied edit to FILE` lines are aider's own tool-confirmation echoes, not
LLM content. Aider logs only ONE real timestamp per launch (not per turn), so turn
timestamps here are synthesized by advancing one second per event from that anchor —
good enough for ordering, not wall-clock-accurate. `.aider.input.history` has per-turn
timestamps but duplicates the same prompt text; left out to keep this collector simple.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path

from .. import ventures
from . import Emitter, file_changed, record_file
from . import git as _git

SESSION_RE = re.compile(r"^# aider chat started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$")
APPLIED_RE = re.compile(r"^>\s*(Applied edit to .+)$")


class _FileCtx:
    """Per-repo parse state. `em=None` (used for replaying already-ingested lines after
    a resume) rebuilds session/timing context without re-emitting anything."""

    def __init__(self, repo: str):
        self.repo = repo
        self.project = repo.rsplit("/", 1)[-1]
        self.venture = ventures.attribute(repo)
        self.session_id = None
        self.next_ts = None
        self.state = "none"  # none | user | response
        self.user_buf = []
        self.resp_buf = []
        self.applied = []

    def _tick(self) -> str:
        ts = self.next_ts
        self.next_ts = ts + timedelta(seconds=1)
        return ts.isoformat()

    def set_session(self, when: str):
        self.session_id = f"aider:{self.repo}:{when}"
        self.next_ts = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
        self.state, self.user_buf, self.resp_buf, self.applied = "none", [], [], []

    def flush_user(self, em):
        text = "\n".join(self.user_buf).strip()
        self.user_buf = []
        if text and em is not None and self.session_id:
            em.emit(ts=self._tick(), source="aider", kind="prompt", actor="you",
                    summary=text.split("\n")[0][:180], detail=text,
                    session_id=self.session_id, venture=self.venture, project=self.project)

    def flush_response(self, em):
        text = "\n".join(self.resp_buf).strip()
        self.resp_buf = []
        if text and em is not None and self.session_id:
            em.emit(ts=self._tick(), source="aider", kind="response", actor="aider",
                    summary=text.split("\n")[0][:180], detail=text,
                    session_id=self.session_id, venture=self.venture, project=self.project)
        applied, self.applied = self.applied, []
        if em is not None and self.session_id:
            for a in applied:
                em.emit(ts=self._tick(), source="aider", kind="tool_result", actor="aider",
                        summary=a[:180], session_id=self.session_id,
                        venture=self.venture, project=self.project)

    def flush(self, em):
        if self.state == "user":
            self.flush_user(em)
        elif self.state == "response":
            self.flush_response(em)
        self.state = "none"

    def add_user_line(self, text: str, em):
        if self.state == "response":
            self.flush_response(em)
        self.state = "user"
        self.user_buf.append(text)

    def add_applied(self, text: str):
        self.applied.append(text)

    def add_other_line(self, line: str, em):
        if self.state == "user":
            self.flush_user(em)
        self.state = "response"
        self.resp_buf.append(line)


def _parse_line(em, ctx: _FileCtx, line: str) -> None:
    m = SESSION_RE.match(line)
    if m:
        ctx.flush(em)
        ctx.set_session(m.group(1))
        return
    if ctx.session_id is None:
        return  # preamble before the first launch heading: nothing to attribute it to
    if line.startswith("#### "):
        ctx.add_user_line(line[len("#### "):], em)
        return
    stripped = line.strip()
    am = APPLIED_RE.match(stripped)
    if am:
        ctx.add_applied(am.group(1))
        return
    if stripped.startswith(">"):
        return  # other tool confirmations/prompts: noise
    ctx.add_other_line(line, em)


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    files = []
    for repo in _git.discover_repos():
        f = Path(repo) / ".aider.chat.history.md"
        if f.is_file():
            files.append((repo, f))
    parsed_files = 0
    sessions = set()
    for repo, f in files:
        st = f.stat()
        changed, start_line = file_changed(con, str(f), st.st_mtime, st.st_size)
        if not changed:
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError as e:
            print(f"  [aider] unreadable {f}: {e}")
            continue
        parsed_files += 1
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()  # trailing "\n" produces a phantom empty element, not a real line
        ctx = _FileCtx(repo)
        for line in lines[:start_line]:
            _parse_line(None, ctx, line)  # context-only replay: rebuild session/timing state
        ctx.flush(None)  # a prior run always ends at a clean flush; mirror that before resuming
        for line in lines[start_line:]:
            _parse_line(em, ctx, line)
        ctx.flush(em)
        if ctx.session_id:
            sessions.add(ctx.session_id)
        if not dry_run:
            record_file(con, str(f), st.st_mtime, st.st_size, len(lines))
    return {"files_scanned": len(files), "files_parsed": parsed_files,
            "sessions_seen": len(sessions),
            "events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped}
