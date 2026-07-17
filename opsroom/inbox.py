"""Lead + reply ingest — JSON drop files are the contract, any source can write one.

A reply from someone you pitched is the hottest event on the board, and a fresh
lead is paid-for money; until now both were invisible unless you happened to check
the right inbox. Have anything produce a small JSON file — an AI agent session
reading your mail, a CRM export script, a form webhook you pipe to disk — and
`opsroom leads-import` / `opsroom replies-import` (or the live console, which
re-imports on file change) merge it into the operator ledger. opsroom itself never
touches the network; the drop file is the boundary.

Drop shapes (extra keys are ignored):

  leads.json    {"leads": [{"name": "Kestrel Detailing", "phone": "(555) 010-0199",
                            "service": "full detail", "note": "asked about pricing",
                            "date": "2026-07-16", "link": "https://…"}],
                 "missed_calls": 2}
  replies.json  {"replies": [{"msg_id": "abc123", "date": "2026-07-16",
                              "venture": "meridian", "target": "Kestrel Detailing",
                              "from_name": "Sam", "from_email": "sam@kestrel.example",
                              "subject": "Re: ops sprint", "snippet": "sounds good…",
                              "link": "https://…"}]}

Rails:
  - Leads dedup by phone digits — re-importing the same drop adds nothing.
  - Replies dedup by a stable id (msg_id, else email|date|subject). A genuinely NEW
    reply also logs a `replied` touch and schedules the call for TODAY, clawing it
    to the top of NOW. The touch fires ONLY when the insert actually lands
    (rowcount==1), so re-ingesting can never double-count a reply on the tape.
  - "missed_calls" is a count you can surface when a source can see that calls
    happened but not who called (latest drop wins, never cumulative).
  - Nothing here fabricates contact data; rows without a phone (leads) or without
    an email/msg_id (replies) are skipped as unverifiable.
"""
import hashlib
import json
import re
from pathlib import Path

from . import config, ops

SCHEMA = """
CREATE TABLE IF NOT EXISTS replies (
  id          TEXT PRIMARY KEY,
  ingested_ts TEXT NOT NULL,
  reply_date  TEXT,
  venture     TEXT,
  target      TEXT,
  from_name   TEXT,
  from_email  TEXT,
  subject     TEXT,
  snippet     TEXT,
  link        TEXT,
  status      TEXT DEFAULT 'open'
);
"""


def leads_drop_path() -> Path:
    p = config.load()["paths"].get("leads_drop") or ""
    return Path(p).expanduser() if p else config.data_dir() / "inbox" / "leads.json"


def replies_drop_path() -> Path:
    p = config.load()["paths"].get("replies_drop") or ""
    return Path(p).expanduser() if p else config.data_dir() / "inbox" / "replies.json"


def _ensure(con) -> None:
    con.executescript(SCHEMA)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")[-10:]


# ---------------------------------------------------------------- leads

def merge_leads(ocon, parsed: dict) -> dict:
    """Insert leads deduped by phone digits. Returns {added, skipped, missed_calls}."""
    have = {_digits(r["phone"]) for r in ocon.execute("SELECT phone FROM leads").fetchall()
            if r["phone"]}
    added = skipped = 0
    for ld in parsed.get("leads", []):
        phone = (ld.get("phone") or "").strip()[:30]
        if not _digits(phone):
            continue  # nothing verifiable to dial — never fabricate a row
        if _digits(phone) in have:
            skipped += 1
            continue
        note_bits = [ld.get("note") or ""]
        if ld.get("date"):
            note_bits.append(f"lead date {str(ld['date'])[:10]}")
        if ld.get("link"):
            note_bits.append(f"reply: {str(ld['link'])[:200]}")
        name = (ld.get("name") or "").strip()[:80] or \
            f"{(ld.get('service') or 'imported').strip()[:40]} lead"
        ops.add_lead(ocon, name, phone, (ld.get("service") or "")[:80],
                     " · ".join(b for b in note_bits if b)[:300])
        have.add(_digits(phone))
        added += 1
    if "missed_calls" in parsed:
        ops.kv_set(ocon, "missed_calls", str(int(parsed.get("missed_calls") or 0)))
    return {"added": added, "skipped": skipped,
            "missed_calls": int(parsed.get("missed_calls") or 0)}


# ---------------------------------------------------------------- replies

def _rid(r: dict) -> str:
    """Stable id. Prefer the source message id; fall back to email|date|subject —
    snippet is excluded so a re-pull with a longer snippet is still the same reply."""
    key = r.get("msg_id") or \
        f"{_norm(r.get('from_email'))}|{r.get('date', '')}|{_norm(r.get('subject'))}"
    return "r" + hashlib.sha1(key.encode()).hexdigest()[:14]


def merge_replies(ocon, parsed: dict) -> dict:
    """Insert replies deduped by stable id. A NEW row also logs a `replied` touch
    and schedules the call for TODAY. Returns {added, skipped}."""
    _ensure(ocon)
    added = skipped = 0
    for r in parsed.get("replies", []):
        if not (r.get("from_email") or r.get("msg_id")):
            continue  # nothing verifiable to key on
        rid = _rid(r)
        cur = ocon.execute(
            """INSERT OR IGNORE INTO replies(id, ingested_ts, reply_date, venture, target,
                 from_name, from_email, subject, snippet, link)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rid, ops._now(), (r.get("date") or "")[:10], (r.get("venture") or "")[:40],
             (r.get("target") or "")[:120], (r.get("from_name") or "")[:120],
             (r.get("from_email") or "")[:200], (r.get("subject") or "")[:200],
             (r.get("snippet") or "")[:300], (r.get("link") or "")[:400]))
        if cur.rowcount == 1:
            added += 1
            target = (r.get("target") or r.get("from_name") or r.get("from_email"))[:120]
            venture = (r.get("venture") or "unknown")[:40]
            ops.log_touch(ocon, venture, target, "replied",
                          note=f"auto: reply — {(r.get('subject') or '')[:80]}",
                          followup_days=0)
            ocon.execute(  # a live reply is called TODAY, not on the day-3 cadence
                """INSERT INTO followups (due, venture, target, note, created_ts)
                   VALUES (?,?,?,?,?)""",
                (ops._today().isoformat(), venture, target, "they replied — call now",
                 ops._now()))
        else:
            skipped += 1
    ocon.commit()
    return {"added": added, "skipped": skipped}


def open_replies(con, limit: int = 20):
    _ensure(con)
    return con.execute(
        """SELECT * FROM replies WHERE status='open'
           ORDER BY COALESCE(reply_date,'') DESC, ingested_ts DESC LIMIT ?""",
        (limit,)).fetchall()


def reply_set(con, rid: str, op: str) -> None:
    _ensure(con)
    status = {"handled": "handled", "dismiss": "dismissed"}.get(op)
    if status:
        con.execute("UPDATE replies SET status=? WHERE id=?", (status, rid))
        con.commit()


# ---------------------------------------------------------------- drop files

def _import(ocon, path: Path, merge) -> dict:
    try:
        parsed = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return {"error": str(e), "added": 0, "skipped": 0}
    if not isinstance(parsed, dict):
        return {"error": "drop must be a JSON object", "added": 0, "skipped": 0}
    return merge(ocon, parsed)


def import_leads(ocon, path: Path = None) -> dict:
    return _import(ocon, path or leads_drop_path(), merge_leads)


def import_replies(ocon, path: Path = None) -> dict:
    return _import(ocon, path or replies_drop_path(), merge_replies)


_MTIMES = {}


def watch_tick(ocon) -> bool:
    """One poll: re-import either drop file when its mtime changes. Used by the
    serve sync loop. Returns True when anything was ingested."""
    changed = False
    for path, imp in ((leads_drop_path(), import_leads),
                      (replies_drop_path(), import_replies)):
        try:
            mt = path.stat().st_mtime
        except OSError:
            continue
        if _MTIMES.get(str(path)) != mt:
            _MTIMES[str(path)] = mt
            r = imp(ocon, path)
            changed = changed or bool(r.get("added"))
    return changed
