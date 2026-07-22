"""The context pack — a live operator brief you paste into any AI chat to ground it in
the whole operation in one shot. Built from the same state the console renders, plus the
open promises and captures. Pure text; nothing here is written back."""
from datetime import datetime

from . import ventures, views


def build(con, ocon, st) -> str:
    from . import ops, promises
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# OPERATOR CONTEXT PACK — live from the ledger",
        f"Generated {now} · paste into any AI chat to ground it in the whole operation.\n",
        "## LEDGER TRUTH (authoritative)",
    ]
    # the numbers an advisor once invented from stray files it found on disk —
    # now stated up front, from config + the append-only ledger, with an
    # explicit no-invention rail. If anything below disagrees, THIS wins.
    cash_t = int(ops.cash_total(ocon) or 0)
    spend_t = int(ops.spend_total(ocon) or 0)
    goal_bits = f"${ventures.GOAL_USD:,}" if ventures.GOAL_USD else "not set"
    if ventures.DEADLINE:
        goal_bits += f" by {ventures.DEADLINE.isoformat()}"
    lines += [
        f"- THE goal: {ventures.GOAL_LABEL or 'no goal configured'} ({goal_bits})",
        f"- collected to date: ${cash_t:,} · spent: ${spend_t:,} · net: ${cash_t - spend_t:,}",
        "- These figures are the operator's real config + cash ledger. Quote them",
        "  exactly; never invent, estimate, or substitute a different goal or total.",
        "", "## SITREP",
    ]
    lines += views._sitrep_lines(st)

    tape = ops.today_tape(ocon)
    lines += ["", "## TODAY'S TAPE",
              f"{tape['touches']} touches · {tape['calls']} calls · {tape['sends']} sends · "
              f"${int(tape['cash']):,} collected today"]

    due = ops.followups_due(ocon)
    if due:
        lines += ["", "## DUE TODAY (the follow-up engine)"]
        lines += [f"- [{d['venture'] or '?'}] {d['target']} — {d['note'] or 'follow up'}"
                  for d in due]

    proms = promises.open_promises(ocon, limit=12)
    if proms:
        lines += ["", "## OPEN PROMISES (staged by an agent, awaiting your go)"]
        lines += [f"- [{p['venture'] or '?'}] {p['text']}" for p in proms]

    lines += ["", "## THE QUEUE (what needs doing now)"]
    have = False
    for v in st["ventures"]:
        nxt = st["next"].get(v["key"], [])
        if nxt and nxt[0] != "No queued actions — check the tracker or add playbook lines in config":
            lines.append(f"- [{v['key']}] {nxt[0]}")
            have = True
    if not have:
        lines.append("- (queue empty — wire up pipeline trackers or a dashboard note)")

    hist = sorted(({"date": h["date"], "text": h["text"], "v": k}
                   for k, hs in st["history"].items() for h in hs),
                  key=lambda x: x["date"], reverse=True)
    if hist:
        lines += ["", "## RECENT DECISIONS"]
        lines += [f"- {h['date']} [{h['v']}] {h['text'][:180]}" for h in hist[:5]]

    caps = ops.captures_open(ocon, limit=10)
    if caps:
        lines += ["", "## INBOX (captured, unfiled)"]
        lines += [f"- {c['text']}" for c in caps]

    rails = []
    for key, meta in ventures.VENTURES.items():
        for pb in meta.get("playbook", []):
            rails.append(f"- [{key}] {pb}")
    if rails:
        lines += ["", "## STANDING RAILS (from your config playbooks)"] + rails[:12]

    lines += ["", "## GROUND RULE",
              "- Cash counts only when collected, not quoted or booked. "
              "Stage side-effectful work (sends, spend, deploys) for approval; "
              "reversible work, just do."]
    return "\n".join(lines)
