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

from . import config

FOLLOWUP_DAYS = 3  # default cadence: every touch schedules a day-3 follow-up

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
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  added TEXT NOT NULL, name TEXT NOT NULL, phone TEXT, service TEXT, note TEXT,
  status TEXT DEFAULT 'open', last_touch TEXT, quoted REAL, collected REAL
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
    os.chmod(p.parent, stat.S_IRWXU)  # 700
    if not p.exists():
        os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))  # create at 600
    con = sqlite3.connect(p)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 600, same posture as activity.db
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now().astimezone().date()


# ---------------------------------------------------------------- writes

def log_touch(con, venture: str, target: str, kind: str, note: str = "",
              followup_days: int = FOLLOWUP_DAYS) -> int:
    """Log an outreach touch and schedule its follow-up. Returns followup id (0 if none)."""
    con.execute("INSERT INTO touches (ts, venture, target, kind, note) VALUES (?,?,?,?,?)",
                (_now(), venture, target, kind, note))
    fid = 0
    if followup_days > 0:
        due = (_today() + timedelta(days=followup_days)).isoformat()
        cur = con.execute(
            """INSERT INTO followups (due, venture, target, note, created_ts)
               VALUES (?,?,?,?,?)""",
            (due, venture, target, f"day-{followup_days} after {kind}", _now()))
        fid = cur.lastrowid
    con.execute("UPDATE leads SET last_touch=?, status='working' "
                "WHERE name=? AND status IN ('open','working')", (_now(), target))
    con.commit()
    return fid


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
                (_now(), amount, venture, what))
    con.commit()


def add_lead(con, name: str, phone: str = "", service: str = "", note: str = "") -> int:
    cur = con.execute(
        "INSERT INTO leads (added, name, phone, service, note) VALUES (?,?,?,?,?)",
        (_now(), name, phone, service, note))
    con.commit()
    return cur.lastrowid


def touch_lead(con, lead_id: int, kind: str, amount=None, note: str = "") -> None:
    row = con.execute("SELECT name FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        return
    if kind == "quoted" and amount:
        con.execute("UPDATE leads SET quoted=?, last_touch=?, status='working' WHERE id=?",
                    (amount, _now(), lead_id))
    elif kind == "collected" and amount:
        con.execute("UPDATE leads SET collected=COALESCE(collected,0)+?, last_touch=?, "
                    "status='won' WHERE id=?", (amount, _now(), lead_id))
        log_cash(con, amount, "leads", f"lead: {row['name']}")
    elif kind == "lost":
        con.execute("UPDATE leads SET status='lost', last_touch=? WHERE id=?", (_now(), lead_id))
    else:  # called / texted / emailed …
        con.execute("UPDATE leads SET last_touch=?, status='working' WHERE id=?",
                    (_now(), lead_id))
        con.execute("INSERT INTO touches (ts, venture, target, kind, note) VALUES (?,?,?,?,?)",
                    (_now(), "leads", row["name"], kind, note))
    con.commit()


def capture(con, text: str) -> None:
    """Quick capture from the console header — a thought parked in the inbox, filed later."""
    con.execute("INSERT INTO captures (ts, text) VALUES (?,?)", (_now(), text.strip()[:500]))
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


def leads_open(con) -> list:
    return con.execute(
        """SELECT * FROM leads WHERE status IN ('open','working')
           ORDER BY COALESCE(last_touch, added)""").fetchall()


def touches_recent(con, limit: int = 25) -> list:
    return con.execute("SELECT * FROM touches ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def today_tape(con) -> dict:
    """Today's operator tape: touches by kind + cash collected today (local day)."""
    start = _today().isoformat()
    tape = {"touches": 0, "calls": 0, "sends": 0, "cash": 0.0}
    for r in con.execute("SELECT kind, COUNT(*) c FROM touches WHERE ts >= ? GROUP BY kind",
                         (start,)):
        tape["touches"] += r["c"]
        if r["kind"] in ("call", "called"):
            tape["calls"] += r["c"]
        elif r["kind"] in ("email", "send", "sent", "text", "texted", "dm"):
            tape["sends"] += r["c"]
    row = con.execute("SELECT COALESCE(SUM(amount),0) s FROM cash WHERE ts >= ?",
                      (start,)).fetchone()
    tape["cash"] = row["s"]
    return tape
