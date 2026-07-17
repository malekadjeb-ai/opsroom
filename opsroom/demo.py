"""`opsroom demo` — a fictional three-venture portfolio, fully loaded, in one command.
Everything lands under <data>/demo (config, notes, trackers, DB, console); your real
config and ledger are untouched. All names, numbers and phone numbers are invented
(555 exchange)."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

DASHBOARD_NOTE = """---
title: Q3 Sprint Dashboard
type: dashboard
updated: {today}
---

# Q3 $50K Sprint

## Live state
| Metric | Value | As of |
|---|---|---|
| Days to goal | {days} | {today} |
| Cash collected vs $50K | **$8,250 collected** | {today} |
| Meridian pipeline | 2 proposals out ($12K + $18K). Blocking: case-study PDF | {today} |
| Shopkit pipeline | 41 licenses sold this month | {today} |
| Open leads | ~14 unanswered quote requests, aged ~6 days | {lead_asof} |
| Baseline revenue | Shopkit ~$2.1K/mo recurring | {today} |

## Today's one move
Finish the Meridian case-study PDF and send both proposals — $30K of pipeline is waiting on one document.

Honest band: realistic $28-39K, stretch $55K.
"""

MERIDIAN = """# Meridian Targets — fictional demo data

| # | Company | Type | Location | Size evidence | Phone / Website | Decision-maker | Pain hypothesis |
|---|---------|------|----------|---------------|-----------------|----------------|-----------------|
| 1 | Cobalt Logistics | 3PL warehouse | Reno, NV | 40 staff per site | (555) 201-4410 / cobaltlogistics.example | Dana Reyes, COO | Manual pick-sheet reconciliation eats 2 FTEs |
| 2 | Harbor & Pine | E-commerce furniture | Portland, OR | 15 staff, 2 warehouses | (555) 315-8822 / harborpine.example | Sam Okafor, founder | Returns processing is spreadsheet chaos |
| 3 | Brightline Dental Group | 6-clinic dental group | Boise, ID | 60 staff | (555) 440-9031 / brightlinedental.example | Dr. Lee Nguyen | No-show rate 18%, no automated recalls |
| 4 | Summit Fabrication | Metal shop | Ogden, UT | 25 staff | (555) 662-1177 / summitfab.example | Chris Vale, owner | Paper job tickets to invoices = 9-day lag |
| 5 | Foxglove Catering | Corporate catering | Sacramento, CA | 30 staff | (555) 774-2065 / foxglovecatering.example | Priya Shah, GM | Quote turnaround loses weekend events |
| 6 | Kestrel Property Co | Property manager | Spokane, WA | 300 doors | (555) 883-4409 / kestrelpm.example | Jordan Blake | Maintenance-request triage is all email |

## TOUCH LOG — campaign live
| Target | Channel | Status | Draft/next |
|---|---|---|---|
| Cobalt Logistics (Dana Reyes) | email | DRAFTED | send, then day-3 call |
| Harbor & Pine (Sam Okafor) | email | DRAFTED | send, then day-3 call |
| Brightline Dental | email | SENT {sent} | day-3 follow-up call |
| Summit Fabrication | PHONE | on call sheet | (555) 662-1177, ask Chris Vale |
| Foxglove Catering | PHONE | on call sheet | (555) 774-2065, ask Priya |
"""

DETAILPRO = """# DetailPro Lead Recovery

## Totals
- Contacted: 3/14
- Quoted: $1,180
- Booked: $640
- Collected: $640
"""

DECISIONS = """# Decisions Log

- **{d1}** — Sent Brightline proposal ($18K tier) after the discovery call; meridian pipeline now two live proposals — *why:* strike while the no-show pain is fresh — *affects:* meridian.
- **{d2}** — Shipped Shopkit 2.3 (bulk export + Stripe tax); 41 licenses this month, churn flat — *affects:* shopkit.
- **{d3}** — Found 14 unanswered quote requests in the detailpro inbox; started the recovery blitz, 3 contacted day one — *affects:* detailpro.
- **{d4}** — Paused blog-engine rewrite; it was eating revenue hours (trap) — *affects:* blog-engine.
"""

CONFIG = """[goal]
amount = 50000
deadline = "{deadline}"
label = "Q3 $50K sprint"

[paths]
scan_roots = []
notes_roots = ["{notes}"]
dashboard_note = "{notes}/Q3 Sprint Dashboard.md"
pipeline_dir = "{pipes}"

[links]
mail_drafts = "https://mail.google.com/mail/u/0/#drafts"
leads = ""

[[venture]]
key = "meridian"
label = "Meridian Consulting"
revenue = "B2B ops automation — $12-18K projects"
track = "A"
trap = false
live_prefix = "meridian"
target_table = "meridian-targets"
playbook = ["Always propose the 3-tier ladder; anchor on the outcome, not hours"]
offer = "The 2-week ops sprint is $12,000 flat — scoped up front, no retainers, you keep everything."
draft_style = "b2b"

[[venture]]
key = "shopkit"
label = "Shopkit"
revenue = "plugin licenses — $49/mo"
track = "B"
trap = false
live_prefix = "shopkit"

[[venture]]
key = "detailpro"
label = "DetailPro"
revenue = "local service — daily cash"
track = "C"
trap = false
live_prefix = "open leads"
offer = "Full details start at $249, interiors at $189 — I come to you, nothing to drop off."
draft_style = "service"

[[venture]]
key = "blog-engine"
label = "Blog Engine"
revenue = "$0 rewrite"
trap = true

[[venture]]
key = "sideproject-x"
label = "Side Project X"
revenue = "$0 experiment"
trap = true
"""


def run():
    from . import config
    demo_root = config.data_dir() / "demo"
    os.environ["OPSROOM_CONFIG_DIR"] = str(demo_root / "config")
    os.environ["OPSROOM_DATA_DIR"] = str(demo_root / "data")
    notes = demo_root / "notes"
    pipes = demo_root / "pipelines"
    for d in (demo_root / "config", demo_root / "data", notes, pipes):
        d.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    today = now.date()
    deadline = today + timedelta(days=23)
    (demo_root / "config" / "config.toml").write_text(
        CONFIG.format(deadline=deadline.isoformat(), notes=notes, pipes=pipes))
    (notes / "Q3 Sprint Dashboard.md").write_text(DASHBOARD_NOTE.format(
        today=today.isoformat(), days=(deadline - today).days,
        lead_asof=(today - timedelta(days=2)).isoformat()))
    (notes / "Decisions Log.md").write_text(DECISIONS.format(
        d1=(today - timedelta(days=1)).isoformat(), d2=(today - timedelta(days=2)).isoformat(),
        d3=(today - timedelta(days=3)).isoformat(), d4=(today - timedelta(days=6)).isoformat()))
    (pipes / "meridian-targets.md").write_text(
        MERIDIAN.format(sent=(today - timedelta(days=1)).strftime("%m-%d")))
    (pipes / "detailpro-leads.md").write_text(DETAILPRO)

    from . import config as cfg, db, ventures
    cfg.load(force=True)
    ventures.refresh()
    db.DB_DIR = cfg.data_dir()
    db.DB_PATH = db.DB_DIR / "activity.db"
    con = db.connect()

    def sess(i, venture, hours_ago, mins, outcome, summary, source="cli"):
        start = now - timedelta(hours=hours_ago)
        con.execute("""INSERT OR REPLACE INTO sessions
            (id, source, started_at, ended_at, duration_min, venture, outcome, summary)
            VALUES (?,?,?,?,?,?,?,?)""",
            (f"demo-{i}", source, start.isoformat(), (start + timedelta(minutes=mins)).isoformat(),
             mins, venture, outcome, summary))

    sess(1, "meridian", 3, 85, "shipped", "Drafted Cobalt + Harbor & Pine openers")
    sess(2, "meridian", 26, 50, "shipped", "Brightline proposal: 3-tier ladder, ROI math")
    sess(3, "shopkit", 30, 65, "shipped", "Shopkit 2.3: bulk export + Stripe tax")
    sess(4, "detailpro", 8, 25, "shipped", "Called 3 stale quote requests, 1 booked")
    sess(5, "blog-engine", 50, 190, "wip", "Rewrote the templating layer again")
    sess(6, "sideproject-x", 75, 120, "wip", "Prototype #4 of the recommender")
    sess(7, "shopkit", 12, 45, "shipped", "Codex: fixed the Stripe webhook retry bug", "codex")
    sess(8, "blog-engine", 55, 140, "wip", "Codex: markdown parser rewrite, round 2", "codex")
    for i, (hrs, actor, kind, text) in enumerate([
            (20, "you", "prompt", "Pricing strategy: is $49/mo leaving money on the table for Shopkit?"),
            (20, "chatgpt", "response", "Given 41 licenses and flat churn, test a $79 pro tier before touching base pricing…"),
            (44, "you", "prompt", "Rewrite the Brightline proposal executive summary, punchier"),
            (44, "chatgpt", "response", "Draft: 'Brightline loses ~$210K/yr to no-shows. This proposal removes 60% of that…'")]):
        con.execute("""INSERT OR REPLACE INTO events
            (id, ts, source, session_id, venture, kind, actor, summary)
            VALUES (?,?,?,?,?,?,?,?)""",
            (f"demo-chat{i}", (now - timedelta(hours=hrs, minutes=i)).isoformat(), "chat",
             f"chatgpt:demo-{hrs}", "shopkit" if hrs == 20 else "meridian", kind, actor, text))
    for i, (v, s) in enumerate([("meridian", "add case-study outline"),
                                ("shopkit", "v2.3: bulk export + tax"),
                                ("blog-engine", "wip: new templating layer")]):
        con.execute("""INSERT OR REPLACE INTO events (id, ts, source, venture, kind, actor, summary)
                       VALUES (?,?,?,?,?,?,?)""",
                    (f"demo-c{i}", (now - timedelta(hours=6 + i * 20)).isoformat(),
                     "git", v, "commit", "you", s))
    con.execute("""INSERT OR REPLACE INTO loops
        (id, opened_at, venture, project, description, evidence, signal, confidence, age_days, status)
        VALUES ('demo-l1', ?, 'meridian', 'proposals',
        'Case-study PDF blocking two live proposals ($30K)', 'dashboard note: Blocking: case-study PDF',
        'plan_language', 0.9, 4, 'open')""", ((now - timedelta(days=4)).isoformat(),))
    con.execute("""INSERT OR REPLACE INTO loops
        (id, opened_at, venture, project, description, evidence, signal, confidence, age_days, status)
        VALUES ('demo-l2', ?, 'blog-engine', 'rewrite',
        'Templating rewrite open 12 days with zero revenue attached', '190m session, wip outcome',
        'stale_branch', 0.7, 12, 'open')""", ((now - timedelta(days=12)).isoformat(),))
    con.commit()

    from . import state, views
    import importlib
    out = views.dash(con)
    con.close()
    print(f"\ndemo portfolio: {demo_root}")
    print("This is FICTIONAL data (555 numbers, .example domains). Your real config/ledger untouched.")
    print("Reset: delete that folder. Set up your own: opsroom init")
    import subprocess, sys
    opener = {"darwin": "open", "linux": "xdg-open"}.get(sys.platform)
    if opener and not os.environ.get("OPSROOM_NO_OPEN"):
        subprocess.run([opener, out], check=False)
    return 0
