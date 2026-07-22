"""Operational write layer for `opsroom serve` — the ONLY module that writes state.
Separate ops.db (same dir, 600 perms) so `opsroom purge`/re-sync can never eat your
cash ledger or touch log. Sources (notes, trackers) stay read-only; the one optional
markdown write is an append-only line into the daily note, through the redactor.

Tables:
  touches    — every outreach action you log; each schedules a follow-up (+3d default)
  followups  — the cadence engine: due dates drive the top of the NOW queue
  cash       — append-only collected-cash ledger; the goal bar reads this
  leads      — leads as rows (quick-add, touch, quote, collect)
  kv         — misc (queue-item dismissals, snoozes)
"""
import os
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, redact

FOLLOWUP_DAYS = 3  # default cadence: every touch schedules a day-3 follow-up

# The pipeline vocabulary. `stage` is the operator-facing axis; `status` stays as
# the legacy 4-value column, always mirrored via _STAGE_TO_STATUS so every
# pre-0.11 query and verb keeps working against the same rows.
STAGES = ("new", "contacted", "talking", "quoted", "won", "lost")
SOURCES = ("lsa", "website", "referral", "manual", "import")
_STAGE_TO_STATUS = {"new": "open", "contacted": "working", "talking": "working",
                    "quoted": "working", "won": "won", "lost": "lost"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS touches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, venture TEXT, target TEXT NOT NULL, kind TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS followups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  due TEXT NOT NULL, venture TEXT, target TEXT NOT NULL, note TEXT,
  status TEXT DEFAULT 'open', created_ts TEXT, done_ts TEXT
);
CREATE TABLE IF NOT EXISTS cash (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, amount REAL NOT NULL, venture TEXT, what TEXT
);
CREATE TABLE IF NOT EXISTS spend (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, amount REAL NOT NULL, venture TEXT, what TEXT
);
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  added TEXT NOT NULL, name TEXT NOT NULL, phone TEXT, service TEXT, note TEXT,
  status TEXT DEFAULT 'open', last_touch TEXT, quoted REAL, collected REAL,
  venture TEXT
);
CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, text TEXT NOT NULL, status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, due);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status, added);
"""


def db_path() -> Path:
    return config.data_dir() / "ops.db"


def connect() -> sqlite3.Connection:
    from . import db as _db
    _db._assert_safe_location()  # never let the cash/leads ledger live in a sync root
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _db._chmod(p.parent, stat.S_IRWXU)  # 700
    if not p.exists():
        os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))  # create at 600
    con = sqlite3.connect(p)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")  # wait out a concurrent writer, don't 500
    con.executescript(SCHEMA)
    _migrate_leads(con)
    con.row_factory = sqlite3.Row
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            _db._chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 600, same posture as activity.db
    return con


def _migrate_leads(con) -> None:
    """Additive lead migrations. Every column is a nullable TEXT ALTER guarded by
    PRAGMA table_info, so any pre-0.11 (or pre-0.6.1) ledger opens cleanly. The
    stage backfill runs once, kv-guarded, and only derives from data already in
    the row — it never invents facts."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(leads)")}
    for col in ("venture", "stage", "source", "intent", "next_due", "first_seen", "link"):
        if col not in cols:
            con.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage, next_due, added)")
    done = con.execute("SELECT v FROM kv WHERE k='leads_v11_backfill'").fetchone()
    if done and done[0]:
        return
    con.execute("""UPDATE leads SET stage = CASE
        WHEN status='won'  THEN 'won'
        WHEN status='lost' THEN 'lost'
        WHEN quoted IS NOT NULL THEN 'quoted'
        WHEN note LIKE '%reply%' OR EXISTS (
             SELECT 1 FROM touches t
             WHERE lower(t.target)=lower(leads.name) AND t.kind='replied')
             THEN 'talking'
        WHEN last_touch IS NOT NULL OR status='working' THEN 'contacted'
        ELSE 'new' END
        WHERE stage IS NULL OR stage=''""")
    con.execute("""UPDATE leads SET source = CASE
        WHEN note LIKE '%lead date %' OR name LIKE 'LSA%' THEN 'import'
        ELSE 'manual' END
        WHERE source IS NULL OR source=''""")
    con.execute("""UPDATE leads SET intent = service
        WHERE (intent IS NULL OR intent='') AND service IS NOT NULL AND service != ''""")
    # first_seen: best-effort pull of the 10-char date after 'lead date ' in the
    # flattened note (pre-0.11 importer), else the row's own added date.
    con.execute("""UPDATE leads SET first_seen = CASE
        WHEN instr(note, 'lead date ') > 0
             THEN substr(note, instr(note, 'lead date ') + 10, 10)
        ELSE substr(added, 1, 10) END
        WHERE first_seen IS NULL OR first_seen=''""")
    con.execute("INSERT INTO kv (k, v) VALUES ('leads_v11_backfill', '1') "
                "ON CONFLICT(k) DO UPDATE SET v='1'")
    con.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now().astimezone().date()


# ---------------------------------------------------------------- writes

def log_touch(con, venture: str, target: str, kind: str, note: str = "",
              followup_days: int = FOLLOWUP_DAYS) -> int:
    """Log an outreach touch and schedule its follow-up. Returns followup id (0 if none)."""
    con.execute("INSERT INTO touches (ts, venture, target, kind, note) VALUES (?,?,?,?,?)",
                (_now(), venture, target, kind, redact.scrub(note)))
    fid = 0
    if followup_days > 0:
        due = (_today() + timedelta(days=followup_days)).isoformat()
        cur = con.execute(
            """INSERT INTO followups (due, venture, target, note, created_ts)
               VALUES (?,?,?,?,?)""",
            (due, venture, target, f"day-{followup_days} after {kind}", _now()))
        fid = cur.lastrowid
    con.execute("UPDATE leads SET last_touch=?, status='working', "
                "stage=CASE WHEN ?='replied' AND stage NOT IN ('quoted') THEN 'talking' "
                "WHEN stage='new' OR stage IS NULL OR stage='' THEN 'contacted' "
                "ELSE stage END "
                "WHERE lower(name)=lower(?) AND status IN ('open','working')",
                (_now(), kind, target))
    con.commit()
    return fid


def followup_add(con, target: str, due: str, venture: str = "", note: str = "") -> int:
    """Schedule a follow-up directly (used by applied agent proposals — same row
    shape log_touch creates, without logging a touch that never happened)."""
    cur = con.execute(
        "INSERT INTO followups (due, venture, target, note, created_ts) VALUES (?,?,?,?,?)",
        (due, venture, target, redact.scrub(note), _now()))
    con.commit()
    return cur.lastrowid


def followup_set(con, fid: int, op: str) -> None:
    if op == "done":
        con.execute("UPDATE followups SET status='done', done_ts=? WHERE id=?", (_now(), fid))
    elif op == "snooze":
        con.execute("UPDATE followups SET due=? WHERE id=? AND status='open'",
                    ((_today() + timedelta(days=1)).isoformat(), fid))
    elif op == "drop":
        con.execute("UPDATE followups SET status='dropped', done_ts=? WHERE id=?", (_now(), fid))
    con.commit()


def log_cash(con, amount: float, venture: str, what: str = "") -> None:
    """Append-only. Cash counts when COLLECTED — this ledger is the source of truth."""
    con.execute("INSERT INTO cash (ts, amount, venture, what) VALUES (?,?,?,?)",
                (_now(), amount, venture, redact.scrub(what)))
    con.commit()


def log_spend(con, amount: float, venture: str, what: str = "") -> None:
    """Append-only money-out ledger — the other half of the P&L."""
    con.execute("INSERT INTO spend (ts, amount, venture, what) VALUES (?,?,?,?)",
                (_now(), amount, venture, redact.scrub(what)))
    con.commit()


def add_lead(con, name: str, phone: str = "", service: str = "", note: str = "",
             venture: str = "", stage: str = "new", source: str = "manual",
             intent: str = "", first_seen: str = "", link: str = "",
             next_due: str = "") -> int:
    if stage not in STAGES:
        stage = "new"  # junk from a caller never invents a stage
    if source not in SOURCES:
        source = "manual"
    cur = con.execute(
        """INSERT INTO leads (added, name, phone, service, note, venture,
                              stage, source, intent, first_seen, link, next_due, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (_now(), name, phone, service, redact.scrub(note), venture,
         # first_seen is an operator-facing calendar fact: LOCAL date, never the
         # UTC prefix (11pm adds used to read "first seen tomorrow")
         stage, source, intent or service, first_seen or _today().isoformat(),
         link, next_due, _STAGE_TO_STATUS[stage]))
    con.commit()
    return cur.lastrowid


def lead_set_stage(con, lead_id: int, stage: str, note: str = "",
                   next_due: str = "") -> bool:
    """Move a lead to a pipeline stage. Whitelisted; mirrors the legacy status
    column so every pre-0.11 query keeps seeing the same truth."""
    if stage not in STAGES:
        return False
    row = con.execute("SELECT id FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        return False
    con.execute("UPDATE leads SET stage=?, status=?, last_touch=?, "
                "next_due=CASE WHEN ?='' THEN next_due ELSE ? END WHERE id=?",
                (stage, _STAGE_TO_STATUS[stage], _now(), next_due, next_due, lead_id))
    if note:
        con.execute("INSERT INTO touches (ts, venture, target, kind, note) "
                    "SELECT ?, venture, name, 'stage', ? FROM leads WHERE id=?",
                    (_now(), redact.scrub(note), lead_id))
    con.commit()
    return True


def touch_lead(con, lead_id: int, kind: str, amount=None, note: str = "") -> None:
    row = con.execute("SELECT name, venture FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        return
    # attribute a lead's cash to its own venture (falls back to 'leads' if unset) so
    # per-venture ROI stays honest instead of piling every collection into one bucket.
    venture = row["venture"] or "leads"
    if kind == "quoted" and amount:
        con.execute("UPDATE leads SET quoted=?, last_touch=?, status='working', "
                    "stage=CASE WHEN stage IN ('won','lost') THEN stage ELSE 'quoted' END "
                    "WHERE id=?", (amount, _now(), lead_id))
    elif kind == "collected" and amount:
        con.execute("UPDATE leads SET collected=COALESCE(collected,0)+?, last_touch=?, "
                    "status='won', stage='won' WHERE id=?", (amount, _now(), lead_id))
        log_cash(con, amount, venture, f"lead: {row['name']}")
    elif kind == "lost":
        con.execute("UPDATE leads SET status='lost', stage='lost', last_touch=? WHERE id=?",
                    (_now(), lead_id))
    else:  # called / texted / emailed … — a contact touch advances 'new' only,
        # never demotes a lead already talking/quoted.
        con.execute("UPDATE leads SET last_touch=?, status='working', "
                    "stage=CASE WHEN stage='new' OR stage IS NULL OR stage='' "
                    "THEN 'contacted' ELSE stage END WHERE id=?", (_now(), lead_id))
        con.execute("INSERT INTO touches (ts, venture, target, kind, note) VALUES (?,?,?,?,?)",
                    (_now(), venture, row["name"], kind, redact.scrub(note)))
    con.commit()


def capture(con, text: str) -> None:
    """Quick capture from the console header — a thought parked in the inbox, filed later."""
    con.execute("INSERT INTO captures (ts, text) VALUES (?,?)",
                (_now(), redact.scrub(text.strip()[:500])))
    con.commit()


def captures_open(con, limit: int = 12) -> list:
    return con.execute(
        "SELECT * FROM captures WHERE status='open' ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def capture_set(con, cid: int, op: str) -> None:
    con.execute("UPDATE captures SET status=? WHERE id=?",
                ("filed" if op == "file" else "done", cid))
    con.commit()


def kv_set(con, k: str, v: str) -> None:
    con.execute("INSERT INTO kv (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, v))
    con.commit()


def kv_get(con, k: str, default: str = "") -> str:
    row = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return row["v"] if row else default


# ---------------------------------------------------------------- reads

def followups_due(con, horizon_days: int = 0) -> list:
    lim = (_today() + timedelta(days=horizon_days)).isoformat()
    return con.execute(
        """SELECT * FROM followups WHERE status='open' AND due <= ? ORDER BY due""",
        (lim,)).fetchall()


def followups_upcoming(con, limit: int = 15) -> list:
    return con.execute(
        """SELECT * FROM followups WHERE status='open' AND due > ?
           ORDER BY due LIMIT ?""", (_today().isoformat(), limit)).fetchall()


def cash_total(con) -> float:
    return con.execute("SELECT COALESCE(SUM(amount),0) s FROM cash").fetchone()["s"]


def cash_entries(con, limit: int = 20) -> list:
    return con.execute("SELECT * FROM cash ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def spend_total(con) -> float:
    return con.execute("SELECT COALESCE(SUM(amount),0) s FROM spend").fetchone()["s"]


def spend_entries(con, limit: int = 20) -> list:
    return con.execute("SELECT * FROM spend ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def roi_rows(con) -> list:
    """Per-venture P&L: money in vs money out vs net, from the two append-only
    ledgers. Attribution is honest and simple — whatever venture you logged."""
    cash_by = {r["v"]: r["s"] for r in con.execute(
        "SELECT COALESCE(venture,'') v, SUM(amount) s FROM cash GROUP BY 1")}
    spend_by = {r["v"]: r["s"] for r in con.execute(
        "SELECT COALESCE(venture,'') v, SUM(amount) s FROM spend GROUP BY 1")}
    rows = []
    for v in sorted(set(cash_by) | set(spend_by)):
        c, s = int(cash_by.get(v, 0)), int(spend_by.get(v, 0))
        rows.append({"venture": v or "unattributed", "collected": c, "spend": s,
                     "net": c - s})
    return rows


def leads_open(con) -> list:
    # newest first: speed-to-lead wins, and it matches the DO NOW row's story
    return con.execute(
        """SELECT * FROM leads WHERE status IN ('open','working')
           ORDER BY COALESCE(last_touch, added) DESC""").fetchall()


_LEAD_SORTS = {  # whitelist: sort key -> ORDER BY (never interpolate user input)
    "newest": "COALESCE(last_touch, added) DESC",
    "aged": "COALESCE(last_touch, added) ASC",
    "quoted": "COALESCE(quoted, 0) DESC, COALESCE(last_touch, added) DESC",
}


def leads_all(con, q: str = "", status: str = "", sort: str = "newest",
              stage: str = "") -> list:
    """The full-workspace query: every lead, filterable and sortable. Same
    %_-escaped LIKE discipline as search_ops — query text is always literal."""
    where, params = [], []
    if q:
        pat = "%" + q.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_") + "%"
        where.append(r"(name LIKE ? ESCAPE '\' OR phone LIKE ? ESCAPE '\' "
                     r"OR service LIKE ? ESCAPE '\' OR note LIKE ? ESCAPE '\')")
        params += [pat] * 4
    if stage in STAGES:  # whitelist — junk stage param means no stage filter
        where.append("stage = ?")
        params.append(stage)
    if status == "open":
        where.append("status IN ('open','working')")
    elif status == "quoted":
        where.append("quoted IS NOT NULL AND status IN ('open','working')")
    elif status in ("won", "lost"):
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM leads"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + _LEAD_SORTS.get(sort, _LEAD_SORTS["newest"])
    return con.execute(sql, params).fetchall()


def leads_by_stage(con, q: str = "") -> dict:
    """One query, bucketed by stage for the pipeline board. Within a stage,
    next_due first (overdue work floats), then newest."""
    rows = leads_all(con, q=q, sort="newest")
    buckets = {s: [] for s in STAGES}
    for r in rows:
        buckets.get(r["stage"] or "new", buckets["new"]).append(r)
    today = _today().isoformat()
    for s in buckets:
        buckets[s].sort(key=lambda r: (
            0 if (r["next_due"] and r["next_due"] <= today) else 1,
            r["next_due"] or "9999",
            r["added"] or ""), reverse=False)
    return buckets


def leads_stage_counts(con) -> dict:
    out = {s: 0 for s in STAGES}
    out["all"] = 0
    for r in con.execute("SELECT COALESCE(NULLIF(stage,''),'new') s, COUNT(*) c "
                         "FROM leads GROUP BY 1"):
        if r["s"] in out:
            out[r["s"]] += r["c"]
        out["all"] += r["c"]
    return out


QUOTED_COLD_DAYS = 3  # a quote untouched this long is cooling; day 7 is dead


def _local_date(val: str) -> str:
    """A stored value's LOCAL calendar date. Rows store UTC iso timestamps, so
    a lead added at 11pm local is 'tomorrow' in UTC — comparing raw prefixes
    would hide it from every today lane. Bare dates pass through."""
    if not val:
        return ""
    if len(val) > 10:
        try:
            return datetime.fromisoformat(val).astimezone().date().isoformat()
        except ValueError:
            pass
    return val[:10]


def leads_lanes(con, cap: int = 5) -> dict:
    """The pipeline's HOT lanes for the NOW board — the four states that demand
    action today, straight from the ledger. A lead lands in its hottest lane
    only (replied > due > new > cold), so nothing double-counts:
      replied — stage 'talking': a live two-way thread, answer it today
      due     — next_due today or overdue
      new     — first seen today (speed-to-lead)
      cold    — quoted but untouched for QUOTED_COLD_DAYS+
    Each lane: {"rows": [...cap], "n": total}. Computed in Python over the open
    set so UTC-stored timestamps compare on LOCAL dates."""
    rows = leads_open(con)  # already newest-touch first
    today = _today().isoformat()
    cold_edge = (_today() - timedelta(days=QUOTED_COLD_DAYS)).isoformat()
    lanes, seen = {}, set()

    def take(key, hits, sort_key=None):
        hits = [r for r in hits if r["id"] not in seen]
        seen.update(r["id"] for r in hits)
        if sort_key:
            hits.sort(key=sort_key)
        lanes[key] = {"rows": hits[:cap], "n": len(hits)}

    take("replied", [r for r in rows if r["stage"] == "talking"])
    take("due", [r for r in rows
                 if r["next_due"] and _local_date(r["next_due"]) <= today],
         sort_key=lambda r: r["next_due"])
    take("new", [r for r in rows
                 if _local_date(r["first_seen"] or r["added"]) == today])
    take("cold", [r for r in rows if r["stage"] == "quoted"
                  and _local_date(r["last_touch"] or r["added"]) <= cold_edge],
         sort_key=lambda r: -(r["quoted"] or 0))
    return lanes


def lead_get(con, lead_id: int):
    return con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()


def lead_touches(con, name: str, limit: int = 8) -> list:
    """A lead's recent touch history (by target name) — feeds the dispatch brief."""
    return con.execute(
        "SELECT * FROM touches WHERE lower(target)=lower(?) ORDER BY ts DESC LIMIT ?",
        (name, limit)).fetchall()


def leads_counts(con) -> dict:
    """Counts for the workspace filter chips."""
    out = {"all": 0, "open": 0, "quoted": 0, "won": 0, "lost": 0}
    for r in con.execute("SELECT status, quoted, COUNT(*) c FROM leads GROUP BY 1, quoted IS NULL"):
        out["all"] += r["c"]
        if r["status"] in ("open", "working"):
            out["open"] += r["c"]
            if r["quoted"] is not None:
                out["quoted"] += r["c"]
        elif r["status"] in ("won", "lost"):
            out[r["status"]] += r["c"]
    return out


def touches_recent(con, limit: int = 25) -> list:
    return con.execute("SELECT * FROM touches ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def search_ops(con, q: str, limit: int = 15) -> dict:
    """LIKE-match the operator ledgers (leads, touches, inbox captures) for the
    console search. Param-bound with %_ escaped, so query text is always literal."""
    pat = "%" + q.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_") + "%"
    leads = con.execute(
        r"""SELECT * FROM leads WHERE name LIKE ? ESCAPE '\' OR phone LIKE ? ESCAPE '\'
            OR service LIKE ? ESCAPE '\' OR note LIKE ? ESCAPE '\'
            ORDER BY added DESC LIMIT ?""", (pat, pat, pat, pat, limit)).fetchall()
    touches = con.execute(
        r"""SELECT * FROM touches WHERE target LIKE ? ESCAPE '\' OR note LIKE ? ESCAPE '\'
            OR venture LIKE ? ESCAPE '\' ORDER BY ts DESC LIMIT ?""",
        (pat, pat, pat, limit)).fetchall()
    captures = con.execute(
        r"""SELECT * FROM captures WHERE text LIKE ? ESCAPE '\'
            ORDER BY ts DESC LIMIT ?""", (pat, limit)).fetchall()
    return {"leads": leads, "touches": touches, "captures": captures}


def _local_day_utc_bounds():
    """UTC-isoformat [start, end) spanning the current LOCAL day, so string
    comparisons against UTC timestamps don't smear evening entries across two days."""
    now = datetime.now().astimezone()
    start_local = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc).isoformat(),
            end_local.astimezone(timezone.utc).isoformat())


def today_tape(con) -> dict:
    """Today's operator tape: touches by kind + cash collected today (local day)."""
    start, end = _local_day_utc_bounds()
    tape = {"touches": 0, "calls": 0, "sends": 0, "cash": 0.0}
    for r in con.execute("SELECT kind, COUNT(*) c FROM touches WHERE ts >= ? AND ts < ? "
                         "GROUP BY kind", (start, end)):
        tape["touches"] += r["c"]
        if r["kind"] in ("call", "called"):
            tape["calls"] += r["c"]
        elif r["kind"] in ("email", "send", "sent", "text", "texted", "dm"):
            tape["sends"] += r["c"]
    row = con.execute("SELECT COALESCE(SUM(amount),0) s FROM cash WHERE ts >= ? AND ts < ?",
                      (start, end)).fetchone()
    tape["cash"] = row["s"]
    return tape
