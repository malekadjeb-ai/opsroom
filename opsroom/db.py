"""SQLite layer: schema, WAL, permission enforcement, sync-root guard."""
import os
import sqlite3
import stat
import sys
from pathlib import Path

from . import config as _config

DB_DIR = _config.data_dir()
DB_PATH = DB_DIR / "activity.db"

# Directories that sync to a cloud on macOS. The DB must never live under one.
SYNC_ROOT_MARKERS = ["Mobile Documents", "/Documents/", "/Desktop/", "Dropbox", "OneDrive",
                     "Google Drive", "/mnt/c/"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id          TEXT PRIMARY KEY,
  ts          TEXT NOT NULL,
  source      TEXT NOT NULL,
  session_id  TEXT,
  venture     TEXT,
  project     TEXT,
  kind        TEXT,
  actor       TEXT,
  summary     TEXT,
  detail      TEXT,
  artifacts   TEXT,
  raw_ref     TEXT,
  is_sidechain INTEGER DEFAULT 0,
  redacted    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  duration_min  REAL,
  venture       TEXT,
  project       TEXT,
  git_branch    TEXT,
  prompt_count  INTEGER,
  tool_calls    INTEGER,
  files_touched INTEGER,
  commits_after INTEGER DEFAULT 0,
  outcome       TEXT,
  summary       TEXT,
  open_loops    TEXT
);
CREATE TABLE IF NOT EXISTS loops (
  id          TEXT PRIMARY KEY,
  opened_at   TEXT NOT NULL,
  session_id  TEXT,
  venture     TEXT,
  project     TEXT,
  description TEXT NOT NULL,
  evidence    TEXT NOT NULL,
  signal      TEXT,
  confidence  REAL DEFAULT 0.5,
  age_days    INTEGER,
  status      TEXT DEFAULT 'open',
  closed_by   TEXT,
  last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS watermarks (
  source     TEXT PRIMARY KEY,
  last_ts    TEXT,
  last_ref   TEXT,
  last_run   TEXT,
  status     TEXT
);
CREATE TABLE IF NOT EXISTS file_state (
  path   TEXT PRIMARY KEY,
  mtime  REAL,
  size   INTEGER,
  lines  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_venture_ts ON events(venture, ts);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_loops_status ON loops(status, age_days);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(summary, detail, content='events', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
  INSERT INTO events_fts(rowid, summary, detail) VALUES (new.rowid, new.summary, new.detail);
END;
CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
  INSERT INTO events_fts(events_fts, rowid, summary, detail) VALUES ('delete', old.rowid, old.summary, old.detail);
END;
"""


def _assert_safe_location() -> None:
    p = str(DB_PATH.resolve())
    for marker in SYNC_ROOT_MARKERS:
        if marker in p:
            sys.exit(f"FATAL: DB path {p} appears to be inside a sync root ({marker}). Refusing.")


def enforce_perms() -> None:
    if DB_DIR.exists():
        os.chmod(DB_DIR, stat.S_IRWXU)  # 700
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(DB_PATH) + suffix)
        if f.exists():
            os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 600


def connect() -> sqlite3.Connection:
    _assert_safe_location()
    DB_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DB_DIR, stat.S_IRWXU)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=15000")  # a sync tick must not 500 a concurrent write
    con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    enforce_perms()
    return con


def set_watermark(con, source: str, status: str, last_ts: str = None, last_ref: str = None) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """INSERT INTO watermarks(source, last_ts, last_ref, last_run, status) VALUES (?,?,?,?,?)
           ON CONFLICT(source) DO UPDATE SET
             last_ts=COALESCE(excluded.last_ts, watermarks.last_ts),
             last_ref=COALESCE(excluded.last_ref, watermarks.last_ref),
             last_run=excluded.last_run, status=excluded.status""",
        (source, last_ts, last_ref, now, status))
