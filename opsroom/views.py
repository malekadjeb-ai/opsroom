"""Terminal views + sitrep + operator-console dashboard + daily writeback (append-only)."""
import os
import re
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, dashboard, enrich, redact, state, ventures

BAR = "█"


def _bar(pct, width=18):
    return BAR * max(1, round(width * pct / 100)) if pct else ""


def _day_bounds(offset=0):
    d = datetime.now(timezone.utc).date() - timedelta(days=offset)
    return d.isoformat(), (d + timedelta(days=1)).isoformat()


def today(con, offset=0):
    start, end = _day_bounds(offset)
    print(f"\nACTIVITY · {start}\n")
    sessions = con.execute(
        """SELECT * FROM sessions WHERE ended_at >= ? AND started_at < ?
           ORDER BY started_at""", (start, end)).fetchall()
    if not sessions:
        print("  no agent sessions recorded")
    for s in sessions:
        mins = int(s["duration_min"] or 0)
        agent = enrich.AGENT_LABELS.get(s["source"], s["source"])
        print(f"  {s['started_at'][11:16]}  {agent:<7} [{s['venture']:<13}] {mins:>4}m  "
              f"{s['outcome'] or '?':<9} {(s['summary'] or '(no prompt)')[:64]}")
    commits = con.execute(
        """SELECT ts, venture, summary FROM events WHERE kind='commit' AND ts >= ? AND ts < ?
           ORDER BY ts""", (start, end)).fetchall()
    if commits:
        print(f"\n  COMMITS ({len(commits)})")
        for c in commits:
            print(f"  {c['ts'][11:16]}  [{c['venture']:<13}] {c['summary'][:75]}")
    other = con.execute(
        """SELECT source, COUNT(*) c FROM events WHERE ts >= ? AND ts < ?
           AND source NOT IN ('cli','git') GROUP BY source""", (start, end)).fetchall()
    for o in other:
        print(f"\n  {o['source']}: {o['c']} events")
    print()


def week(con):
    print("\nWEEK VIEW")
    for off in range(6, -1, -1):
        start, end = _day_bounds(off)
        r = con.execute(
            """SELECT COALESCE(SUM(duration_min),0) m, COUNT(*) n FROM sessions
               WHERE started_at >= ? AND started_at < ?""", (start, end)).fetchone()
        c = con.execute(
            "SELECT COUNT(*) c FROM events WHERE kind='commit' AND ts >= ? AND ts < ?",
            (start, end)).fetchone()["c"]
        h, m = divmod(int(r["m"]), 60)
        print(f"  {start}  {r['n']:>3} sessions  {h:>2}h {m:02d}m  {c:>3} commits  "
              f"{_bar(min(100, r['m'] / 6), 20)}")
    by_agent(con)
    drift(con)


def by_agent(con):
    agents = enrich.by_agent(con)
    if not agents:
        print()
        return
    print("\n  BY AGENT (7d)")
    for a in agents:
        if a["unit"] == "time":
            h, m = divmod(int(a["minutes"]), 60)
            vol = f"{h:>2}h {m:02d}m"
        else:
            vol = f"{int(a['minutes']):>3} msgs"
        print(f"  {a['agent']:<13} {a['sessions']:>3} sessions  {vol:>8}  "
              f"top: {a['top_venture']:<13} last {a['last_seen']}")
    print()


def loops(con, show_all=False):
    where = "" if show_all else "AND age_days >= 0"
    rows = con.execute(
        f"""SELECT * FROM loops WHERE status='open' {where}
            ORDER BY confidence*age_days DESC LIMIT 40""").fetchall()
    aging = sum(1 for r in rows if (r["age_days"] or 0) >= 7)
    print(f"\nOPEN LOOPS ({len(rows)} open, {aging} aging 7d+)\n")
    for r in rows:
        sev = "HIGH" if (r["age_days"] or 0) >= 7 or r["confidence"] >= 0.75 else "MED"
        print(f"[{sev} · {r['age_days']}d · {r['signal']}] {r['venture']} · {r['project']}")
        print(f"  {r['description']}")
        print(f"  Evidence: {r['evidence'][:150]}")
        print(f"  id: {r['id']}   (dismiss: opsroom loops --dismiss {r['id'][:8]})\n")
    if not rows:
        print("  none detected\n")


def dismiss_loop(con, prefix):
    cur = con.execute("UPDATE loops SET status='dismissed' WHERE id LIKE ? AND status='open'",
                      (prefix + "%",))
    print(f"dismissed {cur.rowcount} loop(s)")


def drift(con, week_offset=0):
    d = enrich.drift(con, week_offset)
    print(f"\nEFFORT vs REVENUE · week of {d['week_of']}\n")
    for r in d["rows"]:
        h, m = divmod(int(r["minutes"]), 60)
        tag = " [trap]" if r["trap"] else ""
        print(f"  {r['label']:<24}{tag:<7} {h:>3}h {m:02d}m  {_bar(r['pct'])}  {r['pct']}%")
    if not d["rows"]:
        print("  no sessions this week")
    th, tm = divmod(int(d["trap_min"]), 60)
    share = round(100 * d["trap_min"] / d["total_min"]) if d["total_min"] else 0
    print(f"\n  build-time in $0-revenue ventures: {th}h {tm:02d}m ({share}%)")
    if d["red_alert"]:
        print("  ⚠ RED ALERT: trap-zone time exceeds revenue-venture time this week.")
    if ventures.DEADLINE:
        days = (ventures.DEADLINE - datetime.now().astimezone().date()).days
        lead = next((v for v in ventures.VENTURES.items()
                     if v[1].get("track") == "A" and not v[1]["trap"]), None)
        if lead:
            key, meta = lead
            r = next((r for r in d["rows"] if r["venture"] == key), None)
            bm = int(r["minutes"]) if r else 0
            print(f"  {meta['label']} got {bm // 60}h {bm % 60:02d}m with the "
                  f"{ventures.DEADLINE} deadline {days}d out.")
    print()


def venture_view(con, name):
    key = ventures.attribute_text(name) if name not in ventures.VENTURES else name
    print(f"\nVENTURE · {ventures.VENTURES.get(key, {}).get('label', key)}\n")
    for s in con.execute(
            """SELECT * FROM sessions WHERE venture=? ORDER BY started_at DESC LIMIT 15""", (key,)):
        print(f"  {s['started_at'][:16]}  {int(s['duration_min'] or 0):>4}m  "
              f"{s['outcome'] or '?':<9} {(s['summary'] or '')[:65]}")
    n = con.execute("SELECT COUNT(*) c FROM loops WHERE venture=? AND status='open'", (key,)).fetchone()["c"]
    print(f"\n  open loops: {n}  (opsroom loops for detail)\n")


def _fts_query(q: str) -> str:
    """Wrap user words as quoted FTS5 tokens so query punctuation (AND, quotes, parens,
    apostrophes) is treated as literal text, never as FTS operators that raise."""
    words = re.findall(r"\w+", q)
    return " ".join(f'"{w}"' for w in words)


def search(con, query):
    fts = _fts_query(query)
    rows = []
    if fts:
        try:
            rows = con.execute(
                """SELECT e.ts, e.venture, e.kind, e.summary, e.raw_ref FROM events_fts f
                   JOIN events e ON e.rowid = f.rowid WHERE events_fts MATCH ?
                   ORDER BY e.ts DESC LIMIT 25""", (fts,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    print(f"\nSEARCH '{query}' · {len(rows)} hits\n")
    for r in rows:
        print(f"  {r['ts'][:16]}  [{r['venture']:<13}] {r['kind']:<11} {(r['summary'] or '')[:70]}")
        print(f"     ↳ {r['raw_ref']}")
    print()


def _sitrep_lines(st):
    """The operator SITREP lines. Shape is the product's signature."""
    goal = st["goal_label"]
    if st["days_to_goal"] is not None:
        days_note = " (dashboard note stale)" if st["note_days_stale"] else ""
        line1 = f"- DATE / DAYS TO GOAL: {st['date']} / {st['days_to_goal']}d{days_note}"
    else:
        line1 = f"- DATE: {st['date']} (no goal deadline set — opsroom init)"
    cash = st["cash_raw"] or "n/a — no cash row in the dashboard note"
    if st["leads_n"] is not None:
        leads = f"~{st['leads_n']}" + (f" aged ~{st['leads_age']}d" if st.get("leads_age") else "")
    else:
        leads = "n/a — no leads row in the dashboard note"
    pipe_bits = []
    for key, row in st["venture_live"].items():
        if row.get("raw"):
            pipe_bits.append(f"{ventures.VENTURES[key]['label']}: {row['raw'].split('. ')[0][:90]}")
    for p in st["pipelines"]:
        if p["touches"]:
            pipe_bits.append(", ".join(f"{n} {k.lower()}" for k, n in sorted(p["touches"].items())))
    pipeline = " · ".join(pipe_bits) or "n/a — no venture live rows / trackers"
    return [
        line1,
        f"- CASH COLLECTED vs {goal}: {cash}",
        f"- OPEN LEADS: {leads}",
        f"- LIVE PIPELINE: {pipeline[:220]}",
        f"- TOP LEAK RIGHT NOW: {st['top_leak']}",
        f"- SINGLE HIGHEST CASH ACTION TODAY: {st['one_move']}",
    ]


def _source_health(st):
    if st["degraded"] and st["cached"]:
        return f"notes DEGRADED ({st['degraded'][0]}) — showing CACHED snapshot {st['cached'][:16]}"
    if st["degraded"]:
        return f"notes DEGRADED ({st['degraded'][0]}) — no cache, DB-only"
    if st["dashboard_updated"]:
        return f"notes ok (dashboard updated {st['dashboard_updated']})"
    return "no dashboard note configured — DB-only (opsroom init to add one)"


def _chmod_note(target: Path) -> None:
    """Daily notes can carry ledger-derived text; keep them owner-only like the DB."""
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass


def sitrep(con, write=False):
    st = state.build_state(con)
    lines = _sitrep_lines(st)
    print(f"\nSITREP · {st['date']}\n")
    for ln in lines:
        print(ln)
    dbi = st["db"]
    print(f"\n  today: " + (", ".join(
        f"{s['venture']} {s['n']}x/{int(s['m'])}m" for s in dbi["sessions"]) or "no sessions"))
    print(f"  open loops: {dbi['open_loops']} · trap-zone share this week: {dbi['trap_pct']}%")
    for p in st["pipelines"]:
        if p["age_days"] >= 3:
            print(f"  ⚠ pipeline '{p['name']}' untouched {p['age_days']}d")
    print(f"  SOURCES: {_source_health(st)}\n")
    if write:
        target = Path(config.load()["paths"]["daily_dir"]).expanduser() / f"{st['date']}.md"
        stamp = datetime.now(timezone.utc).isoformat()[:16]
        block = (f"\n## SITREP · {st['date']} (opsroom sitrep, appended {stamp}Z)\n\n"
                 + "\n".join(lines) + "\n")
        try:
            block, _ = redact.redact(block)
        except Exception as e:
            print(f"REDACTION FAILED ({e}) — write dropped, nothing appended")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a") as fh:
            fh.write(block)
        _chmod_note(target)
        print(f"appended SITREP to {target}")


def dash(con, out_path=None):
    out = Path(out_path or config.data_dir() / "console.html")
    st = state.build_state(con)
    d = enrich.drift(con)
    lps = con.execute("""SELECT * FROM loops WHERE status='open'
                         ORDER BY confidence*age_days DESC LIMIT 30""").fetchall()
    sess = con.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 25").fetchall()
    agents = enrich.by_agent(con)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dashboard.render(st, d, lps, sess, agents))
    out.chmod(0o600)  # may carry notes-derived text; same posture as the DB
    print(f"console written: {out}")
    return str(out)


def daily_writeback(con, dry_run=True):
    """Append-only, dated ledger block into the operator daily note (daily_dir/<date>.md).
    Notes roots are never written — read-only rail."""
    today_s = datetime.now().astimezone().date().isoformat()
    target = Path(config.load()["paths"]["daily_dir"]).expanduser() / f"{today_s}.md"
    d = enrich.drift(con)
    start, end = _day_bounds()
    sess = con.execute("""SELECT venture, COUNT(*) n, SUM(duration_min) m FROM sessions
                          WHERE started_at >= ? AND started_at < ? GROUP BY venture""",
                       (start, end)).fetchall()
    open_loops = con.execute("SELECT COUNT(*) c FROM loops WHERE status='open'").fetchone()["c"]
    lines = [f"\n## Ledger · {today_s} (appended {datetime.now(timezone.utc).isoformat()[:16]}Z)\n"]
    for s in sess:
        lines.append(f"- {s['venture']}: {s['n']} sessions, {int(s['m'] or 0)}m")
    share = round(100 * d['trap_min'] / d['total_min']) if d['total_min'] else 0
    lines.append(f"- open loops: {open_loops}; trap-zone share this week: {share}%")
    try:
        block, _ = redact.redact(block)
    except Exception as e:
        print(f"REDACTION FAILED ({e}) — write dropped, nothing appended")
        return
    if dry_run:
        print(f"--- would APPEND to {target} ---{block}--- end (append-only, no rewrite) ---")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a") as fh:
            fh.write(block)
        _chmod_note(target)
        print(f"appended ledger to {target}")
