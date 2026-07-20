# X launch thread draft

**Tweet 1 (hook + GIF):**

Your AI agents write code all day.

Do you know if any of it makes money?

I built opsroom: one local console for Claude Code + Codex + ChatGPT that shows
which agent worked on what, and whether the work pays.

No cloud. No accounts. One SQLite file.

[demo.gif]

**Tweet 2:**

It reads what's already on your disk:

- ~/.claude/projects (Claude Code)
- ~/.codex/sessions (Codex CLI)
- ChatGPT + Claude data exports
- your git repos
- your markdown notes

→ one dashboard: cash vs goal, action queue, effort-vs-revenue drift.

**Tweet 3:**

The feature that hurt the most: trap-zone drift.

Hours spent building $0-revenue side quests vs hours on things that pay — with a
red alert the week building beats selling.

The engineer's trap, on a chart.

**Tweet 4:**

And "open loops": everything you started and silently dropped.

The agent said "next I'll wire up the tests" … and no commit ever followed. Stale
branches. Orphaned tasks. It all stays on the board until closed.

**Tweet 5 (it operates, not just measures):**

Then it stopped being a dashboard.

The whole console is now one money-ranked DO NOW stack — replies, follow-ups, leads,
staged drafts — each row DOable in place: draft the reply, tap to dial, or hand the
task to your local agent CLI with a full context brief.

Measurement → action → back to the agents.

**Tweet 6 (the loop):**

New in 0.9: the loop runs both ways.

When a dispatched agent finishes, opsroom parses its output into PROPOSED ledger
writes — "record $380 collected", "schedule the follow-up", "run this next".

Nothing auto-applies. Each proposal waits on the console for your one-tap approve.

Agents propose. You approve. The ledger moves.

**Tweet 7 (CTA):**

pipx install opsroom-console
opsroom demo   ← fully loaded fictional console in 10 seconds

Stdlib-only Python, MIT, fail-closed secret redaction, zero network egress.

Repo: https://github.com/malekadjeb-ai/opsroom

**Timing:** same morning as the HN post, ~30 min after.
