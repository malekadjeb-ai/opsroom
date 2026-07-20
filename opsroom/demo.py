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


DEMO_PORT = 7339  # never the real console's 7337: a demo must not shadow your ledger


def run(serve_console: bool = True):
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

    # ---- the operator ledger: the served console's source of truth for money,
    # leads, replies and follow-ups. Without this the live demo reads $0 of $50K.
    from . import inbox, ops
    oc = ops.connect()
    if not ops.cash_entries(oc):  # idempotent: a demo re-run doesn't double the money
        ops.log_cash(oc, 5000, "meridian", "Meridian sprint deposit — Brightline")
        ops.log_cash(oc, 2610, "shopkit", "41 license renewals")
        ops.log_cash(oc, 640, "detailpro", "2 details collected")
        ops.log_spend(oc, 420, "shopkit", "Stripe fees + hosting")
        ops.log_spend(oc, 180, "meridian", "prospect-list data")
        quoted_id = None
        for name, phone, svc, note in [
                ("Rowan Marsh", "5550100231", "full detail", "asked for a Saturday slot"),
                ("Casey Ito", "5550100544", "interior", "quote sent, no answer yet"),
                ("Jules Barton", "5550100712", "full detail", "came in from the website form"),
                ("Avery Chen", "5550100903", "ceramic add-on", "wants the price by text"),
                ("Marlowe Diaz", "5550100377", "interior", "missed call yesterday")]:
            lid = ops.add_lead(oc, name, phone, svc, note, venture="detailpro")
            if name == "Casey Ito":
                quoted_id = lid
        if quoted_id:
            ops.touch_lead(oc, quoted_id, "quoted", 380, "held the $189 interior price")
        fid = ops.log_touch(oc, "meridian", "Summit Fabrication (Chris Vale)",
                            "called", "left a voicemail with Chris")
        if fid:
            oc.execute("UPDATE followups SET due=? WHERE id=?",
                       (today.isoformat(), fid))  # due TODAY: the cadence engine has teeth
            oc.commit()
        inbox.merge_replies(oc, {"replies": [{
            "from_name": "Dana Reyes", "from_email": "dana@cobaltlogistics.example",
            "subject": "Re: the 2-week ops sprint", "date": today.isoformat(),
            "snippet": "This looks interesting — what exactly would the first two weeks cover?",
            "venture": "meridian", "msg_id": "demo-reply-1"}]})
        ops.kv_set(oc, "missed_calls", "2")
        ops.capture(oc, "Shopkit pro tier: test $79/mo before touching base pricing")

        # ---- a leads ledger worth a WORKSPACE (/leads): more rows, every status,
        # believable ages — so filters, sorts and the aged view have teeth
        aged = []
        for name, phone, svc, note, days_old in [
                ("Sasha Whitfield", "5550101201", "full detail", "wants the ceramic bundle", 9),
                ("Robin Falco", "5550101322", "interior", "asked twice about Saturday", 8),
                ("Emerson Quill", "5550101488", "full detail", "from the referral card", 6),
                ("Devon Pratt", "5550101550", "ceramic add-on", "price-shopping, warm", 5),
                ("Lennox Vega", "5550101673", "interior", "voicemail left", 3),
                ("Harper Stone", "5550101744", "full detail", "booked once before", 2)]:
            lid = ops.add_lead(oc, name, phone, svc, note, venture="detailpro")
            aged.append((lid, days_old))
        won1 = ops.add_lead(oc, "Micah Reyes", "5550101819", "full detail",
                            "repeat customer", venture="detailpro")
        # won directly: their $249 is already inside the "2 details collected"
        # cash entry above — touch_lead would double-count it
        oc.execute("UPDATE leads SET status='won', collected=249, last_touch=? WHERE id=?",
                   (now.isoformat(), won1))
        lost1 = ops.add_lead(oc, "Perry Nolan", "5550101930", "interior",
                             "went with a cheaper quote", venture="detailpro")
        ops.touch_lead(oc, lost1, "lost")
        for lid, days_old in aged:  # backdate so the aged sort shows real decay
            back = (now - timedelta(days=days_old)).isoformat()
            oc.execute("UPDATE leads SET added=?, last_touch=NULL WHERE id=?", (back, lid))
        oc.commit()

        # ---- the OPERATOR LOOP, pre-loaded: a finished agent run whose output
        # became pending proposals. The provenance link opens this very log.
        from . import dispatch as _dispatch, proposals
        ddir = config.data_dir() / "dispatch"
        ddir.mkdir(parents=True, exist_ok=True)
        ddir.chmod(0o700)
        ts = (now - timedelta(minutes=18)).strftime("%Y%m%d-%H%M%S-%f")
        brief = ("# DISPATCH — do this now\n\nTASK: Work the DetailPro quote backlog\n"
                 "VENTURE: DetailPro\n\n(demo brief — fictional)\n")
        log = ("read the brief. Calling the quote backlog…\n"
               "- Casey Ito picked up: interior confirmed, PAID $380 on the card.\n"
               "- Summit Fabrication: Chris asked for a written quote by Thursday.\n"
               "- Two aged quotes still unanswered — a text blast is the next move.\n"
               "Proposing results:\n"
               '```opsroom\n{"propose": "cash", "amount": 380, "venture": "detailpro",'
               ' "what": "Casey Ito interior — collected on card"}\n```\n'
               '```opsroom\n{"propose": "followup", "target": "Summit Fabrication",'
               ' "due": "+2d", "venture": "meridian", "note": "written quote by Thursday"}\n```\n'
               '```opsroom\n{"propose": "dispatch", "task": "Text the two aged interior'
               ' quotes the $189 price with a Saturday slot", "venture": "detailpro"}\n```\n')
        for fname, text in ((f"{ts}-brief.md", brief), (f"{ts}.log", log)):
            p = ddir / fname
            p.write_text(text)
            p.chmod(0o600)
        proposals.harvest(oc, ts)  # the real path: parse → validate → stage pending

        # ---- THE ADVISOR, pre-loaded: an autonomous briefing the console "thought
        # up" before you opened it. Same real register→harvest path.
        from . import counsel
        ts2 = (now - timedelta(minutes=9)).strftime("%Y%m%d-%H%M%S-%f")
        brief2 = ("# DISPATCH — do this now\n\nTASK: " + counsel.ADVISE_TASK
                  + "\n\n(demo brief — fictional)\n")
        log2 = ("reading the board…\n"
                "```counsel\n"
                "## Verdict\n"
                "Cash is **on pace** ($8,250 of $50K) but two leaks are compounding:\n"
                "the $30K Meridian pipeline is stuck behind one PDF, and 6 DetailPro\n"
                "quotes are aging past day 7 — quote-to-close falls ~40% after that.\n"
                "## Plays beyond the queue\n"
                "1. Bundle the case-study PDF from the Brightline discovery notes — 90\n"
                "minutes unblocks $30K of proposals.\n"
                "2. Text-blast the 6 aged DetailPro quotes a Saturday slot at the $189\n"
                "interior price — recovered quotes beat new leads on cost.\n"
                "3. Shopkit's 41 licenses are churn-flat: a $79 pro tier test this week\n"
                "rides the renewal cycle instead of waiting for next month.\n"
                "```\n"
                "```counsel-plan\n"
                '{"steps": [\n'
                '  {"task": "Draft the Meridian case-study PDF from the Brightline notes", "venture": "meridian", "why": "unblocks $30K of live proposals"},\n'
                '  {"task": "Text the 6 aged DetailPro quotes a Saturday slot at $189", "venture": "detailpro", "why": "quotes decay hard after day 7"},\n'
                '  {"task": "Spec the Shopkit $79 pro tier test", "venture": "shopkit", "why": "ride this month\'s renewal cycle"}\n'
                "]}\n"
                "```\n"
                '```opsroom\n{"propose": "followup", "target": "Brightline Dental",'
                ' "due": "+1d", "venture": "meridian", "note": "proposal follow-through'
                ' while the discovery call is fresh"}\n```\n')
        for fname, text in ((f"{ts2}-brief.md", brief2), (f"{ts2}.log", log2)):
            p = ddir / fname
            p.write_text(text)
            p.chmod(0o600)
        counsel.register(oc, ts2, "advise", "")
        counsel.harvest(oc, ts2)
        proposals.harvest(oc, ts2)
    oc.close()

    from . import views
    out = views.dash(con)  # the static snapshot still lands next to the live console
    con.close()
    print(f"\ndemo portfolio: {demo_root}")
    print("This is FICTIONAL data (555 numbers, .example domains). Your real config/ledger untouched.")
    print("Reset: delete that folder. Set up your own: opsroom init")
    if serve_console and not os.environ.get("OPSROOM_NO_SERVE"):
        # the product IS the live console — buttons, ledgers, dispatch — not a
        # static snapshot. Serve the seeded portfolio.
        from . import serve as srv
        open_b = not os.environ.get("OPSROOM_NO_OPEN")
        try:
            srv.serve(port=DEMO_PORT, open_browser=open_b)
        except OSError:
            srv.serve(port=0, open_browser=open_b)  # 7339 busy: take any free port
        return 0
    import subprocess, sys
    opener = {"darwin": "open", "linux": "xdg-open"}.get(sys.platform)
    if opener and not os.environ.get("OPSROOM_NO_OPEN"):
        subprocess.run([opener, out], check=False)
    return 0
