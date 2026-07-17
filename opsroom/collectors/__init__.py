"""Shared collector plumbing: redact-gated event emission, per-file watermarks."""
import hashlib
import json
import sys
from datetime import datetime, timezone

from .. import redact as _redact

MAX_DETAIL = 4096


def norm_ts(ts: str) -> str:
    """Normalize any ISO8601 timestamp (Z, ±hh:mm, or naive) to canonical UTC 'YYYY-MM-DDTHH:MM:SS.mmmZ'
    so lexicographic SQL comparisons are correct across sources."""
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Emitter:
    """Buffers redacted events and writes them idempotently. Fail-closed on redaction errors."""

    def __init__(self, con, dry_run: bool = False):
        self.con = con
        self.dry_run = dry_run
        self.inserted = 0
        self.seen = 0
        self.dropped = 0

    def emit(self, *, ts, source, kind, actor, summary, detail="", session_id=None,
             venture=None, project=None, artifacts=None, raw_ref=None, is_sidechain=0):
        self.seen += 1
        try:
            ts = norm_ts(ts)
        except (ValueError, TypeError):
            self.dropped += 1
            return
        try:
            summary, h1 = _redact.redact((summary or "")[:512])
            detail, h2 = _redact.redact((detail or "")[:MAX_DETAIL])
            redacted = 1 if (h1 + h2) else 0
        except Exception as e:  # fail closed: never write unredacted content
            self.dropped += 1
            print(f"  [redactor] dropped event ({source}/{kind}): {type(e).__name__}", file=sys.stderr)
            return
        eid = hashlib.sha256(
            f"{source}|{session_id}|{ts}|{kind}|{raw_ref}|{summary[:200]}".encode()).hexdigest()
        if self.dry_run:
            self.inserted += 1
            return
        cur = self.con.execute(
            """INSERT OR IGNORE INTO events
               (id, ts, source, session_id, venture, project, kind, actor, summary, detail,
                artifacts, raw_ref, is_sidechain, redacted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, ts, source, session_id, venture, project, kind, actor, summary, detail,
             json.dumps(artifacts) if artifacts else None, raw_ref, is_sidechain, redacted))
        self.inserted += cur.rowcount


def file_changed(con, path: str, mtime: float, size: int):
    """Return (changed, lines_already_ingested). Reparse fully if the file shrank."""
    row = con.execute("SELECT mtime, size, lines FROM file_state WHERE path=?", (path,)).fetchone()
    if row is None:
        return True, 0
    if row["mtime"] == mtime and row["size"] == size:
        return False, row["lines"]
    if size < row["size"]:
        return True, 0  # truncated/rewritten: reparse
    return True, row["lines"]


def record_file(con, path: str, mtime: float, size: int, lines: int):
    con.execute(
        """INSERT INTO file_state(path, mtime, size, lines) VALUES (?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size, lines=excluded.lines""",
        (path, mtime, size, lines))
