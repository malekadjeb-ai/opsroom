"""Heuristic enrichment: sessions from events, outcome classification, open-loop detection,
effort-vs-revenue drift. Pure local computation; the optional LLM pass is out of scope for now."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from . import ventures

PLAN_LANGUAGE = re.compile(
    r"\b(next step|next,? i|i'?ll |then i|remaining|left to do|todo|to do:|when you'?re ready|"
    r"once you|after that|still need|queued|pending|follow[- ]up)\b", re.I)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    # canonical UTC format matching collectors.norm_ts, so string comparisons hold
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


GAP_CAP_MIN = 15  # idle gaps above this don't count as active time


def _active_minutes(ts_list) -> float:
    """Sum inter-event gaps capped at GAP_CAP_MIN: honest active time, not wall clock."""
    if len(ts_list) < 2:
        return 1.0
    total = 0.0
    prev = None
    for ts in ts_list:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if prev is not None:
            total += min((dt - prev).total_seconds() / 60, GAP_CAP_MIN)
        prev = dt
    return round(max(total, 1.0), 1)


def build_sessions(con) -> int:
    """Aggregate cli events into sessions rows. Idempotent (full rebuild of aggregates)."""
    rows = con.execute("""
        SELECT session_id,
               MIN(ts) AS started_at, MAX(ts) AS ended_at,
               SUM(CASE WHEN kind='prompt' AND is_sidechain=0 THEN 1 ELSE 0 END) AS prompts,
               SUM(CASE WHEN kind IN ('tool_call','file_edit') THEN 1 ELSE 0 END) AS tools,
               SUM(CASE WHEN kind='file_edit' THEN 1 ELSE 0 END) AS edits,
               MAX(project) AS project
        FROM events WHERE source='cli' AND session_id IS NOT NULL
        GROUP BY session_id""").fetchall()
    n = 0
    for r in rows:
        try:
            end = datetime.fromisoformat(r["ended_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        ts_list = [x["ts"] for x in con.execute(
            "SELECT ts FROM events WHERE session_id=? ORDER BY ts", (r["session_id"],))]
        dur = _active_minutes(ts_list)
        first_prompt = con.execute(
            "SELECT summary FROM events WHERE session_id=? AND kind='prompt' ORDER BY ts LIMIT 1",
            (r["session_id"],)).fetchone()
        # majority non-unknown venture; fall back to keyword attribution on the first prompt
        vrow = con.execute(
            """SELECT venture, COUNT(*) c FROM events WHERE session_id=? AND venture != 'unknown'
               GROUP BY venture ORDER BY c DESC LIMIT 1""", (r["session_id"],)).fetchone()
        venture = vrow["venture"] if vrow else ventures.attribute_text(
            (first_prompt["summary"] if first_prompt else "") + " " + (r["project"] or ""))
        commits_after = con.execute(
            """SELECT COUNT(*) c FROM events WHERE source='git' AND kind='commit'
               AND venture=? AND ts BETWEEN ? AND ?""",
            (venture, r["ended_at"],
             _iso(end + timedelta(hours=2)))).fetchone()["c"]
        outcome = _classify_outcome(con, r, end, commits_after)
        con.execute("""
            INSERT INTO sessions (id, source, started_at, ended_at, duration_min, venture, project,
                                  prompt_count, tool_calls, files_touched, commits_after, outcome, summary)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              started_at=excluded.started_at, ended_at=excluded.ended_at,
              duration_min=excluded.duration_min, venture=excluded.venture, project=excluded.project,
              prompt_count=excluded.prompt_count, tool_calls=excluded.tool_calls,
              files_touched=excluded.files_touched, commits_after=excluded.commits_after,
              outcome=excluded.outcome, summary=excluded.summary""",
            (r["session_id"], "cli", r["started_at"], r["ended_at"], dur, venture,
             r["project"], r["prompts"], r["tools"], r["edits"], commits_after, outcome,
             first_prompt["summary"] if first_prompt else None))
        n += 1
    return n


def _classify_outcome(con, r, end, commits_after) -> str:
    if commits_after > 0:
        return "shipped"
    age_h = (_now() - end).total_seconds() / 3600
    if age_h < 48:
        return "ongoing"
    later = con.execute(
        "SELECT 1 FROM events WHERE source='cli' AND project=? AND session_id!=? AND ts>? LIMIT 1",
        (r["project"], r["session_id"], r["ended_at"])).fetchone()
    if later:
        return "unknown"
    last = con.execute(
        """SELECT kind, detail FROM events WHERE session_id=? AND kind IN ('response','error')
           ORDER BY ts DESC LIMIT 1""", (r["session_id"],)).fetchone()
    if last and (last["kind"] == "error" or PLAN_LANGUAGE.search(last["detail"] or "")):
        return "abandoned"
    return "unknown"


# ---------------------------------------------------------------- loops

def _upsert_loop(con, signal, key, *, venture, project, description, evidence,
                 confidence, session_id=None, fired: set = None):
    lid = hashlib.sha256(f"{signal}|{key}".encode()).hexdigest()[:24]
    now = _iso(_now())
    row = con.execute("SELECT opened_at, status FROM loops WHERE id=?", (lid,)).fetchone()
    if row and row["status"] == "dismissed":
        fired.add(lid)
        return
    opened = row["opened_at"] if row else now
    age = (_now() - datetime.fromisoformat(opened)).days
    con.execute("""
        INSERT INTO loops (id, opened_at, session_id, venture, project, description, evidence,
                           signal, confidence, age_days, status, last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?)
        ON CONFLICT(id) DO UPDATE SET
          description=excluded.description, evidence=excluded.evidence, age_days=excluded.age_days,
          confidence=excluded.confidence, status='open', last_seen=excluded.last_seen""",
        (lid, opened, session_id, venture, project, description, evidence, signal,
         confidence, age, now))
    fired.add(lid)


def detect_loops(con, git_result: dict, vault_result: dict) -> dict:
    fired = set()
    # signals fully recomputed this run — only these may be auto-closed when they stop firing
    recomputed = {"abandoned_session", "orphan_task", "failed_exit"}
    if git_result.get("repo_states"):
        recomputed |= {"uncommitted_work", "stale_branch"}
    if "stale_notes" in vault_result:
        recomputed.add("stale_note")
    # 1. abandoned sessions with a stated plan
    for s in con.execute("""SELECT * FROM sessions WHERE outcome='abandoned'
                            AND duration_min >= 5 ORDER BY ended_at DESC LIMIT 100"""):
        last = con.execute(
            """SELECT summary, raw_ref FROM events WHERE session_id=? AND kind IN ('response','error')
               ORDER BY ts DESC LIMIT 1""", (s["id"],)).fetchone()
        _upsert_loop(con, "abandoned_session", s["id"], venture=s["venture"], project=s["project"],
                     session_id=s["id"],
                     description=f"Session '{(s['summary'] or '?')[:90]}' ended with a plan, no follow-up",
                     evidence=f"last msg: {(last['summary'] if last else '?')[:140]} | {last['raw_ref'] if last else ''}",
                     confidence=0.6, fired=fired)
    # 2. orphaned tasks (latest state per task file still pending/in_progress, session cold 48h+)
    for t in con.execute("""
            SELECT e.raw_ref, e.summary, e.venture, e.project, e.session_id, MAX(e.ts) ts
            FROM events e JOIN sessions s ON s.id = e.session_id
            WHERE e.kind='task' AND (e.summary LIKE '[pending]%' OR e.summary LIKE '[in_progress]%')
              AND s.ended_at < ? GROUP BY e.raw_ref""",
            (_iso(_now() - timedelta(hours=48)),)):
        _upsert_loop(con, "orphan_task", t["raw_ref"], venture=t["venture"], project=t["project"],
                     session_id=t["session_id"],
                     description=f"Task never finished: {t['summary'][:110]}",
                     evidence=f"{t['raw_ref']} | session {t['session_id'][:8]} cold 48h+",
                     confidence=0.8, fired=fired)
    # 3/4. uncommitted work + stale branches (live git state)
    for st in git_result.get("repo_states", []):
        old = [d for d in st["dirty"] if d["age_h"] >= 48]
        if old:
            _upsert_loop(con, "uncommitted_work", st["repo"], venture=st["venture"],
                         project=st["project"],
                         description=f"{len(old)} modified files uncommitted 48h+ in {st['project']}",
                         evidence=", ".join(d["path"] for d in old[:6]) + f" | {st['repo']}",
                         confidence=0.7, fired=fired)
        for b in st["stale_branches"]:
            _upsert_loop(con, "stale_branch", f"{st['repo']}#{b['branch']}", venture=st["venture"],
                         project=st["project"],
                         description=f"Branch {b['branch']} is {b['ahead']} ahead, idle {b['age_d']}d",
                         evidence=f"{st['repo']} {b['branch']}@{b['sha']}",
                         confidence=0.75, fired=fired)
    # 5. failed exits
    for s in con.execute("SELECT * FROM sessions WHERE outcome != 'shipped'"):
        last = con.execute(
            """SELECT kind, summary, raw_ref FROM events WHERE session_id=?
               AND kind IN ('error','tool_result','response') ORDER BY ts DESC LIMIT 1""",
            (s["id"],)).fetchone()
        if not last or last["kind"] != "error":
            continue
        later = con.execute(
            "SELECT 1 FROM sessions WHERE project=? AND started_at>? LIMIT 1",
            (s["project"], s["ended_at"])).fetchone()
        if later:
            continue
        _upsert_loop(con, "failed_exit", s["id"], venture=s["venture"], project=s["project"],
                     session_id=s["id"],
                     description=f"Session ended on an error, never revisited: {(last['summary'] or '')[:100]}",
                     evidence=last["raw_ref"] or "", confidence=0.7, fired=fired)
    # 6. planted TODOs still in HEAD
    for t in git_result.get("planted_todos", []):
        _upsert_loop(con, "planted_todo", f"{t['repo']}|{t['line'][:80]}", venture=t["venture"],
                     project=t["project"],
                     description=f"{t['marker']} planted and still in HEAD: {t['line'][:100]}",
                     evidence=f"{t['repo']}@{t['sha'][:8]}", confidence=0.5, fired=fired)
    # 7. stale in-progress notes
    for nt in vault_result.get("stale_notes", []):
        _upsert_loop(con, "stale_note", nt["path"], venture=nt["venture"], project="notes",
                     description=f"Note '{nt['name']}' in-progress but untouched {nt['age_d']}d",
                     evidence=nt["path"], confidence=0.6, fired=fired)
    # planted TODOs are ingested incrementally; verify open ones are still in HEAD
    from collectors import git as c_git
    for row in con.execute(
            "SELECT id, description, evidence FROM loops WHERE status='open' AND signal='planted_todo'").fetchall():
        repo = (row["evidence"] or "").split("@")[0]
        probe = (row["description"] or "").split(": ", 1)[-1][:80]
        if repo and probe:
            try:
                if c_git._git(repo, "grep", "-F", probe, "HEAD", "--", "."):
                    fired.add(row["id"])
                # else: line gone from HEAD -> allow auto-close below
            except Exception:
                fired.add(row["id"])  # can't verify: keep open
        else:
            fired.add(row["id"])
    recomputed.add("planted_todo")
    # auto-close loops that stopped firing, but only for signals recomputed this run
    closed = 0
    for row in con.execute("SELECT id, signal FROM loops WHERE status='open'").fetchall():
        if row["id"] not in fired and row["signal"] in recomputed:
            con.execute("UPDATE loops SET status='closed', closed_by='signal cleared', last_seen=? WHERE id=?",
                        (_iso(_now()), row["id"]))
            closed += 1
    open_n = con.execute("SELECT COUNT(*) c FROM loops WHERE status='open'").fetchone()["c"]
    return {"open": open_n, "closed_this_run": closed}


# ---------------------------------------------------------------- drift

def drift(con, week_offset: int = 0) -> dict:
    """Session minutes per venture for the ISO week starting Monday (offset weeks back)."""
    today = _now().date()
    monday = today - timedelta(days=today.weekday(), weeks=week_offset)
    start, end = monday.isoformat(), (monday + timedelta(days=7)).isoformat()
    rows = con.execute("""
        SELECT venture, SUM(duration_min) m, COUNT(*) n FROM sessions
        WHERE started_at >= ? AND started_at < ? GROUP BY venture ORDER BY m DESC""",
        (start, end)).fetchall()
    total = sum(r["m"] or 0 for r in rows) or 1
    out = []
    trap_min = rev_min = 0
    for r in rows:
        meta = ventures.VENTURES.get(r["venture"], ventures.VENTURES["unknown"])
        m = r["m"] or 0
        out.append({"venture": r["venture"], "label": meta["label"], "revenue": meta["revenue"],
                    "minutes": m, "pct": round(100 * m / total), "trap": meta["trap"],
                    "sessions": r["n"]})
        if meta["trap"]:
            trap_min += m
        elif r["venture"] != "unknown":
            rev_min += m
    return {"week_of": start, "rows": out, "total_min": total,
            "trap_min": trap_min, "rev_min": rev_min,
            "red_alert": trap_min > rev_min and trap_min > 60}
