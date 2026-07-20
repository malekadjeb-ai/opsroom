# Show HN draft

**Title (79 char max):**

Show HN: Opsroom – your AI agents propose, you approve, the ledger moves

**URL:** https://github.com/malekadjeb-ai/opsroom

**First comment (post immediately after submitting):**

I run several small ventures solo, with Claude Code and Codex doing most of the
building. A month in I realized I had perfect logs of *activity* and zero visibility
into whether any of it made money. Every productivity tool tracks hours; none track
whether the hours pay.

So opsroom reads what already exists on your disk — Claude Code logs
(~/.claude/projects), Codex CLI logs (~/.codex/sessions), ChatGPT/Claude data
exports, your git repos, your markdown notes — into one SQLite file, and renders a
single local HTML console. No cloud, no accounts, no deps (stdlib only).

What it measures, that changed my behavior:

- **Trap-zone drift**: hours in $0-revenue projects vs revenue projects, red alert
  when building beats selling. The engineer's trap, made visible.
- **Open loops**: things I started and silently dropped — plan language in agent
  transcripts with no follow-up commit, stale branches, orphaned tasks.
- **BY AGENT**: Claude vs Codex vs ChatGPT — sessions, hours, which venture each
  actually worked on.

Then I stopped just measuring and made it operate. The console is now one local app
(loopback HTTP, CSRF-gated, still zero egress) where the whole thing is a single
money-ranked **DO NOW** stack — replies to answer, follow-ups due, staged drafts,
leads to call — each row DOable in place:

- A **reply drafter** that turns a pasted inbound message into a rails-correct reply
  from your own config (deterministic, no LLM call, never echoes a number you didn't
  write down).
- A **cash + spend + ROI** ledger — real per-venture P&L, not just a vanity meter.
- **Agent dispatch**: the top action becomes a one-tap hand-off to your local agent
  CLI with a full context brief — plus a FIFO **work queue** so dispatches chain
  instead of colliding.
- A live **AGENTS RUNNING** panel that reads which Claude Code sessions are alive
  right now (interactive, cowork, background), attributed per venture.
- A full **leads workspace** — every lead ever captured, searchable, sortable by
  age or quote size, each one dispatchable with its history baked into the brief.

The newest piece closes the loop in the other direction: **agents propose, you
approve, the ledger moves**. When a dispatched agent finishes, opsroom parses its
output for fenced JSON blocks — "record $380 collected", "schedule the day-2
follow-up", "add this lead", "run this next" — and stages them as pending
proposals on the console. Nothing auto-applies, ever: each proposal is one tap to
apply (through the same code path as the manual buttons) or dismiss, with a
provenance link to the raw log. Agent stdout is treated as untrusted input — a
strict verb whitelist onto actions you could already do by hand, size caps,
fail-closed secret redaction, idempotent staging, double-tap-safe application.
A prompt-injected agent can at worst put a visible pending row on the board.

Security posture, since it reads terminal history AND parses agent output:
fail-closed secret redaction before anything touches the DB, zero network egress,
600-perm SQLite that refuses to live in a cloud-sync folder, read-only on every
source, human-tap-gated writes only.

`pipx install opsroom-console && opsroom demo` gives you a fully loaded fictional console
in ten seconds.

Happy to answer anything about parsing the agents' log formats — Codex's rollout
files and Claude's JSONL are surprisingly pleasant; ChatGPT's export mapping-tree
less so.

**Timing:** Tue/Wed/Thu, 6:00-8:00 AM Pacific. Never Friday/weekend.
**Rules:** don't ask for votes anywhere, don't share the direct HN link (rings get penalized) — say "opsroom is on HN today" and let people find it.
