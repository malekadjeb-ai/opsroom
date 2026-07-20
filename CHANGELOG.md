# Changelog

## 0.9.0 — 2026-07-20 · "the operator loop"

The release where opsroom stops only reporting the business and starts running it,
with your tap as the throttle.

- **Agent proposals** — dispatched agents can end a run by printing fenced
  ` ```opsroom ` JSON blocks; opsroom parses them into PENDING ledger writes shown
  on a new AGENT PROPOSES strip. One tap applies (through the same write path as
  the manual buttons) or dismisses; nothing ever auto-applies. Agent output is
  treated as untrusted input: strict verb whitelist onto existing actions, size
  caps, fail-closed secret redaction, idempotent staging, double-tap-safe apply,
  provenance link to the raw log. Threat model documented in
  `opsroom/proposals.py`.
- **Work queue** — dispatch while an agent runs and it queues, auto-firing FIFO
  when the runner reaps; an applied "run this next" proposal queues the chain.
  Queued items show as chips in AGENTS RUNNING with one-tap dismiss; a sync-tick
  rescue fires items stranded by a console restart.
- **/leads workspace** — the whole lead register on one page: search, status
  chips (open/quoted/won/lost), age + quote-size sorts, every action inline, and
  a per-lead ▶ dispatch that bakes the lead's id, contact, quote and touch
  history into the agent brief.
- **Console-native onboarding** — a truly fresh install opens with a SET UP YOUR
  ROOM card: goal + ventures on the page, console re-renders configured without a
  restart. The web path refuses any config that already has a goal, ventures, or
  an `[agent]` section — `[agent]` stays terminal-only, always.
- **Demo** — `opsroom demo` now seeds a finished agent run with pending
  proposals and a leads register worth browsing.
- Gates: 21 (new: proposals, queue, leads workspace, web setup) plus a reusable
  fake agent CLI (`tests/fake_agent.py`) for live end-to-end demos.

## 0.8.0 — 2026-07-18

Hardening, honest demo, dispatch feedback. See the GitHub release notes.

## 0.7.0 and earlier

See GitHub releases: https://github.com/malekadjeb-ai/opsroom/releases
