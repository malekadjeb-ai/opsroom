"""Read-only notes + pipeline state for sitrep/console. Parses your dashboard note's
"## Live state" table by row-key substring (never column position), so it survives
reformatting. Degrades to a cached snapshot when the notes dir is unreadable.
Writes nothing outside the opsroom data dir.

Conventions it understands (all optional — see README):
  Live-state rows:  "Days to goal" · "Cash collected…" · any row containing "lead" ·
                    "Baseline…" · one row per venture matched by its live_prefix
  "## Today's one move" section → the console hero action
  Pipeline trackers: "## Totals" label lines · "## TOUCH LOG" tables (Target/Channel/
                    Status/Next) · any wide markdown table = a research target list
  A "*Decisions Log*.md" note with "- **YYYY-MM-DD** — …" bullets → per-venture DONE
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config, enrich, ventures

FM = re.compile(r"\A---\n(.*?)\n---", re.S)
FM_FIELD = re.compile(r"^(type|updated)\s*:\s*(.+)$", re.M)

_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?")
_AGED = re.compile(r"aged\s*~?\s*(\d+)\s*d", re.I)
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _cfg_path(key: str) -> Path | None:
    v = config.load()["paths"].get(key) or ""
    return Path(v).expanduser() if v else None


def dashboard_note() -> Path | None:
    return _cfg_path("dashboard_note")


def pipeline_dir() -> Path | None:
    return _cfg_path("pipeline_dir")


def cache_path() -> Path:
    return config.data_dir() / "state.json"


def _clean_cell(s: str) -> str:
    s = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", s)  # [[x]] / [[x|y]] -> display text
    s = s.replace("**", "").replace("`", "")
    return s.strip()


def _first_int(s: str):
    m = re.search(r"(\d+)", s or "")
    return int(m.group(1)) if m else None


def _money(s: str):
    m = _MONEY.search(s or "")
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    mult = {"k": 1_000, "m": 1_000_000}.get((m.group(2) or "").lower(), 1)
    return int(v * mult)


def _aged_days(raw: str, as_of: str, today=None):
    """Stated age + days elapsed since the note's as-of date (leads keep aging
    even when the note doesn't move)."""
    m = _AGED.search(raw or "")
    if not m:
        return None
    base = int(m.group(1))
    d = _DATE.search(as_of or "")
    if d:
        try:
            noted = datetime.strptime(d.group(1), "%Y-%m-%d").date()
            today = today or datetime.now().astimezone().date()
            base += max(0, (today - noted).days)
        except ValueError:
            pass
    return base


def _section(text: str, heading_re: str) -> str:
    """Body of a ## section, up to the next ## heading."""
    m = re.search(heading_re, text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"(?m)^##\s", rest)
    return rest[:nxt.start()] if nxt else rest


def parse_dashboard(text: str) -> dict:
    """Pure parser. Returns {'updated', 'rows': [{'key','raw','as_of'}], 'one_move', 'band'}."""
    out = {"updated": None, "rows": [], "one_move": None, "band": None}
    fm = FM.match(text)
    if fm:
        for k, v in FM_FIELD.findall(fm.group(1)):
            if k == "updated":
                out["updated"] = v.strip().strip("'\"")
    body = _section(text, r"(?im)^##\s+live\s+state\s*$")
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or all(re.fullmatch(r"[-: ]*", c) for c in cells):
            continue  # separator row
        key_cell = _clean_cell(cells[0])
        if key_cell.casefold() == "metric":
            continue  # header row
        out["rows"].append({
            "key": key_cell,
            "raw": _clean_cell(cells[1]) if len(cells) > 1 else "",
            "as_of": _clean_cell(cells[2]) if len(cells) > 2 else None,
        })
    move = _section(text, r"(?im)^##\s+today.?s\s+one\s+move\s*$").strip()
    if move:
        out["one_move"] = move.split("\n\n")[0].replace("\n", " ").strip()
    band = re.search(r"(?i)honest band:\s*([^\n.]+)", text)
    out["band"] = band.group(1).strip() if band else None
    return out


def live_find(rows, *needles):
    """First live row whose key contains any needle (casefolded substring)."""
    for row in rows:
        k = row["key"].casefold()
        if any(n in k for n in needles):
            return row
    return {}


def load_dashboard():
    """Locate + read + parse the dashboard note. Returns (parsed|None, error|None)."""
    note = dashboard_note()
    if not note:
        return None, "no dashboard_note configured (opsroom init)"
    root = note.parent
    try:
        os.scandir(str(root)).close()  # probe: rglob/read swallow PermissionError
    except PermissionError:
        return None, f"{root}: PermissionError (grant your terminal Full Disk Access)"
    except OSError as e:
        return None, f"{root}: {type(e).__name__}"
    try:
        parsed = parse_dashboard(note.read_text(errors="replace"))
    except (PermissionError, OSError) as e:
        return None, f"{note}: {type(e).__name__}"
    if not parsed["rows"]:
        return None, f"{note.name}: no '## Live state' table found"
    parsed["path"] = str(note)
    return parsed, None


def parse_md_tables(text: str, min_cols=4, max_rows=80):
    """Every markdown table with >= min_cols columns -> [{'headers': [...], 'rows': [dict]}].
    Rows whose cells are all empty (ignoring a numeric '#' column) are skipped."""
    tables, headers, rows = [], None, []

    def flush():
        nonlocal headers, rows
        if headers and rows:
            tables.append({"headers": headers, "rows": rows[:max_rows]})
        headers, rows = None, []

    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            flush()
            continue
        cells = [_clean_cell(c) for c in s.strip("|").split("|")]
        if all(re.fullmatch(r"[-: ]*", c) for c in cells):
            continue  # separator
        if headers is None:
            if len(cells) >= min_cols:
                headers = cells
            continue
        row = dict(zip(headers, cells))
        if any(v for k, v in row.items() if k not in ("#",) and v):
            rows.append(row)
    flush()
    return tables


def pipeline_status():
    """Per tracker markdown file: age, Totals lines, TOUCH LOG rows, research tables.
    Never raises; [] when no pipeline_dir configured."""
    out = []
    pd = pipeline_dir()
    if not pd:
        return out
    try:
        files = sorted(pd.glob("*.md"))
    except OSError:
        return out
    now = datetime.now(timezone.utc).timestamp()
    for f in files:
        try:
            age = max(0, int((now - f.stat().st_mtime) / 86400))
            text = f.read_text(errors="replace")
        except OSError:
            continue
        totals = {}
        for label, val in re.findall(r"([A-Za-z][A-Za-z /]+?):\s*([^·\n|]+)",
                                     _section(text, r"(?im)^##\s+totals\s*$")):
            totals[label.strip()] = val.strip()
        touches, rows = {}, []
        tl = _section(text, r"(?im)^##\s+touch\s+log\b.*$")
        for row in tl.splitlines():
            if not row.strip().startswith("|") or set(row.strip()) <= set("|-: "):
                continue
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if not cells or cells[0].casefold() in ("target", "metric"):
                continue
            for status in ("DRAFTED", "SENT", "REPLIED", "call sheet"):
                if status in row:
                    touches[status] = touches.get(status, 0) + 1
                    break
            rows.append({"target": cells[0],
                         "channel": cells[1] if len(cells) > 1 else "",
                         "status": cells[2] if len(cells) > 2 else "",
                         "next": cells[3] if len(cells) > 3 else ""})
        out.append({"name": f.stem, "path": str(f), "age_days": age,
                    "totals": totals, "touches": touches, "rows": rows,
                    "tables": parse_md_tables(text)})
    return out


def venture_history(text=None):
    """Decisions-log entries per venture: {venture: [{'date','text'}]}, newest first.
    Looks for any '*ecisions*og*.md' under the notes roots. Pass text for tests."""
    if text is None:
        found = None
        for root, _label in ventures.NOTES_ROOTS:
            try:
                hits = sorted(Path(root).rglob("*ecisions*og*.md"))
            except (PermissionError, OSError):
                continue
            if hits:
                found = hits[0]
                break
        if not found:
            return {}
        try:
            text = found.read_text(errors="replace")
        except (PermissionError, OSError):
            return {}
    hist = {}
    for m in re.finditer(r"(?ms)^- \*\*(\d{4}-\d{2}-\d{2})\*\*\s*[—-]\s*(.+?)(?=^\s*- \*\*\d{4}|\Z)",
                         text):
        date_s, body = m.group(1), " ".join(m.group(2).split())
        for v in ventures.attribute_text_all(body):
            hist.setdefault(v, []).append({"date": date_s, "text": body[:600]})
    return hist


def _venture_pipeline(key: str, meta: dict, pipelines):
    """The tracker file(s) belonging to a venture: name starts with its key, or matches
    its configured target_table."""
    mine = [p for p in pipelines if p["name"].startswith(key)]
    tt = meta.get("target_table")
    if tt:
        mine += [p for p in pipelines if p["name"] == tt and p not in mine]
    return mine


def next_actions(state):
    """Generated per-venture NEXT list from live pipeline state. Data first, then the
    venture's configured playbook lines. Generic rules:
      - a 'Blocking:' clause in the venture's live row becomes UNBLOCK FIRST
      - TOUCH LOG rows become send / follow-up / call actions
      - all-zero Totals gets called out
      - trap ventures are frozen by the operator rule"""
    acts = {}
    for v in state["ventures"]:
        key, a = v["key"], []
        if v["trap"]:
            acts[key] = ["FROZEN by operator rule — no building unless it produces cash "
                         "in-window or directly unblocks a revenue-track close"]
            continue
        live_row = state["venture_live"].get(key, {})
        m = re.search(r"Blocking:\s*([^|]+)", live_row.get("raw", ""))
        if m:
            a.append(f"UNBLOCK FIRST: {m.group(1).strip()} — nothing ships until this")
        meta = ventures.VENTURES.get(key, {})
        for p in _venture_pipeline(key, meta, state["pipelines"]):
            for r in p["rows"]:
                st = r["status"]
                if "REPLIED" in st:
                    a.append(f"HOT — {r['target']} replied: {r['next'] or 'move to a call today'}")
                elif "SENT" in st:
                    a.append(f"Follow-up → {r['target']}: {r['next'] or 'day-3 call'}")
                elif "DRAFTED" in st:
                    a.append(f"Send draft → {r['target']} (60-sec review), then day-3 call")
                elif "call" in st.lower():
                    a.append(f"Call {r['target']} — {r['next']}")
            t = p["totals"]
            if t and all(str(x).lstrip("$~ ").startswith("0") for x in t.values()):
                a.append(f"Tracker '{p['name']}' is all zeros — outreach has not started")
        if state["leads_n"] and key == state.get("leads_venture"):
            pos = 1 if (a and a[0].startswith("UNBLOCK FIRST")) else 0
            aged = f" (aged ~{state['leads_age']}d)" if state.get("leads_age") else ""
            a.insert(pos, f"Call the ~{state['leads_n']} open leads NEWEST FIRST"
                          f"{aged} — log every touch")
        # the operator's single top move (dashboard one-move) surfaces on every venture
        # it names, so the NOW hero and the venture's DO-NEXT never disagree.
        one_move = state.get("one_move")
        if one_move and key in ventures.attribute_text_all(one_move):
            pos = 1 if (a and a[0].startswith("UNBLOCK FIRST")) else 0
            a.insert(pos, f"▶ TOP MOVE: {one_move}")
        a += meta.get("playbook", [])
        acts[key] = a or ["No queued actions — check the tracker or add playbook lines in config"]
    return acts


def venture_rollup(con):
    """Every configured venture (revenue tracks first, then traps), merged with
    this-week effort, last activity, open loops, recent commits."""
    d = enrich.drift(con)
    week_min = {r["venture"]: int(r["minutes"]) for r in d["rows"]}
    last_sess = {r["venture"]: r["t"] for r in con.execute(
        "SELECT venture, MAX(started_at) t FROM sessions GROUP BY venture")}
    last_ev = {r["venture"]: r["t"] for r in con.execute(
        "SELECT venture, MAX(ts) t FROM events GROUP BY venture")}
    loops_n = {r["venture"]: r["c"] for r in con.execute(
        "SELECT venture, COUNT(*) c FROM loops WHERE status='open' GROUP BY venture")}
    out = []
    for key, meta in ventures.VENTURES.items():
        if key == "unknown":
            continue
        last = max(filter(None, (last_sess.get(key), last_ev.get(key))), default=None)
        commits = [dict(r) for r in con.execute(
            """SELECT ts, summary FROM events WHERE kind='commit' AND venture=?
               ORDER BY ts DESC LIMIT 3""", (key,))]
        top_loop = con.execute(
            """SELECT description, age_days FROM loops WHERE status='open' AND venture=?
               ORDER BY confidence*age_days DESC LIMIT 1""", (key,)).fetchone()
        out.append({"key": key, "label": meta["label"], "revenue": meta["revenue"],
                    "trap": meta["trap"], "track": meta.get("track"),
                    "week_min": week_min.get(key, 0), "last_activity": last,
                    "open_loops": loops_n.get(key, 0), "commits": commits,
                    "top_loop": dict(top_loop) if top_loop else None})
    out.sort(key=lambda v: (v["trap"], v["track"] or "Z", -v["week_min"]))
    return out


def db_enrichment(con):
    """Activity context from opsroom's own ledger."""
    day = datetime.now(timezone.utc).date().isoformat()
    sess = con.execute(
        """SELECT venture, COUNT(*) n, COALESCE(SUM(duration_min),0) m FROM sessions
           WHERE started_at >= ? GROUP BY venture ORDER BY m DESC""", (day,)).fetchall()
    open_loops = con.execute("SELECT COUNT(*) c FROM loops WHERE status='open'").fetchone()["c"]
    d = enrich.drift(con)
    trap_pct = round(100 * d["trap_min"] / d["total_min"]) if d["total_min"] else 0
    return {"sessions": [dict(s) for s in sess], "open_loops": open_loops,
            "trap_pct": trap_pct, "red_alert": d["red_alert"],
            "drift_rows": d["rows"], "week_of": d["week_of"]}


def build_state(con) -> dict:
    """Assemble notes + pipeline + DB state. Always returns a dict; never raises on
    notes loss — falls back to the last cached snapshot. Operator-facing dates are
    LOCAL (a goal deadline is a calendar day); DB queries stay UTC."""
    today = datetime.now().astimezone().date()
    parsed, err = load_dashboard()
    degraded, cached_at = [], None
    history = venture_history() if parsed else {}
    cache = cache_path()
    if parsed:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(
                {"cached_at": datetime.now(timezone.utc).isoformat(),
                 "dashboard": parsed, "history": history}))
            cache.chmod(0o600)
        except OSError:
            pass
    else:
        if err and "no dashboard_note configured" not in err:
            degraded.append(err)
        try:
            snap = json.loads(cache.read_text())
            parsed = snap.get("dashboard")
            history = snap.get("history", {})
            cached_at = snap.get("cached_at")
        except (OSError, ValueError):
            parsed = None
    rows = (parsed or {}).get("rows", [])
    deadline = ventures.DEADLINE
    days = (deadline - today).days if deadline else None
    note_days = _first_int(live_find(rows, "days to goal").get("raw", ""))
    leads_row = live_find(rows, "lead")
    cash_row = live_find(rows, "cash")
    rollup = venture_rollup(con)
    venture_live = {}
    for v in rollup:
        prefix = ventures.VENTURES.get(v["key"], {}).get("live_prefix", "")
        if prefix:
            venture_live[v["key"]] = live_find(rows, prefix.casefold())
    leads_venture = next(
        (v["key"] for v in rollup
         if ventures.VENTURES[v["key"]].get("live_prefix", "").casefold()
         and ventures.VENTURES[v["key"]]["live_prefix"].casefold() in leads_row.get("key", "").casefold()),
        next((v["key"] for v in rollup if not v["trap"] and v["track"] == "C"),
             next((v["key"] for v in rollup if not v["trap"]), None)))
    state = {
        "date": today.isoformat(),
        "days_to_goal": days,
        "goal_usd": ventures.GOAL_USD,
        "goal_label": ventures.GOAL_LABEL,
        "note_days_stale": days is not None and note_days is not None and note_days != days,
        "cash_raw": cash_row.get("raw"),
        "cash_usd": _money(cash_row.get("raw", "")),
        "leads_n": _first_int(leads_row.get("raw", "")),
        "leads_age": _aged_days(leads_row.get("raw", ""), leads_row.get("as_of", ""), today),
        "leads_venture": leads_venture,
        "live_rows": rows,
        "venture_live": venture_live,
        "baseline_raw": live_find(rows, "baseline").get("raw", ""),
        "one_move": (parsed or {}).get("one_move"),
        "band": (parsed or {}).get("band"),
        "dashboard_updated": (parsed or {}).get("updated"),
        "pipelines": pipeline_status(),
        "ventures": rollup,
        "history": history,
        "db": db_enrichment(con),
        "degraded": degraded,
        "cached": cached_at,
    }
    state["top_leak"] = _top_leak(state)
    state["next"] = next_actions(state)
    if not state["one_move"]:
        for key in ([leads_venture] if state["leads_n"] else []) + \
                   [v["key"] for v in rollup if not v["trap"]]:
            first = (state["next"].get(key) or [None])[0]
            if first and not first.startswith("No queued"):
                state["one_move"] = first
                break
        state["one_move"] = state["one_move"] or "Set a goal + dashboard note (opsroom init) to power this"
    return state


def _top_leak(state) -> str:
    if state["db"]["red_alert"]:
        return "trap-zone build time exceeds revenue-venture time this week"
    if (state["leads_age"] or 0) >= 7 and state["leads_n"]:
        return (f"~{state['leads_n']} open leads aged ~{state['leads_age']}d — "
                "paid-for money rotting uncalled")
    for key, row in state["venture_live"].items():
        m = re.search(r"Blocking:\s*([^|]+)", row.get("raw", ""))
        if m:
            return f"{ventures.VENTURES[key]['label']} blocked: {m.group(1).strip()}"
    stale = [p for p in state["pipelines"] if p["age_days"] >= 3]
    if stale:
        worst = max(stale, key=lambda p: p["age_days"])
        return f"pipeline tracker '{worst['name']}' untouched for {worst['age_days']}d"
    return "none detected"
