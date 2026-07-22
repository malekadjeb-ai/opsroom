# Changelog

## 0.11.0 — 2026-07-21 · "the operator's cockpit"

The clarity release: know exactly what to do in ten seconds.

- **PIPELINE** — leads stop being a blob. New stage axis (new/contacted/talking/
  quoted/won/lost) + source/intent/first_seen/link/next_due columns, all
  additive with a one-time backfill that derives stages only from data already
  in the rows; the legacy status column stays mirrored so nothing breaks.
  `/leads` becomes a stage-segmented board with live counts, temperature-
  colored ages, inline stage moves, and human titles — never "LSA · lead".
  The importer keeps provenance structured instead of flattening it into the
  note; a replied lead arrives in *talking* with the call due today.
- **lead_stage** — new whitelisted proposal verb: agents can propose pipeline
  moves; you approve with one tap, like every other write.
- **The NOW fold** — exactly one alert banner (rest fold behind "+N more",
  including the previously invisible advisor-error breadcrumb), one pace line
  that includes today's tape, the briefing collapsed to its verdict + 3 plays,
  DO NOW capped at 7 rows with routine sends/calls collapsed to one row each,
  and coding-session promises moved to a PROMISES drawer — only money work
  ranks.
- **Real navigation** — NOW · LEADS · MONEY · ADVISOR · VENTURES on every
  page; /leads and /counsel stop hiding behind buried links; one shared
  stylesheet + page shell across all workspace pages.
- **`opsroom connect`** — detects your agent CLI (claude/codex/gemini), shows
  what it resolved, writes `[agent]` only on your explicit yes (second yes =
  daily autonomous briefing). Terminal-only by design; the web wall stands.
- **`opsroom doctor`** — read-only wiring check: config, DB perms, agent
  command resolution (launchd bare-PATH aware), advise mode, and the last
  advisor error, verbatim. Exit 1 on any real failure.

## 0.10.2 — 2026-07-21

- **Auto-reload actually reloads** — the CSP (`default-src 'none'`) was blocking
  the page's own `/version` poll, so no open console page had ever refreshed
  itself after a write; `connect-src 'self'` unblocks it (still zero external
  origins). A gate now pins the directive.

## 0.10.1 — 2026-07-21

Two production fixes found by the advisor's own first night:

- **Agent CLI resolution** — the always-on console (launchd/systemd) runs with a
  minimal PATH, so `claude` was unfindable and every dispatch it fired died into
  a 0-byte log. argv[0] now resolves like a login shell (PATH + ~/.local/bin,
  /opt/homebrew/bin, /usr/local/bin); an unresolvable command fails loudly into
  the log with a hint instead of raising.
- **Self-healing counsel harvest** — a finished advise run whose registration was
  lost is recovered by the sweep from its own brief (opsroom-written, never agent
  output — registered-runs-only holds); advisor errors land in kv `advise_error`
  instead of vanishing.

## 0.10.0 — 2026-07-20 · "the advisor"

The console stops waiting for you and starts thinking.

- **Ask the board anything** — a 🧠 ask bar on NOW: your question is dispatched to
  your agent CLI with the full live context; the answer renders as first-class
  console content on `/counsel` (escape-first, link-free markdown — agent prose is
  untrusted input), any plan comes back as ▶-dispatchable steps, and any
  ` ```opsroom ` blocks become one-tap proposals as usual.
- **The autonomous advisor** — `[agent] advise = "daily"` or an hour interval
  (2..168): opsroom launches the agent BY ITSELF on a schedule to assess the whole
  board and surface 3-5 plays BEYOND the derived DO NOW. You open the console to a
  🧠 TODAY'S BRIEFING that was thought up while you were away. This is opsroom's
  first unattended agent launch, so it's a second opt-in beyond `enabled`, its
  task string is a hard-coded constant, it fires at most once per window
  (claim-first, crash-safe), and never while other work runs.
- **Counsel protocol** — one ` ```counsel ` markdown answer block (16KB cap) + one
  ` ```counsel-plan ` JSON block (≤7 steps, numbered-line fallback); harvested
  only from runs opsroom itself registered — a fence smuggled into an ordinary
  run's log is ignored. Threat model in `opsroom/counsel.py`.
- Demo seeds an autonomous briefing; gate count 22 (new: tests/test_counsel.py).

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
