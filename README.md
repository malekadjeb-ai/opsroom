# ⚡ opsroom

![ci](https://github.com/malekadjeb-ai/opsroom/actions/workflows/ci.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![deps](https://img.shields.io/badge/dependencies-zero-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

<!-- LAUNCH: insert demo GIF here — vhs docs/launch/demo.tape -->

**Your AI agents write code all day. opsroom shows you whether any of it pays.**

One console for **every AI coding agent you run** — Claude Code, OpenAI Codex CLI, ChatGPT, Claude web — plus your **git repos** and your **markdown notes** (Obsidian or plain folders), fused into one local dashboard that answers the only question that matters:

> *What should I do right now to make money?*

No cloud. No accounts. No dependencies. One Python package, one SQLite file on your disk, one HTML file as your console.

```
pipx install opsroom     # or: pip install opsroom / uv tool install opsroom
opsroom demo             # see a fully loaded console in 10 seconds (fictional data)
opsroom init             # wire up YOUR repos, goal, and notes
opsroom sync && opsroom dash
```

## What you get

**🎯 NOW — an action queue, not a report.** Drafts staged in your outreach tracker become a send list with an open-your-drafts button. Phone-first targets become tap-to-dial links. Stale leads become a rescue block. The single highest cash action sits on top, pulled from your own dashboard note.

**🏢 VENTURES — every project, with a brief.** Click any venture: an ordered **DO NEXT** list generated from live pipeline state ("UNBLOCK FIRST: …" when your notes say something's blocking), a **DONE** timeline auto-pulled from your decisions log, live numbers, and every researched target as a searchable click-to-open card — pain hypothesis, decision-makers, phones linked.

**💰 MONEY — the goal math.** Collected vs goal, days left, needed per day. Cash counts only when collected, not quoted.

**📊 ACTIVITY — where your time actually went, by agent.** A **BY AGENT** table (Claude vs Codex vs ChatGPT: sessions, active hours, top venture), sessions per venture, commits, and the two features that hurt (in a good way):

- **Trap-zone drift**: time spent in $0-revenue builds vs revenue ventures, with a red alert when building beats selling this week. The engineer's trap, made visible.
- **Open loops**: things you started and silently dropped — plan language in AI transcripts with no follow-up commit, stale branches, uncommitted work, in-progress notes going stale.

## The sitrep

```
$ opsroom sitrep

SITREP · 2026-07-16

- DATE / DAYS TO GOAL: 2026-07-16 / 19d
- CASH COLLECTED vs Q3 $50K sprint: $8,250 collected
- OPEN LEADS: ~14 aged ~8d
- LIVE PIPELINE: Meridian: 2 proposals out ($12K + $18K) · 2 drafted, 1 sent, 2 call sheet
- TOP LEAK RIGHT NOW: ~14 open leads aged ~8d — paid-for money rotting uncalled
- SINGLE HIGHEST CASH ACTION TODAY: Finish the case-study PDF and send both proposals
```

Six lines, every morning, from live data. `--write` appends it to a daily note.

## How it works

Read-only collectors, one local SQLite ledger, deterministic rendering:

| Source | What it reads |
|---|---|
| `cli` | Claude Code session logs (`~/.claude/projects`) — prompts, duration, outcomes |
| `codex` | OpenAI Codex CLI session logs (`~/.codex/sessions`) — same treatment, same attribution |
| `git` | every repo under your scan roots — commits, branches, uncommitted work |
| `fs` | mtime scan for non-git work |
| `notes` | your markdown roots — frontmatter, staleness, your dashboard note's `## Live state` table |
| `chat` | manual drop of a chat export — **both** Claude (Anthropic) and ChatGPT (OpenAI) exports, sniffed by shape |

Attribution is by path: work done in `~/code/acme` counts toward venture `acme`. Sessions are gap-capped active minutes, not wall clock.

### Your notes are the API

opsroom doesn't make you adopt a system — it reads simple markdown conventions you can start using in five minutes:

- A dashboard note with a `## Live state` table (`| Metric | Value | As of |`) — rows are matched by key words (`days to goal`, `cash`, anything with `lead`), never by position, so reformatting won't break it. Ages keep ticking: "aged ~6 days" as-of last week reads correctly today.
- A `## Today's one move` section → the console's hero action.
- Pipeline trackers with `## Totals` lines and `## TOUCH LOG` tables (`Target | Channel | Status | Next`) → your send/call queues. Any wide table in the same file → your searchable target list.
- A `Decisions Log.md` with `- **YYYY-MM-DD** — …` bullets → per-venture DONE timelines.

## Security posture

This tool reads your terminal history and notes, so it's built paranoid:

- **Fail-closed secret redaction** — every event passes a redactor *before* touching the DB (API keys, AWS/GitHub/Slack/Stripe/Google tokens, JWTs, DB URIs, private keys, high-entropy `KEY=value`). If redaction errors, the event is dropped, never written.
- **No network egress. Ever.** Nothing phones home; the console HTML loads zero external resources. The only URLs are ones *you* configured as buttons.
- **Local only** — SQLite at `~/.local/share/opsroom` with `600` perms, refuses to live under a cloud-sync root (iCloud/Dropbox/OneDrive).
- **Read-only on all sources** — your notes are never written; the only writes are the ledger and an optional append-only daily note.
- `opsroom purge --source=X` / `--before=DATE` to shrink the blast radius any time.

## Philosophy

Built during a 23-day cash sprint by an operator running eight ventures, out of one frustration: every productivity tool tracks *activity*; none of them track *whether the activity pays*. The rules encoded here are blunt:

1. Cash counts when **collected** — not quoted, not booked, not "basically closed".
2. Building instead of selling is a **trap** — visible on the board, hours counted.
3. Everything you start and drop is a **loop** — it stays on the board until closed or dismissed.
4. The console must answer *"what do I do next"* with names, numbers, and buttons — or it's just letters on a screen.

## FAQ

**Do I need Claude Code / Codex / Obsidian?** No. Every source is optional and degrades gracefully. Git repos alone give you drift + loops + sessions; add notes when you want the money features.

**Which AI agents are supported?** Claude Code and OpenAI Codex CLI are read live from their local logs. ChatGPT and Claude web/desktop ingest via each vendor's data-export file dropped in a folder. Gemini CLI and Cursor are next — collectors are ~100-line files with one `collect(con)` entry point, PRs welcome.

**macOS says the notes are unreadable.** Grant your terminal Full Disk Access. If access drops mid-session, opsroom serves the last cached snapshot and says so.

**Windows?** WSL works. Native Windows is untested.

## Development

```
git clone https://github.com/malekadjeb-ai/opsroom && cd opsroom
for t in tests/test_*.py; do python "$t" || break; done   # five gates, all must print green
python -m opsroom.cli demo
```

Stdlib only — there is nothing to `pip install` for development. MIT license.
