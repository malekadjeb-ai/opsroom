# Changelog

## 0.14.0 — 2026-07-22 · "glass box"

Know what you're about to do, where it runs, and where everything lives.

- **NEXT MOVE** — the top-ranked action renders as a hero at the head of
  DO NOW: one glance, one action. The rest stays a ranked list below it.
- **⚙ HOW DISPATCH RUNS** — a panel on /do that answers "where does this
  actually go?": the resolved command (your `[agent]` CLI — the same
  `claude` as your terminal, run headless and detached; NOT the desktop
  app), the log path, the watchdog/retry rules, and the config file.
- **📂 reveal** — every dispatched run, the dispatch folder, and
  config.toml get a Finder-reveal button (and palette commands). The
  client only ever sends *names* — brief/log/config/data plus a validated
  ts — the server derives every path itself; junk is refused.
- **Direct links where the work happens** — SEND rows link ↗ straight to
  your configured mail drafts; imported leads with a source URL get ↗ on
  their row; the palette gains jump-to-section (DO NOW / proposals / hot
  lanes) so finding a surface is two keystrokes.
- INBOX folds into a drawer; 38 gates green.

## 0.13.0 — 2026-07-22 · "flight deck"

The fix that mattered and the order the board deserved.

- **THE Chrome bug** — `Referrer-Policy: no-referrer` made Chrome send
  `Origin: null` on every same-origin form POST, which the same-origin gate
  rightly rejected: **every button in a real browser died with a misleading
  "bad token"**. The tests never saw it (urllib sends no Origin at all). Now:
  `Referrer-Policy: same-origin` (the referrer still never leaves this
  loopback origin), origin and token refusals split into honestly-named
  errors, and a browser-origin gate that pins real-browser behavior — with
  `Origin: null` (a sandboxed iframe's signature) still rejected.
- **One column** — the header (HUD, search, nav) rides the same 920px column
  as the content; a full-bleed cockpit over a centered page read as sprawl.
- **Quiet meta headers** — every section is a short title with its qualifier
  in a right-aligned mono meta slot ("nothing applies without your tap",
  "7 ranked · most money first"), never a bold sentence.
- **Actions on demand** — lead rows show ☎ called and ▶ dispatch; draft /
  quoted-$ / collected-$ / stage fold behind ⋯ (same forms, same verbs).
  Five always-open controls per row was the loudest noise on the board.
- **Proposal grouping** — identical pending proposals render once with a ×N
  chip, so a double-staged $380 can't be double-applied by reflex; the rest
  surface one at a time as each is decided.
- **Less prose everywhere** — sentence-length placeholders, per-card hint
  paragraphs, and header clauses cut across NOW, BOARD, DO, MONEY, VENTURES.
- 37 gates green.

## 0.12.0 — 2026-07-22 · "one board, zero doubt"

Dispatch you can trust, the whole operation on one surface, and every number
earning its place.

### Dispatch you can trust
- **The runs ledger** — every agent launch lands in ops.db and every exit is
  a recorded fact: pid, exit code, duration, output size, scrubbed tail. The
  v0.11 reaper discarded the return code, so a run that died instantly left a
  0-byte log and zero trace — and read as "done" after a restart. A reconcile
  sweep (boot, per render, sync tick) adopts live runs and finalizes orphans;
  exit codes now survive restarts.
- **Dead runs go red** — a 0-byte or nonzero-exit run is the console's TOP
  banner: task, accounting, log link, one-tap dismiss. Backfilled pre-0.12
  runs mark `unknown` and never false-alarm.
- **Watchdog** — `[agent] timeout_minutes` (default 30): a hung run gets a
  group SIGTERM→SIGKILL, a log marker saying why, and a `killed` record.
- **Auto-retry** — an advisor run that dies at 0 bytes (the unattended one)
  retries exactly once, both attempts linked in the ledger. Operator runs get
  the banner instead of a loop.
- **✕ cancel** — kill a running dispatch from the console; recorded as
  `cancelled` *before* the signal fires so the verdict can't be overwritten.
- **A real live tail** — /do grows the log in place via a TS_RE-locked,
  read-only, scrub-on-read `/tail` endpoint (2s poll) instead of reloading
  the whole page every 4 seconds.
- **`opsroom doctor --fire`** — one flag proves the whole loop through your
  REAL configured command: launch → log → reap → ledger, verdict printed as
  exit · duration · bytes. Refuses when `[agent]` is disabled.
- **Stale-code tripwire** — the always-on console banners when the code on
  disk is newer than what it booted with (the editable-install drift that ran
  a pre-fix build all night), naming both versions and the restart command.
- **`[agent] input = "stdin"`** — pipe the brief for CLIs that don't take
  argv prompts; the default one-argv-no-shell path is unchanged.

### One board
- **Hot lanes ON NOW** — REPLIED / DUE TODAY / NEW TODAY / QUOTED-going-cold
  render as ledger-true lanes inside NOW, each row the same `_lead_row`
  grammar (inline call/quote/collect/stage/dispatch) as the full board, each
  lead in its hottest lane only. The daily lead loop no longer needs a tab.
- **Command palette** — `/` or `k` anywhere: jump to any surface, open any
  hot lead, mark a follow-up done, apply an agent proposal, dispatch the top
  move, focus search or the ask bar. Server-rendered inert JSON + ~80 lines
  of stdlib JS; every action fires through the existing CSRF-gated verbs.
- **One nav** — NOW · BOARD · MONEY · ADVISOR (ventures/activity as minor
  icons), generated from a single definition on every surface.

### 100% accurate
- Every HUD number is a ledger fact in served mode — the open-lead count and
  its warn color come from the same rows; "awaiting your tap" counts exactly
  what the page asks you to act on. The aged-leads TOP LEAK is recomputed
  from the ledger, never a stale note.
- Note-derived claims (TOP MOVE, the honest band, baseline) wear a visible
  **notes** source pill; the band disappears once the note is a week stale.
- **LEDGER TRUTH in every brief** — the dispatch/advise brief now leads with
  the configured goal and the ledger's collected/spent/net, with an explicit
  no-invention rail, so an advisor can never frame a briefing from stray
  files again.
- Operator dates are LOCAL dates: `first_seen` no longer stamps the UTC day
  (an 11pm lead used to read "first seen tomorrow").
- New gates: runs ledger, watchdog, retry, tail/cancel, doctor --fire,
  stale-code, hot lanes, nav, palette, accuracy — 36 total, all green.

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
