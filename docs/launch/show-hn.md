# Show HN draft

**Title (79 char max):**

Show HN: Opsroom – local console showing whether your AI coding agents pay rent

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

The features that changed my behavior:

- **Trap-zone drift**: hours in $0-revenue projects vs revenue projects, red alert
  when building beats selling. The engineer's trap, made visible.
- **Open loops**: things I started and silently dropped — plan language in agent
  transcripts with no follow-up commit, stale branches, orphaned tasks.
- **BY AGENT**: Claude vs Codex vs ChatGPT — sessions, hours, which venture each
  actually worked on.
- **Sitrep**: six lines every morning — cash vs goal, aging leads, the single
  highest-cash action today.

Security posture, since it reads terminal history: fail-closed secret redaction
before anything touches the DB, zero network egress, 600-perm SQLite that refuses
to live in a cloud-sync folder, read-only on every source.

`pipx install opsroom && opsroom demo` gives you a fully loaded fictional console
in ten seconds.

Happy to answer anything about parsing the agents' log formats — Codex's rollout
files and Claude's JSONL are surprisingly pleasant; ChatGPT's export mapping-tree
less so.

**Timing:** Tue/Wed/Thu, 6:00-8:00 AM Pacific. Never Friday/weekend.
**Rules:** don't ask for votes anywhere, don't share the direct HN link (rings get penalized) — say "opsroom is on HN today" and let people find it.
