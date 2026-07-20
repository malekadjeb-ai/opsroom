"""Agent proposals — the operator loop's return path. A dispatched agent can end
its run by printing fenced blocks; opsroom parses them into PROPOSED ledger writes
that appear on the console for one-tap approval. The agent suggests; you decide;
the ledger moves. Nothing applies without your tap.

Protocol (documented in every dispatch brief):

    ```opsroom
    {"propose": "cash", "amount": 380, "venture": "shopkit", "what": "setup collected"}
    ```

One JSON object per fence, fence at column 0. Verbs map 1:1 onto the console's own
write actions — an agent can propose nothing you couldn't already do with one form
tap: touch, cash, spend, lead_add, lead_touch, followup, capture, dispatch.

Threat model — agent stdout is UNTRUSTED input. The agent ran with whatever powers
your CLI gives it and read a brief containing ingested third-party text (lead
notes, reply snippets), so its log may carry attacker-influenced content (prompt
injection via a lead's note that talks the agent into echoing a proposal block).
Controls, in order of load-bearing-ness:
  1. NO AUTO-APPLY, EVER. A proposal is a pending row + a rendered summary; only a
     CSRF-gated, loopback-only human tap writes to the ledger.
  2. Verb whitelist onto existing ops.py write functions — no new capability
     surface, no arbitrary keys, no schema access.
  3. A proposed `dispatch` re-enters the normal gate: command only from config,
     [agent] enabled still required, task capped, brief re-scrubbed.
  4. Fail-closed scrubbing: every stored string passes redact.scrub() at stage
     time; summaries are HTML-escaped at render; payloads render only as
     summaries, never raw.
  5. Resource caps: last 256 KB of log scanned, 4 KB per block, 16 proposals per
     run, every field truncated to the same caps POST /act enforces.
  6. Idempotence: UNIQUE(dispatch_ts, verb, payload) + claim-inside-transaction
     make re-parses and double-taps no-ops. dispatch ids are TS_RE-validated, so
     harvest can never be steered to an arbitrary path.
  7. Brief-echo injection: the fence regex anchors at column 0 and the brief's
     protocol example is indented with an invalid example venture — an agent that
     echoes its own brief verbatim stages nothing.
  Residual risk — a crafted lead note containing a column-0 fence the agent then
  echoes — is accepted because of (1): it becomes a VISIBLE pending row with a
  provenance link to the raw log, not a write.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from . import config, ops, redact, ventures

MAX_SCAN = 256 * 1024      # only the last 256 KB of a log is ever parsed
MAX_BLOCK = 4 * 1024       # one JSON object per fence, 4 KB cap
MAX_PER_RUN = 16           # first 16 valid proposals win; the rest are dropped
MAX_FOLLOWUP_DAYS = 60

TS_RE = re.compile(r"^\d{8}-\d{6}-\d+$")  # same shape dispatch.py enforces
FENCE = re.compile(r"^```opsroom[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)

# field -> truncation cap, matching what POST /act enforces on the same fields
_CAPS = {"target": 120, "kind": 20, "note": 300, "what": 200, "name": 80,
         "phone": 30, "service": 80, "venture": 40, "task": 300, "text": 500,
         "due": 20}

VERBS = ("touch", "cash", "spend", "lead_add", "lead_touch", "followup",
         "capture", "dispatch")
_LEAD_KINDS = ("called", "texted", "emailed", "quoted", "collected", "lost")

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  dispatch_ts TEXT NOT NULL,
  verb        TEXT NOT NULL,
  payload     TEXT NOT NULL,
  summary     TEXT NOT NULL,
  status      TEXT DEFAULT 'pending',
  created     TEXT NOT NULL,
  decided     TEXT,
  UNIQUE(dispatch_ts, verb, payload)
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status, created);
"""


def _ensure(con) -> None:
    con.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- parse / validate

def parse(text: str) -> list:
    """Extract candidate proposal dicts from agent output. Fail-closed: anything
    that isn't a clean fenced JSON object is skipped, never surfaced."""
    out = []
    for m in FENCE.finditer(text or ""):
        raw = m.group(1).strip()
        if not raw or len(raw) > MAX_BLOCK:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _s(obj, key: str) -> str:
    """A scrubbed, truncated string field ('' if absent or not a string).
    Scrub BEFORE truncating: a cap boundary must never split a secret into an
    unrecognizable half (the block is already ≤4 KB, so scrubbing is cheap)."""
    v = obj.get(key)
    if not isinstance(v, str):
        return ""
    return redact.scrub(v.strip())[:_CAPS.get(key, 120)]


def _amount(obj):
    """JSON number only (never a string, bool, or negative). None = invalid."""
    v = obj.get("amount")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not (0 < v <= 1_000_000):
        return None
    return round(float(v), 2)


def _venture(obj, allow_empty_as: str = ""):
    """A venture key that exists in config (never 'unknown'). Returns the key,
    allow_empty_as when the field is absent/empty, or None when it names a
    venture that doesn't exist (fail-closed)."""
    v = _s(obj, "venture")
    if not v:
        return allow_empty_as
    return v if (v in ventures.VENTURES and v != "unknown") else None


def _due(obj):
    """'+Nd' (1..60) or an ISO date no more than 60 days out. None = invalid."""
    v = _s(obj, "due")
    today = datetime.now().astimezone().date()
    m = re.fullmatch(r"\+(\d{1,2})d", v)
    if m:
        n = int(m.group(1))
        return (today + timedelta(days=n)).isoformat() if 1 <= n <= MAX_FOLLOWUP_DAYS else None
    try:
        d = date.fromisoformat(v)
    except ValueError:
        return None
    return d.isoformat() if d <= today + timedelta(days=MAX_FOLLOWUP_DAYS) else None


def validate(obj: dict):
    """Whitelist + caps + venture existence + amount rules. Returns the canonical
    clean payload dict (json-serializable, fully scrubbed) or None."""
    verb = obj.get("propose")
    if verb not in VERBS:
        return None
    if verb == "touch":
        target, venture = _s(obj, "target"), _venture(obj)
        if not target or venture is None:
            return None
        return {"verb": "touch", "target": target, "venture": venture,
                "kind": _s(obj, "kind") or "touch", "note": _s(obj, "note")}
    if verb in ("cash", "spend"):
        amt, venture = _amount(obj), _venture(obj, allow_empty_as="other")
        if amt is None or venture is None:
            return None
        return {"verb": verb, "amount": amt, "venture": venture, "what": _s(obj, "what")}
    if verb == "lead_add":
        name, venture = _s(obj, "name"), _venture(obj)
        if not name or venture is None:
            return None
        return {"verb": "lead_add", "name": name, "phone": _s(obj, "phone"),
                "service": _s(obj, "service"), "note": _s(obj, "note"),
                "venture": venture}
    if verb == "lead_touch":
        lid, kind = obj.get("lead"), _s(obj, "kind")
        if isinstance(lid, bool) or not isinstance(lid, int) or lid <= 0:
            return None
        if kind not in _LEAD_KINDS:
            return None
        out = {"verb": "lead_touch", "lead": lid, "kind": kind, "note": _s(obj, "note")}
        if kind in ("quoted", "collected"):
            amt = _amount(obj)
            if amt is None:
                return None  # a $0 'collected' is how money vanishes from the goal bar
            out["amount"] = amt
        return out
    if verb == "followup":
        target, due, venture = _s(obj, "target"), _due(obj), _venture(obj)
        if not target or due is None or venture is None:
            return None
        return {"verb": "followup", "target": target, "due": due,
                "venture": venture, "note": _s(obj, "note")}
    if verb == "capture":
        text = _s(obj, "text")
        return {"verb": "capture", "text": text} if text else None
    if verb == "dispatch":
        task, venture = _s(obj, "task"), _venture(obj)
        if not task or venture is None:
            return None
        return {"verb": "dispatch", "task": task, "venture": venture}
    return None


def _vlabel(key: str) -> str:
    return ventures.VENTURES.get(key, {}).get("label", key) if key else ""


def summarize(payload: dict) -> str:
    """The human one-liner the console renders (escaped again at render time)."""
    v, p = payload["verb"], payload
    vl = _vlabel(p.get("venture", ""))
    if v == "touch":
        return f"log {p['kind']} touch → {p['target']}" + (f" ({vl})" if vl else "")
    if v == "cash":
        return f"record ${p['amount']:,.0f} collected → {vl or 'other'}" + \
            (f" — {p['what']}" if p["what"] else "")
    if v == "spend":
        return f"record ${p['amount']:,.0f} spent → {vl or 'other'}" + \
            (f" — {p['what']}" if p["what"] else "")
    if v == "lead_add":
        bits = [b for b in (p["service"], p["phone"]) if b]
        return f"add lead: {p['name']}" + (f" ({' · '.join(bits)})" if bits else "")
    if v == "lead_touch":
        amt = f" ${p['amount']:,.0f}" if "amount" in p else ""
        return f"mark lead #{p['lead']} {p['kind']}{amt}"
    if v == "followup":
        return f"schedule follow-up: {p['target']} — due {p['due']}"
    if v == "capture":
        return f"capture to inbox: {p['text'][:100]}"
    if v == "dispatch":
        return f"run next: {p['task'][:120]}" + (f" ({vl})" if vl else "")
    return v


# ---------------------------------------------------------------- stage / harvest

def stage(ocon, dispatch_ts: str, payloads: list) -> int:
    """Stage validated payloads as pending proposals. INSERT OR IGNORE + the
    UNIQUE key make re-staging the same run a no-op. Returns rows added."""
    _ensure(ocon)
    have = ocon.execute("SELECT COUNT(*) c FROM proposals WHERE dispatch_ts=?",
                        (dispatch_ts,)).fetchone()["c"]
    added = 0
    for p in payloads[:max(0, MAX_PER_RUN - have)]:
        cur = ocon.execute(
            "INSERT OR IGNORE INTO proposals (dispatch_ts, verb, payload, summary, created)"
            " VALUES (?,?,?,?,?)",
            (dispatch_ts, p["verb"], json.dumps(p, sort_keys=True),
             redact.scrub(summarize(p)), _now()))
        added += cur.rowcount
    ocon.commit()
    return added


def harvest(ocon, ts: str) -> int:
    """Read one dispatch's log (last 256 KB), parse → validate → stage. Marks the
    run harvested so the sweep never re-reads it. Returns proposals staged."""
    if not TS_RE.match(ts or ""):
        return 0
    log = config.data_dir() / "dispatch" / f"{ts}.log"
    text = ""
    if log.is_file():
        size = log.stat().st_size
        with open(log, "rb") as fh:
            if size > MAX_SCAN:
                fh.seek(size - MAX_SCAN)
            text = fh.read().decode(errors="replace")
    payloads = [p for p in (validate(o) for o in parse(text)) if p]
    added = stage(ocon, ts, payloads)
    ops.kv_set(ocon, f"prop_harvested::{ts}", "1")
    return added


def harvest_finished(ocon) -> int:
    """Sweep recent finished dispatches that were never harvested (agent reaped
    while the console was down). Called from the serve page build; cheap when
    there's nothing to do."""
    from . import dispatch  # lazy: dispatch imports proposals at module load
    added = 0
    for r in dispatch.recent(limit=8):
        st = r.get("status") or ""
        if st == "done" or st.startswith("exit"):
            if not ops.kv_get(ocon, f"prop_harvested::{r['tsid']}", ""):
                added += harvest(ocon, r["tsid"])
    return added


# ---------------------------------------------------------------- decide / apply

def pending(ocon) -> list:
    _ensure(ocon)
    return ocon.execute(
        "SELECT * FROM proposals WHERE status='pending' ORDER BY created DESC LIMIT 30"
    ).fetchall()


def claim(ocon, pid: int, status: str) -> dict | None:
    """Atomically claim a pending (or queued) proposal (double-tap = rowcount 0 =
    None). Does NOT commit — the caller's ledger write commits the claim with it,
    so claim + write land in one transaction."""
    cur = ocon.execute(
        "UPDATE proposals SET status=?, decided=? WHERE id=? AND status IN ('pending','queued')",
        (status, _now(), pid))
    if cur.rowcount != 1:
        return None
    row = ocon.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else None


def unclaim(ocon, pid: int) -> None:
    """Roll a failed apply back to pending so the operator can retry."""
    ocon.execute("UPDATE proposals SET status='pending', decided=NULL WHERE id=?", (pid,))
    ocon.commit()


def dismiss(ocon, pid: int) -> bool:
    row = claim(ocon, pid, "dismissed")
    ocon.commit()
    return row is not None


def apply_payload(ocon, payload: dict) -> None:
    """Route a claimed non-dispatch proposal through the SAME ops.py functions the
    manual forms use. Every one of these commits — persisting the claim with it."""
    v = payload["verb"]
    if v == "touch":
        ops.log_touch(ocon, payload["venture"], payload["target"], payload["kind"],
                      payload["note"])
    elif v == "cash":
        ops.log_cash(ocon, payload["amount"], payload["venture"], payload["what"])
    elif v == "spend":
        ops.log_spend(ocon, payload["amount"], payload["venture"], payload["what"])
    elif v == "lead_add":
        ops.add_lead(ocon, payload["name"], payload["phone"], payload["service"],
                     payload["note"], venture=payload["venture"])
    elif v == "lead_touch":
        row = ocon.execute("SELECT id FROM leads WHERE id=?", (payload["lead"],)).fetchone()
        if not row:
            raise ValueError(f"lead #{payload['lead']} no longer exists")
        ops.touch_lead(ocon, payload["lead"], payload["kind"], payload.get("amount"),
                       payload["note"])
    elif v == "followup":
        ops.followup_add(ocon, payload["target"], payload["due"], payload["venture"],
                         payload["note"])
    elif v == "capture":
        ops.capture(ocon, payload["text"])
    else:  # dispatch is handled by the caller (it needs the serve reaper hook)
        raise ValueError(f"apply_payload can't handle verb {v!r}")


# ---------------------------------------------------------------- work queue

def enqueue(ocon, task: str, venture: str = "", lead: int = 0,
            source: str = "operator") -> int:
    """Queue a dispatch to auto-fire when the current agent finishes. Reuses the
    proposals table (verb=dispatch, status=queued) — same dedup, same visibility.
    source is 'operator' or the dispatch id that proposed the chain."""
    _ensure(ocon)
    payload = {"verb": "dispatch", "task": redact.scrub((task or "").strip())[:300],
               "venture": venture if venture in ventures.VENTURES and venture != "unknown"
               else ""}
    if lead:
        payload["lead"] = int(lead)
    if not payload["task"]:
        return 0
    # "q:" namespace: a queued copy must never collide (UNIQUE) with the original
    # harvested proposal row that produced it
    cur = ocon.execute(
        "INSERT OR IGNORE INTO proposals (dispatch_ts, verb, payload, summary, status, created)"
        " VALUES (?,?,?,?,'queued',?)",
        (f"q:{source}", "dispatch", json.dumps(payload, sort_keys=True),
         redact.scrub(summarize(payload)), _now()))
    ocon.commit()
    return cur.rowcount


def queued(ocon) -> list:
    _ensure(ocon)
    return ocon.execute(
        "SELECT * FROM proposals WHERE status='queued' ORDER BY created ASC LIMIT 20"
    ).fetchall()


def pop_queued(ocon) -> dict | None:
    """Claim the oldest queued dispatch (FIFO) for firing. UPDATE-with-rowcount so
    two racing reapers can never both fire the same item."""
    _ensure(ocon)
    row = ocon.execute(
        "SELECT * FROM proposals WHERE status='queued' ORDER BY created ASC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    cur = ocon.execute(
        "UPDATE proposals SET status='fired', decided=? WHERE id=? AND status='queued'",
        (_now(), row["id"]))
    ocon.commit()
    if cur.rowcount != 1:
        return None  # another reaper won the race
    return json.loads(row["payload"])


# ---------------------------------------------------------------- brief appendix

# Indented example on purpose: the fence regex anchors at column 0, so an agent
# echoing this appendix back stages nothing; the example venture is invalid too.
PROTOCOL_APPENDIX = """
## PROPOSE RESULTS (optional)
When you finish, you may propose ledger updates. Print each as its own fenced
block, at the start of a line, one JSON object per block:

    ```opsroom
    {"propose": "cash", "amount": 380, "venture": "your-venture-key", "what": "what it was for"}
    ```

Verbs: touch (target, kind, note) · cash/spend (amount, venture, what) ·
lead_add (name, phone, service, note, venture) · lead_touch (lead id, kind:
called/texted/emailed/quoted/collected/lost, amount for quoted/collected) ·
followup (target, due "+2d" or ISO date, note) · capture (text) ·
dispatch (task, venture — propose the next agent run).
Use the venture key from this brief. Max 16 proposals.
NOTHING applies automatically — every proposal appears on the operator's console
and only their explicit one-tap approval writes to the ledger.
"""
