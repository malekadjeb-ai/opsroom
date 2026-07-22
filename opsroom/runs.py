"""Runs ledger — every agent dispatch ends in a recorded fact. v0.11 discarded
the reaper's exit code, so a run that died instantly left a 0-byte log and no
trace anywhere; after a console restart it even read as "done". This table makes
a dead run impossible to miss and a finished run fully accounted: pid, exit
code, duration, output size, scrubbed tail.

Lives in ops.db (the un-rebuildable operator ledger, beside proposals/counsel,
keyed by the same dispatch ts). Lazy schema like proposals.py — any pre-0.12
ledger grows the table on first touch.

Outcomes:
  running   — launched by a console that is (or was) alive
  done      — exit 0 with output
  failed    — nonzero exit with output
  dead      — 0 bytes of output (the silent-night signature) — ALERTS
  killed    — watchdog or operator cancel escalated to SIGKILL... (watchdog) — ALERTS
  cancelled — operator pressed cancel
  orphaned  — console died mid-run; exit unknown, output exists
  unknown   — backfilled from disk with no pid to consult (pre-0.12 runs,
              demo seeds). NEVER alerts — we can't know it failed.
"""
import os
import re
import signal
from datetime import datetime, timedelta, timezone

from . import config, redact

TS_RE = re.compile(r"^\d{8}-\d{6}-\d+$")  # dispatch ids are timestamps, never paths
TAIL_BYTES = 1000
ALERT_OUTCOMES = ("dead", "failed", "killed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  ts           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL DEFAULT 'do',
  task         TEXT NOT NULL DEFAULT '',
  venture      TEXT NOT NULL DEFAULT '',
  pid          INTEGER,
  started      TEXT NOT NULL,
  ended        TEXT,
  exit_code    INTEGER,
  duration_s   REAL,
  stdout_bytes INTEGER,
  stderr_tail  TEXT NOT NULL DEFAULT '',
  outcome      TEXT NOT NULL DEFAULT 'running',
  attempt      INTEGER NOT NULL DEFAULT 1,
  retry_of     TEXT,
  acked        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started DESC);
"""


def _ensure(con) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_launch(ocon, ts: str, kind: str = "do", task: str = "",
                  venture: str = "", pid: int = None,
                  attempt: int = 1, retry_of: str = None) -> None:
    if not TS_RE.match(ts or ""):
        return
    _ensure(ocon)
    ocon.execute(
        "INSERT OR IGNORE INTO runs (ts, kind, task, venture, pid, started,"
        " outcome, attempt, retry_of) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, kind, redact.scrub((task or ""))[:300], venture or "", pid,
         _now(), "running", attempt, retry_of))
    ocon.commit()


def record_exit(ocon, ts: str, exit_code: int, duration_s: float,
                stdout_bytes: int, stderr_tail: str, outcome: str) -> None:
    """Finalize a run. Never downgrades an operator/watchdog verdict: a row
    already marked cancelled or killed keeps that outcome (the reaper always
    fires after a kill, and 'exit -15' must not overwrite 'cancelled')."""
    if not TS_RE.match(ts or ""):
        return
    _ensure(ocon)
    tail = redact.scrub(stderr_tail or "")[:TAIL_BYTES]
    cur = ocon.execute(
        "UPDATE runs SET ended=?, exit_code=?, duration_s=?, stdout_bytes=?,"
        " stderr_tail=?, outcome=? WHERE ts=? AND outcome NOT IN"
        " ('cancelled','killed')",
        (_now(), exit_code, duration_s, stdout_bytes, tail, outcome, ts))
    if cur.rowcount == 0 and not get(ocon, ts):
        # record_launch never landed (ledger hiccup at launch) — the exit fact
        # still must not be lost
        ocon.execute(
            "INSERT OR IGNORE INTO runs (ts, started, ended, exit_code,"
            " duration_s, stdout_bytes, stderr_tail, outcome)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ts, _now(), _now(), exit_code, duration_s, stdout_bytes, tail, outcome))
    else:
        # a finalized cancelled/killed row still deserves its exit facts
        ocon.execute(
            "UPDATE runs SET ended=COALESCE(ended,?), exit_code=COALESCE(exit_code,?),"
            " duration_s=COALESCE(duration_s,?), stdout_bytes=?, stderr_tail=?"
            " WHERE ts=?",
            (_now(), exit_code, duration_s, stdout_bytes, tail, ts))
    ocon.commit()


def get(ocon, ts: str):
    if not TS_RE.match(ts or ""):
        return None
    _ensure(ocon)
    return ocon.execute("SELECT * FROM runs WHERE ts=?", (ts,)).fetchone()


def by_ts(ocon, ts_list) -> dict:
    """{ts: row} for a small batch (the /do history) in one query."""
    _ensure(ocon)
    ids = [t for t in ts_list if TS_RE.match(t or "")]
    if not ids:
        return {}
    q = ",".join("?" for _ in ids)
    return {r["ts"]: r for r in
            ocon.execute(f"SELECT * FROM runs WHERE ts IN ({q})", ids)}


def unacked_failures(ocon, within_hours: int = 24) -> list:
    _ensure(ocon)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    return list(ocon.execute(
        "SELECT * FROM runs WHERE outcome IN (?,?,?) AND acked=0 AND started>=?"
        " ORDER BY started DESC LIMIT 5", (*ALERT_OUTCOMES, cutoff)))


def ack(ocon, ts: str) -> None:
    if not TS_RE.match(ts or ""):
        return
    _ensure(ocon)
    ocon.execute("UPDATE runs SET acked=1 WHERE ts=?", (ts,))
    ocon.commit()


def mark_cancelled(ocon, ts: str) -> bool:
    """Operator cancel, recorded BEFORE the kill signal so the reaper's
    record_exit (which never downgrades this) can't turn it into 'exit -15'."""
    if not TS_RE.match(ts or ""):
        return False
    _ensure(ocon)
    ocon.execute("INSERT OR IGNORE INTO runs (ts, started, outcome)"
                 " VALUES (?,?,'running')", (ts, _now()))
    cur = ocon.execute("UPDATE runs SET outcome='cancelled', ended=?"
                       " WHERE ts=? AND outcome='running'", (_now(), ts))
    ocon.commit()
    return cur.rowcount > 0


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, OSError):
        return False


def _ts_started(ts: str) -> str:
    try:
        return datetime.strptime(ts[:15], "%Y%m%d-%H%M%S").replace(
            tzinfo=timezone.utc).isoformat()
    except ValueError:
        return _now()


def sweep(ocon) -> int:
    """Reconcile the ledger with the dispatch dir. Two duties:
    1. Backfill runs the ledger never saw (pre-0.12 runs; console died before
       record_launch). A live pid is adopted as 'running'; no pid to consult
       means 'unknown' — which never alerts (demo seeds log files with no pid;
       an invented failure would be worse than a missed one).
    2. Finalize rows stuck 'running' whose pid is gone (console crashed mid-run,
       the reaper never fired): 'dead' at 0 bytes (alerts), else 'orphaned'.
    Also the cross-boot watchdog: an adopted run past the timeout whose .pid
    file still exists gets a best-effort SIGTERM and is recorded 'killed'."""
    from . import dispatch  # lazy: dispatch imports runs at module level
    _ensure(ocon)
    d = config.data_dir() / "dispatch"
    changed = 0
    if d.is_dir():
        briefs = sorted(d.glob("*-brief.md"), reverse=True)[:50]
        ids = [b.name[:-len("-brief.md")] for b in briefs]
        have = by_ts(ocon, ids)
        for ts in ids:
            if ts in have or not TS_RE.match(ts):
                continue
            log = d / f"{ts}.log"
            if not log.is_file():
                continue  # brief-only (agent was disabled): nothing ran
            pid = None
            pidf = d / f"{ts}.pid"
            if pidf.is_file():
                try:
                    pid = int(pidf.read_text().strip())
                except (ValueError, OSError):
                    pid = None
            if pid and _pid_alive(pid):
                ocon.execute(
                    "INSERT OR IGNORE INTO runs (ts, pid, started, outcome,"
                    " task) VALUES (?,?,?,?,?)",
                    (ts, pid, _ts_started(ts), "running", dispatch._task_of(ts)[:300]))
            else:
                try:
                    nbytes = log.stat().st_size
                except OSError:
                    nbytes = 0
                ocon.execute(
                    "INSERT OR IGNORE INTO runs (ts, pid, started, ended,"
                    " stdout_bytes, stderr_tail, outcome, task)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (ts, pid, _ts_started(ts), _now(), nbytes,
                     dispatch.tail(ts, TAIL_BYTES), "unknown",
                     dispatch._task_of(ts)[:300]))
            changed += 1
    timeout_s = _timeout_seconds()
    for row in list(ocon.execute("SELECT * FROM runs WHERE outcome='running'")):
        ts, pid = row["ts"], row["pid"]
        alive = _pid_alive(pid)
        if alive and timeout_s > 0:
            try:
                started = datetime.fromisoformat(row["started"])
                over = (datetime.now(timezone.utc) - started).total_seconds() > timeout_s
            except ValueError:
                over = False
            pidf = config.data_dir() / "dispatch" / f"{ts}.pid"
            if over and pidf.is_file():
                # cross-boot watchdog: pid only (no pgid across boots), and only
                # while our own .pid file vouches for it — pid reuse containment
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except OSError:
                    pass
                _finalize_from_disk(ocon, ts, "killed")
                changed += 1
            continue
        if alive:
            continue
        nbytes = _log_bytes(ts)
        _finalize_from_disk(ocon, ts, "dead" if nbytes == 0 else "orphaned")
        changed += 1
    if changed:
        ocon.commit()
    return changed


def _log_bytes(ts: str) -> int:
    log = config.data_dir() / "dispatch" / f"{ts}.log"
    try:
        return log.stat().st_size
    except OSError:
        return 0


def _finalize_from_disk(ocon, ts: str, outcome: str) -> None:
    from . import dispatch
    ocon.execute(
        "UPDATE runs SET ended=?, stdout_bytes=?, stderr_tail=?, outcome=?"
        " WHERE ts=? AND outcome='running'",
        (_now(), _log_bytes(ts), dispatch.tail(ts, TAIL_BYTES), outcome, ts))


def _timeout_seconds() -> float:
    """[agent] timeout_minutes (default 30, 0 = watchdog off). Floats allowed —
    tests need sub-minute timeouts."""
    try:
        m = float(config.load().get("agent", {}).get("timeout_minutes", 30))
    except (TypeError, ValueError):
        m = 30.0
    return max(0.0, m) * 60.0
