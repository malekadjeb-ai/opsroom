"""Counsel — the console thinks. Two surfaces on the same machinery:

  ASK    — the operator types a question on the NOW tab; opsroom dispatches it to
           the configured agent CLI with the full live context; the ANSWER renders
           as first-class console content (a card and the /counsel page), any plan
           becomes ▶-dispatchable steps, any ```opsroom blocks become proposals.
  ADVISE — on a schedule ([agent] advise), opsroom launches the agent BY ITSELF to
           assess the whole board and surface plays BEYOND the derived DO NOW.
           The operator opens the console to a briefing that was thought up while
           they were away.

Protocol (appended to ask/advise briefs): the agent answers in exactly ONE fenced
markdown block at column 0 —

    ```counsel
    ## Verdict
    …
    ```

— optionally adds ONE plan block —

    ```counsel-plan
    {"steps": [{"task": "…", "venture": "your-venture-key", "why": "…"}]}
    ```

— and proposes ledger writes via the existing ```opsroom blocks.

Threat model — counsel is RENDERED AGENT PROSE, i.e. untrusted input that may
carry attacker text (prompt injection via ingested lead notes echoed into the
answer). Controls:
  1. Scrub at store (redact.scrub BEFORE truncation), 16 KB answer cap, 4 KB plan
     cap, 7-step cap; the renderer (dashboard.md_html) escapes EVERYTHING first
     and never generates links, images, or raw HTML — URLs render inert.
  2. Plan steps are INERT: a ▶ button only opens a /do brief; queueing re-enters
     the CSRF-gated dispatch_queue verb; execution still requires [agent] enabled
     with a config-file-only command.
  3. The autonomous advisor is opsroom's FIRST unattended agent launch, so it is a
     SECOND opt-in ([agent] advise, default off) beyond [agent] enabled; its task
     string is a hard-coded constant (never derived from ingested text); it fires
     at most once per window (claim-the-window-first kv write, so a crash skips a
     window rather than loop-firing) and never while anything else is running.
  4. Registered-runs-only harvest: counsel fences are read ONLY from runs this
     module registered at dispatch time — a fence smuggled into an ordinary run's
     log is never stored or rendered.
  5. Idempotence: UNIQUE(dispatch_ts), kv harvest markers, UPDATE-with-rowcount
     archive; every ts is TS_RE-validated so nothing can be steered to a path.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import config, ops, redact, ventures

MAX_SCAN = 256 * 1024
MAX_ANSWER = 16 * 1024
MAX_BLOCK = 4 * 1024
MAX_STEPS = 7
MAX_QUESTION = 500

TS_RE = re.compile(r"^\d{8}-\d{6}-\d+$")
COUNSEL_FENCE = re.compile(r"^```counsel[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
PLAN_FENCE = re.compile(r"^```counsel-plan[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
_NUM_LINE = re.compile(r"^([1-9])\.\s+(.+)$", re.M)

ADVISE_TASK = "Advisor briefing — assess the whole board and find what's being missed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS counsel (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  dispatch_ts TEXT NOT NULL UNIQUE,
  kind        TEXT NOT NULL,
  question    TEXT NOT NULL DEFAULT '',
  answer      TEXT NOT NULL DEFAULT '',
  plan_json   TEXT NOT NULL DEFAULT '[]',
  status      TEXT DEFAULT 'open',
  created     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_counsel_status ON counsel(status, created);
"""


def _ensure(con) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- parse

def parse_answer(text: str) -> str:
    """The FIRST valid ```counsel block (agents ramble; the answer should lead).
    Scrub before truncate — a cap boundary must never split a secret."""
    m = COUNSEL_FENCE.search(text or "")
    if not m:
        return ""
    body = m.group(1).strip()
    if not body:
        return ""
    scrubbed = redact.scrub(body)
    if len(scrubbed) > MAX_ANSWER:
        scrubbed = scrubbed[:MAX_ANSWER] + "\n\n…(truncated)"
    return scrubbed


def _clean_step(obj) -> dict | None:
    if not isinstance(obj, dict) or not isinstance(obj.get("task"), str):
        return None
    task = redact.scrub(obj["task"].strip())[:300]
    if not task:
        return None
    venture = obj.get("venture") if isinstance(obj.get("venture"), str) else ""
    # steps are dispatch BRIEFS, not writes — an unknown venture degrades to
    # unattributed instead of rejecting the whole step
    if venture not in ventures.VENTURES or venture == "unknown":
        venture = ""
    why = redact.scrub(obj["why"].strip())[:200] if isinstance(obj.get("why"), str) else ""
    return {"task": task, "venture": venture, "why": why}


def parse_plan(text: str, answer_md: str = "") -> list:
    """```counsel-plan JSON steps (validated, capped), else a fallback scan of
    the answer's column-0 'N. step' lines — flaky agents stay useful."""
    m = PLAN_FENCE.search(text or "")
    if m:
        raw = m.group(1).strip()
        if raw and len(raw) <= MAX_BLOCK:
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = None
            if isinstance(obj, dict) and isinstance(obj.get("steps"), list):
                steps = [s for s in (_clean_step(x) for x in obj["steps"]) if s]
                if steps:
                    return steps[:MAX_STEPS]
    steps = []
    for m2 in _NUM_LINE.finditer(answer_md or ""):
        steps.append({"task": redact.scrub(m2.group(2).strip())[:300],
                      "venture": "", "why": ""})
        if len(steps) >= MAX_STEPS:
            break
    return steps


# ---------------------------------------------------------------- store / harvest

def register(ocon, ts: str, kind: str, question: str = "") -> int:
    """Mark a dispatch as a counsel run AT DISPATCH TIME. harvest() only fills
    registered rows — the fail-closed gate against smuggled fences."""
    if not TS_RE.match(ts or "") or kind not in ("ask", "advise"):
        return 0
    _ensure(ocon)
    cur = ocon.execute(
        "INSERT OR IGNORE INTO counsel (dispatch_ts, kind, question, created)"
        " VALUES (?,?,?,?)",
        (ts, kind, redact.scrub((question or "").strip())[:MAX_QUESTION], _now()))
    ocon.commit()
    return cur.lastrowid if cur.rowcount else 0


def harvest(ocon, ts: str) -> bool:
    """Read a REGISTERED run's log tail, store answer + plan. Empty answer still
    marks harvested (the agent didn't comply; the page shows the log instead)."""
    _ensure(ocon)
    if not TS_RE.match(ts or ""):
        return False
    row = ocon.execute("SELECT id FROM counsel WHERE dispatch_ts=?", (ts,)).fetchone()
    if not row:
        return False  # unregistered run: a counsel fence there is ignored, by design
    log = config.data_dir() / "dispatch" / f"{ts}.log"
    text = ""
    if log.is_file():
        size = log.stat().st_size
        with open(log, "rb") as fh:
            if size > MAX_SCAN:
                fh.seek(size - MAX_SCAN)
            text = fh.read().decode(errors="replace")
    answer = parse_answer(text)
    plan = parse_plan(text, answer)
    ocon.execute("UPDATE counsel SET answer=?, plan_json=? WHERE dispatch_ts=?",
                 (answer, json.dumps(plan, sort_keys=True), ts))
    ocon.commit()
    ops.kv_set(ocon, f"counsel_harvested::{ts}", "1")
    return True


def harvest_finished(ocon) -> int:
    """Sweep recent open counsel rows whose runs finished while the console was
    down. Targeted at the counsel table itself — cheap when there's nothing."""
    from . import dispatch  # lazy: dispatch imports counsel at brief-build time
    _ensure(ocon)
    done = 0
    rows = ocon.execute(
        "SELECT dispatch_ts FROM counsel WHERE status='open' "
        "ORDER BY created DESC LIMIT 8").fetchall()
    for r in rows:
        ts = r["dispatch_ts"]
        if ops.kv_get(ocon, f"counsel_harvested::{ts}", ""):
            continue
        st = dispatch.status(ts)
        if st == "done" or st.startswith("exit"):
            if harvest(ocon, ts):
                done += 1
    return done


# ---------------------------------------------------------------- reads / decisions

def _row(r) -> dict:
    d = dict(r)
    try:
        d["plan"] = json.loads(d.get("plan_json") or "[]")
    except ValueError:
        d["plan"] = []
    return d


def latest_open(ocon) -> dict | None:
    _ensure(ocon)
    r = ocon.execute("SELECT * FROM counsel WHERE status='open' "
                     "ORDER BY created DESC LIMIT 1").fetchone()
    return _row(r) if r else None


def get(ocon, ts: str) -> dict | None:
    _ensure(ocon)
    if not TS_RE.match(ts or ""):
        return None
    r = ocon.execute("SELECT * FROM counsel WHERE dispatch_ts=?", (ts,)).fetchone()
    return _row(r) if r else None


def recent(ocon, limit: int = 8) -> list:
    _ensure(ocon)
    return [_row(r) for r in ocon.execute(
        "SELECT * FROM counsel ORDER BY created DESC LIMIT ?", (limit,)).fetchall()]


def archive(ocon, cid: int) -> bool:
    _ensure(ocon)
    cur = ocon.execute(
        "UPDATE counsel SET status='archived' WHERE id=? AND status='open'", (cid,))
    ocon.commit()
    return cur.rowcount == 1


# ---------------------------------------------------------------- the advisor

def advise_due(mode, last_iso: str, now=None) -> bool:
    """Pure window math, clock-injectable. mode: 'off'|'daily'|int hours (2..168).
    daily = one briefing per LOCAL calendar day, never before 06:00 local."""
    now = now or datetime.now().astimezone()
    last = None
    if last_iso:
        try:
            last = datetime.fromisoformat(last_iso).astimezone(now.tzinfo)
        except ValueError:
            last = None  # malformed = never ran = fire
    if mode == "daily":
        if now.hour < 6:
            return False
        return last is None or last.date() < now.date()
    if isinstance(mode, bool):
        return False
    if isinstance(mode, int):
        if not (2 <= mode <= 168):
            return False
        return last is None or (now - last) >= timedelta(hours=mode)
    return False


def advise_tick(ocon, on_exit=None) -> str:
    """The sync-loop entry: fire ONE advise run when the window is due and the
    runway is clear. Returns the dispatch ts, or '' when nothing fired."""
    from . import dispatch
    if not dispatch.agent_ready():
        return ""
    mode = config.load().get("agent", {}).get("advise", "off")
    now = datetime.now().astimezone()
    if not advise_due(mode, ops.kv_get(ocon, "advise_last", ""), now):
        return ""
    if dispatch.running():
        return ""  # never fight operator work; the window persists to the next tick
    # CLAIM FIRST: a crash between here and launch skips one window, never loops
    ops.kv_set(ocon, "advise_last", now.isoformat())
    r = dispatch.dispatch(ADVISE_TASK, kind="advise", on_exit=on_exit)
    register(ocon, r["ts"], "advise", "")
    return r["ts"]


# ---------------------------------------------------------------- brief appendices

# Examples INDENTED on purpose: fence regexes anchor at column 0, so an agent
# echoing this appendix stages nothing (same defense as proposals.py).
ANSWER_APPENDIX = """
## ANSWER PROTOCOL
Answer in exactly ONE fenced markdown block, fence at the start of a line:

    ```counsel
    ## Verdict
    Lead with the answer. Be concrete and money-first. Ground every claim in the
    LIVE OPERATOR CONTEXT above — never invent names, numbers, or state.
    ```

If you recommend a sequence of actions, ALSO print one plan block (max 7 steps,
each task under 300 chars, venture keys from this brief):

    ```counsel-plan
    {"steps": [{"task": "…", "venture": "your-venture-key", "why": "…"}]}
    ```

Propose ledger-shaped facts (cash collected, follow-ups, leads) via the
```opsroom blocks described above. Nothing renders as anything but text, and
nothing applies without the operator's one-tap approval.
"""

ADVISE_APPENDIX = """
## ADVISOR MANDATE
You were launched on a schedule, not by the operator — they will read this cold.
Lead with the verdict. Your ```counsel block must contain:
1. An honest assessment of the board: what's working, what's slipping, what's
   being missed.
2. 3-5 ranked plays BEYOND the derived DO NOW queue shown in the context above —
   new angles the rules can't see, not restatements of existing rows.
3. Then the ```counsel-plan block with the concrete next sequence.
Propose anything ledger-shaped via ```opsroom blocks.
"""
