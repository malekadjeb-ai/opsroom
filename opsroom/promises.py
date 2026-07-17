"""Promise extractor — the anti-leak. Every AI session stages asks ("6 drafts await
your send", "say the word", "waiting on your go") that then die in scrollback. This
scans recently-modified Claude Code + Codex session logs (read-only), pulls those lines
out, and holds them in the ledger until you act. Text is capped and deduped by a
normalized hash; sources are never written.

Stored in ops.db so a `purge`/re-sync of the activity ledger never drops them."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ventures

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
LOOKBACK_DAYS = 10
MAX_TEXT = 300
MAX_PER_SCAN = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS promises (
  id         TEXT PRIMARY KEY,
  ts         TEXT NOT NULL,
  venture    TEXT,
  session_id TEXT,
  text       TEXT NOT NULL,
  status     TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS promise_marks (
  path  TEXT PRIMARY KEY,
  mtime REAL
);
"""

# Staged-ask language: the response is parked waiting on the operator.
PATTERNS = re.compile(
    r"(?i)\bSTAGED\b|await(?:s|ing)? your|say the word|press send|your (?:explicit )?go\b|"
    r"blocked on you\b|one word from you|needs? your (?:word|approval|go|call|sign-?off)|"
    r"waiting on you\b|only you can|ready (?:for you )?to (?:send|ship|post|publish)|"
    r"just say|whenever you'?re ready")
# Narration bleed: markdown scaffolding, meta about the ledger itself, hedge phrases.
NOISE = re.compile(r"(?i)^\s*(?:[#>\-*|]|\d+[.)])|\bfor example\b|\be\.g\.\b|https?://|\*\*|"
                   r"\bledger\b|\bextractor\b|context pack|scoped but held")


def _ensure(con):
    con.executescript(SCHEMA)


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.lower().strip()))[:200]


def extract_from_text(text: str):
    """Staged-ask lines from one response. Pure; short imperative single-sentence asks
    only — long multi-clause narration is filtered out."""
    out = []
    for raw in text.split("\n"):
        ln = raw.strip().strip("*_`")
        if not (12 < len(ln) < 170):
            continue
        if ln.count(".") > 2 or ln.count(",") > 3:
            continue
        if NOISE.search(raw.strip()):
            continue
        if PATTERNS.search(ln):
            out.append(ln[:MAX_TEXT])
    return out


def _claude_texts(line: str):
    if '"assistant"' not in line:
        return
    try:
        d = json.loads(line)
    except ValueError:
        return
    if d.get("type") != "assistant" or d.get("isSidechain") or d.get("isMeta"):
        return
    content = (d.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else \
        (content if isinstance(content, list) else [])
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
            yield d.get("timestamp"), d.get("sessionId"), d.get("cwd", ""), b["text"]


def _codex_texts(line: str):
    if '"assistant"' not in line and '"output_text"' not in line:
        return
    try:
        d = json.loads(line)
    except ValueError:
        return
    if d.get("type") != "response_item":
        return
    p = d.get("payload") or {}
    if p.get("type") != "message" or p.get("role") != "assistant":
        return
    content = p.get("content")
    if isinstance(content, list):
        text = "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "output_text")
        if text.strip():
            yield d.get("timestamp"), None, "", text


def scan(con, now=None) -> int:
    """Scan recently-modified agent session logs for staged asks. Returns new count."""
    _ensure(con)
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=LOOKBACK_DAYS)).timestamp()
    marks = {r["path"]: r["mtime"] for r in con.execute("SELECT * FROM promise_marks")}
    found = 0
    files = []
    for root, glob in ((CLAUDE_PROJECTS, "*/*.jsonl"), (CODEX_SESSIONS, "**/*.jsonl")):
        if root.is_dir():
            try:
                files += [(f, _claude_texts if "claude" in str(root) else _codex_texts)
                          for f in root.glob(glob)]
            except OSError:
                continue
    for f, reader in sorted(files, key=lambda x: _safe_mtime(x[0])):
        mtime = _safe_mtime(f)
        if not mtime or mtime < cutoff or marks.get(str(f)) == mtime:
            continue
        try:
            with open(f, errors="replace") as fh:
                for line in fh:
                    if found >= MAX_PER_SCAN:
                        break
                    for ts, sid, cwd, text in reader(line):
                        for ask in extract_from_text(text):
                            pid = "p" + hashlib.sha1(_norm(ask).encode()).hexdigest()[:14]
                            cur = con.execute(
                                """INSERT OR IGNORE INTO promises(id, ts, venture, session_id, text)
                                   VALUES (?,?,?,?,?)""",
                                (pid, ts or now.isoformat(), ventures.attribute(cwd or ""),
                                 sid, ask))
                            found += cur.rowcount
        except OSError:
            continue
        con.execute("INSERT OR REPLACE INTO promise_marks(path, mtime) VALUES (?,?)",
                    (str(f), mtime))
    con.commit()
    return found


def _safe_mtime(f):
    try:
        return f.stat().st_mtime
    except OSError:
        return 0


def open_promises(con, limit=20):
    _ensure(con)
    return con.execute(
        "SELECT * FROM promises WHERE status='open' ORDER BY ts DESC LIMIT ?",
        (limit,)).fetchall()


def promise_set(con, pid: str, op: str):
    _ensure(con)
    status = {"done": "done", "dismiss": "dismissed"}.get(op, "done")
    con.execute("UPDATE promises SET status=? WHERE id=?", (status, pid))
    con.commit()
