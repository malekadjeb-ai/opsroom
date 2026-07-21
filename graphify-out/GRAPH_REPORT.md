# Graph Report - .  (2026-07-18)

## Corpus Check
- 58 files · ~71,193 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 491 nodes · 924 edges · 20 communities (19 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.75)
- Token cost: 0 input · 427,471 output

## Community Hubs (Navigation)
- [[_COMMUNITY_ChatCLI Collectors|Chat/CLI Collectors]]
- [[_COMMUNITY_Dashboard Rendering|Dashboard Rendering]]
- [[_COMMUNITY_Ops Ledger & Leads|Ops Ledger & Leads]]
- [[_COMMUNITY_State & Config Cache|State & Config Cache]]
- [[_COMMUNITY_CLI Commands & Config|CLI Commands & Config]]
- [[_COMMUNITY_House Rules & Concepts|House Rules & Concepts]]
- [[_COMMUNITY_Dispatch Write-Back Loop|Dispatch Write-Back Loop]]
- [[_COMMUNITY_Demo Server & HTTP Serve|Demo Server & HTTP Serve]]
- [[_COMMUNITY_Views & Loop Detection|Views & Loop Detection]]
- [[_COMMUNITY_Inbox Import (LeadsReplies)|Inbox Import (Leads/Replies)]]
- [[_COMMUNITY_Console Activity Screenshot|Console Activity Screenshot]]
- [[_COMMUNITY_Console NOW Screenshot|Console NOW Screenshot]]
- [[_COMMUNITY_Context Pack & Promises|Context Pack & Promises]]
- [[_COMMUNITY_Session Enrichment|Session Enrichment]]
- [[_COMMUNITY_Git Collector|Git Collector]]
- [[_COMMUNITY_Draft Reply Generator|Draft Reply Generator]]
- [[_COMMUNITY_Social Preview Card|Social Preview Card]]
- [[_COMMUNITY_Session Tracking|Session Tracking]]
- [[_COMMUNITY_Demo GIF Walkthrough|Demo GIF Walkthrough]]
- [[_COMMUNITY_Console Package Entry|Console Package Entry]]

## God Nodes (most connected - your core abstractions)
1. `Emitter` - 25 edges
2. `Multi-Agent Collectors Design Spec (2026-07-17)` - 16 edges
3. `build_state()` - 14 edges
4. `collect()` - 12 edges
5. `render()` - 12 edges
6. `opsroom README` - 12 edges
7. `_do_now_stack()` - 10 edges
8. `Console Activity Panel (OPERATOR dashboard, 2026-07-17)` - 10 edges
9. `file_changed()` - 9 edges
10. `Handler` - 9 edges

## Surprising Connections (you probably didn't know these)
- `collect()` --implements--> `Collector Writing Recipe (collect(con, dry_run) entry point)`  [INFERRED]
  opsroom/collectors/codex.py → CONTRIBUTING.md
- `Multi-Agent Collectors Design Spec (2026-07-17)` --references--> `collect()`  [EXTRACTED]
  docs/superpowers/specs/2026-07-17-multi-agent-collectors-design.md → opsroom/collectors/chat.py
- `Venture Attribution by Working-Directory Path` --references--> `collect()`  [EXTRACTED]
  README.md → opsroom/collectors/codex.py
- `Multi-Agent Collectors Design Spec (2026-07-17)` --references--> `collect()`  [EXTRACTED]
  docs/superpowers/specs/2026-07-17-multi-agent-collectors-design.md → opsroom/collectors/codex.py
- `Multi-Agent Collectors Design Spec (2026-07-17)` --references--> `build_sessions()`  [EXTRACTED]
  docs/superpowers/specs/2026-07-17-multi-agent-collectors-design.md → opsroom/enrich.py

## Import Cycles
- 4-file cycle: `opsroom/contextpack.py -> opsroom/views.py -> opsroom/dashboard.py -> opsroom/dispatch.py -> opsroom/contextpack.py`

## Hyperedges (group relationships)
- **Launch Campaign Materials (runbook, checklist, HN, X, Reddit)** — docs_launch_runbook, docs_launch_launch_checklist, docs_launch_show_hn, docs_launch_x_thread, docs_launch_reddit [INFERRED 0.85]
- **Collector Protocol Pattern (collect(con) entry point shared by all agent collectors)** — opsroom_collectors_cli, opsroom_collectors_codex_collect, opsroom_collectors_chat_collect, concept_collector_recipe [INFERRED 0.85]
- **House Rules Enforced Across Contribution Surfaces** — concept_opsroom_house_rules, github_issue_template_feature_request, contributing, github_pull_request_template, readme [INFERRED 0.85]
- **Claude and Codex agents both converge on Blog Engine as their top venture** — docs_launch_console_activity_claude_agent, docs_launch_console_activity_codex_agent, docs_launch_console_activity_blog_engine_venture [EXTRACTED 1.00]
- **Red alert trap-zone warning is driven by stale, revenue-less open loops** — docs_launch_console_activity_red_alert_banner, docs_launch_console_activity_blog_engine_rewrite_loop, docs_launch_console_activity_meridian_proposals_loop [INFERRED 0.80]
- **Single money-ranked NOW view replacing prior multi-card layout (leak alert + pace + agents + do-now stack)** — docs_launch_console_now_top_leak_alert, docs_launch_console_now_todays_pace, docs_launch_console_now_agents_running_panel, docs_launch_console_now_do_now_stack [INFERRED 0.85]
- **Meridian venture thread spanning agent cowork task and DO NOW follow-up items** — docs_launch_console_now_cobalt_proposal_task, docs_launch_console_now_dana_reyes_replied_item, docs_launch_console_now_meridian_case_study_item, docs_launch_console_now_call_dana_reyes_item [INFERRED 0.85]
- **demo.gif walkthrough: demo seeds data -> sitrep reports cash/pipeline -> week shows effort vs revenue trap-zone alert** — docs_launch_demo_opsroom_demo_command, docs_launch_demo_opsroom_sitrep_command, docs_launch_demo_opsroom_week_command [EXTRACTED 1.00]
- **VHS tape script renders CLI recording into launch GIF using demo/sitrep/week module code** — docs_launch_demo_tape_script, docs_launch_demo_dispatch_demo_flow, opsroom_cli_module [INFERRED 0.85]
- **Three supported coding-agent integrations shown as badges on the launch card** — docs_launch_social_preview_claude_code_integration, docs_launch_social_preview_codex_cli_integration, docs_launch_social_preview_chatgpt_integration [EXTRACTED 1.00]
- **Install/demo/license call-to-action row forming the launch onboarding path** — docs_launch_social_preview_pipx_install_command, docs_launch_social_preview_opsroom_demo_command, docs_launch_social_preview_mit_license [INFERRED 0.85]

## Communities (20 total, 1 thin omitted)

### Community 0 - "Chat/CLI Collectors"
Cohesion: 0.06
Nodes (50): collect(), _ingest_any(), _ingest_conversations(), _ingest_openai(), _openai_text(), Collector: Desktop/web chat via the vendor data-export flow (manual drop). Drop, OpenAI ChatGPT export: each conversation is a mapping-tree of nodes., Sniff export format: Anthropic conversations carry chat_messages, OpenAI carry m (+42 more)

### Community 1 - "Dashboard Rendering"
Cohesion: 0.08
Nodes (44): _do_now_stack(), do_page(), do_url(), draft_page(), draft_url(), _f(), _hm(), _ledger_cards() (+36 more)

### Community 2 - "Ops Ledger & Leads"
Cohesion: 0.07
Nodes (28): add_lead(), capture(), connect(), db_path(), followup_set(), followups_due(), followups_upcoming(), _local_day_utc_bounds() (+20 more)

### Community 3 - "State & Config Cache"
Cohesion: 0.09
Nodes (36): _aged_days(), build_state(), cache_path(), _cfg_path(), _clean_cell(), dashboard_note(), db_enrichment(), _first_int() (+28 more)

### Community 4 - "CLI Commands & Config"
Cohesion: 0.09
Nodes (26): cmd_purge(), cmd_status(), cmd_sync(), main(), config_dir(), data_dir(), _default_scan_roots(), goal_amount() (+18 more)

### Community 5 - "House Rules & Concepts"
Cohesion: 0.14
Nodes (27): BY AGENT Activity Comparison Table, Collector Writing Recipe (collect(con, dry_run) entry point), DO IT / Agent Dispatch Write-Back Loop, Fail-Closed Secret Redaction, One Console For All AI Coding Agents (multi-agent positioning), NOW Money-Ranked Action Stack, Open Loops Detection (abandoned plans/branches/todos), House Rules: zero deps, zero network egress, read-only sources, local-first (+19 more)

### Community 6 - "Dispatch Write-Back Loop"
Cohesion: 0.10
Nodes (27): Match, build_brief(), dispatch(), _dispatch_dir(), _open_600(), Path, Agent dispatch — close the loop in BOTH directions. opsroom already reads what y, (brief only) · 'running' · 'done' · 'exit N'. Works across console     restarts: (+19 more)

### Community 7 - "Demo Server & HTTP Serve"
Cohesion: 0.10
Nodes (15): BaseHTTPRequestHandler, `opsroom demo` — a fictional three-venture portfolio, fully loaded, in one comma, _bump(), Handler, install_always_on(), _money(), _page(), `opsroom serve` — the console as a local app. Loopback only, zero dependencies. (+7 more)

### Community 8 - "Views & Loop Detection"
Cohesion: 0.13
Nodes (23): _bar(), by_agent(), _chmod_note(), daily_writeback(), dash(), _day_bounds(), drift(), _fts_query() (+15 more)

### Community 9 - "Inbox Import (Leads/Replies)"
Cohesion: 0.14
Nodes (22): _digits(), _ensure(), _import(), import_leads(), import_replies(), leads_drop_path(), merge_leads(), merge_replies() (+14 more)

### Community 10 - "Console Activity Screenshot"
Cohesion: 0.13
Nodes (21): ACTIVITY tab (selected), Open loop: blog-engine rewrite, stale 12d, zero revenue attached, Blog Engine venture (5h30m, 46% of effort), By agent (last 7 days) table, chatgpt agent row (2 sessions, 2 msgs, top venture meridian), claude agent row (6 sessions, 8h55m, top venture blog-engine), codex agent row (2 sessions, 3h05m, top venture blog-engine), Console Activity Panel (OPERATOR dashboard, 2026-07-17) (+13 more)

### Community 11 - "Console NOW Screenshot"
Cohesion: 0.13
Nodes (20): ACTIVITY tab, AGENTS RUNNING panel: 2 live, 1 cowork session, Agent task: fix booking bug (interactive, DetailPro), DO NOW item: Call Dana Reyes (FOLLOW UP, meridian, due 2026-07-18), Agent task: draft the Cobalt proposal (cowork, Meridian Consulting), Daily activity counters: 2 touches, 0 calls, 1 sends, $1,250 collected today, DO NOW item: Dana Reyes replied — call or answer (REPLIED, meridian), DO NOW ranked action stack (10 ranked, most money first) (+12 more)

### Community 12 - "Context Pack & Promises"
Cohesion: 0.16
Nodes (11): The context pack — a live operator brief you paste into any AI chat to ground it, _ensure(), extract_from_text(), _norm(), open_promises(), promise_set(), Promise extractor — the anti-leak. Every AI session stages asks ("6 drafts await, Scan recently-modified agent session logs for staged asks. Returns new count. (+3 more)

### Community 13 - "Session Enrichment"
Cohesion: 0.25
Nodes (14): _active_minutes(), build_sessions(), by_agent(), _classify_outcome(), detect_loops(), drift(), _iso(), _now() (+6 more)

### Community 14 - "Git Collector"
Cohesion: 0.27
Nodes (12): collect(), _collect_commits(), _default_branch(), discover_repos(), _git(), Collector: git repos — commits (events), plus working-tree / branch state consum, Live working-tree + branch state for loop detection (not stored as events)., Ingest commits newer than the per-repo watermark. Returns new shas (for TODO sca (+4 more)

### Community 15 - "Draft Reply Generator"
Cohesion: 0.26
Nodes (9): _b2b(), _clarify(), detect(), draft_reply(), _greet(), Reply drafter — deterministic, stdlib, no LLM, no network. Speed-to-close is the, Keyword-rule intent tags for an inbound message., Rails-correct draft for an inbound message. Deterministic; rails come from     t (+1 more)

### Community 16 - "Social Preview Card"
Cohesion: 0.22
Nodes (10): ChatGPT (supported agent badge), Claude Code (supported agent badge), Codex CLI (supported agent badge), local-first / zero deps / zero egress positioning claim, MIT License, opsroom demo (CLI command), opsroom (product), pipx install opsroom-console (install command) (+2 more)

### Community 17 - "Session Tracking"
Cohesion: 0.27
Nodes (7): _age_seconds(), live(), Path, Live agent sessions — what's running RIGHT NOW, by mode. Read-only, stdlib.  Eve, Sessions updated within the freshness window, newest first. Each row:     {name,, Counts for the console strip: total live, and how many are cowork/background., summary()

### Community 18 - "Demo GIF Walkthrough"
Cohesion: 0.31
Nodes (9): opsroom Demo GIF (terminal walkthrough: demo -> sitrep -> week), `opsroom demo` command (seeds fictional demo portfolio), `opsroom sitrep` command (daily situation report), `opsroom week` command (week view: sessions/commits, effort-vs-revenue, trap-zone alert), docs/launch/demo.tape (VHS script that renders demo.gif), Trap-zone RED ALERT concept (build-time in $0-revenue ventures exceeds revenue-venture time), opsroom/cli.py (CLI entrypoint dispatching demo/sitrep/week subcommands), opsroom/demo.py (seeds fictional demo portfolio: 555 numbers, .example domains) (+1 more)

## Ambiguous Edges - Review These
- `Bug Report Issue Template` → `House Rules: zero deps, zero network egress, read-only sources, local-first`  [AMBIGUOUS]
  .github/ISSUE_TEMPLATE/bug_report.yml · relation: conceptually_related_to
- `Multi-Agent Collectors Design Spec (2026-07-17)` → `detect_loops() (module location ambiguous — likely state.py)`  [AMBIGUOUS]
  docs/superpowers/specs/2026-07-17-multi-agent-collectors-design.md · relation: references

## Knowledge Gaps
- **31 isolated node(s):** `opsroom-console`, `Bug Report Issue Template`, `Feature Request Issue Template`, `opsroom sitrep Command`, `Emitter class in opsroom/collectors/__init__.py` (+26 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Bug Report Issue Template` and `House Rules: zero deps, zero network egress, read-only sources, local-first`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Multi-Agent Collectors Design Spec (2026-07-17)` and `detect_loops() (module location ambiguous — likely state.py)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `opsroom README` connect `House Rules & Concepts` to `CLI Commands & Config`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `Emitter` connect `Chat/CLI Collectors` to `Git Collector`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `collect()` (e.g. with `Collector Writing Recipe (collect(con, dry_run) entry point)` and `build_sessions()`) actually correct?**
  _`collect()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `opsroom — local-first operator console. See https://github.com/malekadjeb-ai/ops`, `Shared collector plumbing: redact-gated event emission, per-file watermarks.`, `Normalize any ISO8601 timestamp (Z, ±hh:mm, or naive) to canonical UTC 'YYYY-MM-` to the rest of the system?**
  _145 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Chat/CLI Collectors` be split into smaller, more focused modules?**
  _Cohesion score 0.06400409626216078 - nodes in this community are weakly interconnected._