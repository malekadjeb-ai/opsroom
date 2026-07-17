# Multi-agent collectors — design (approved 2026-07-17)

Goal: opsroom ingests every major AI coding agent, not just Claude Code, and the
launch story becomes "one console for all your AI agents — shows you whether they're
paying." Approach A (sibling collectors, flat pattern) approved.

## 1. Codex collector — `opsroom/collectors/codex.py`

- Source: `~/.codex/sessions/**/*.jsonl` and `~/.codex/archived_sessions/**/*.jsonl`
  (OpenAI Codex CLI rollout files). Strictly read-only.
- Incremental: reuse `file_changed` / `record_file` watermarks, same as `cli.py`.
- Record mapping:
  - `session_meta` → session id (`payload.id`), and `payload.cwd` when present.
  - `turn_context` → `payload.cwd` for venture attribution (`ventures.attribute`),
    identical rule to the Claude collector.
  - `response_item` with `payload.type == "message"`:
    - `role: user` → `kind=prompt, actor=you` (skip system/developer roles and
      permission/instruction wrappers starting with `<`).
    - `role: assistant` → `kind=response, actor=codex`.
  - `response_item` with `payload.type` in `function_call`/`local_shell_call`/
    `custom_tool_call` → `kind=tool_call, actor=codex`.
  - `event_msg` `task_started` → ignored (noise); errors → `kind=error`.
- Emits `source="codex"`. Session id namespaced as-is (UUIDs, no collision with Claude).
- Active minutes come from the shared gap-cap in `enrich._active_minutes` so Claude and
  Codex hours are comparable.

## 2. ChatGPT export — extend `opsroom/collectors/chat.py`

- Same drop dir, same zip flow, same post-ingest cleanup. Zero new config.
- Format sniff per conversation list:
  - has `chat_messages` → existing Anthropic parser (actor `assistant`).
  - has `mapping` (node tree) → new OpenAI parser: iterate mapping values,
    read `message.author.role` (`user`/`assistant`), text from
    `message.content.parts`, timestamp from `message.create_time` (epoch float).
  - OpenAI zips also contain `conversations.json`, so the zip branch works unchanged.
- OpenAI messages emit `actor="chatgpt"` for assistant, `actor="you"` for user;
  `session_id=f"chatgpt:{conversation id}"`. Venture attribution by title + text
  keywords (`ventures.attribute_text`), like the Anthropic path.

## 3. Sessions generalization — `opsroom/enrich.py`

- `build_sessions` covers `source IN ('cli','codex')` (grouped by source+session_id)
  and writes the true source into the sessions row.
- `_classify_outcome`'s "someone came back later" probe matches the session's source.
- Bug fix (found during design): `detect_loops` used `from collectors import git`,
  an invalid absolute import inside the package — crashes every sync at the
  planted-todo verification step. Fixed to a relative import.

## 4. BY AGENT activity block

- Terminal: `opsroom week` prints a BY AGENT table — per agent (claude/codex/chatgpt):
  sessions, active hours, top venture, last seen. Agent name = session/event source
  mapped for display (`cli→claude`, `codex→codex`, chat events with actor chatgpt).
- Dashboard ACTIVITY tab: same table above Recent sessions. This is the launch
  screenshot.

## 5. Demo data

- `opsroom demo` seeds fictional Codex sessions and a ChatGPT strategy chat so the
  10-second demo shows the multi-agent story.

## 6. Tests (script gates, exit 0 = green, matching existing style)

- `tests/test_codex.py`: synthetic rollout jsonl → events emitted, cwd attribution,
  malformed lines tolerated, incremental re-run emits nothing new.
- `tests/test_chat_openai.py`: synthetic OpenAI conversations.json → correct actors,
  epoch timestamps normalized, Anthropic sniff still works, malformed convs tolerated.

## 7. Launch checklist (executed after build)

- README rewritten around the multi-agent hook; demo GIF above the fold (vhs tape
  provided in `docs/launch/demo.tape`); social preview instructions.
- GitHub Actions CI (3.11/3.12/3.13, run the test gates) for the green badge.
- Drafts in `docs/launch/`: Show HN post, X thread, Reddit posts
  (r/ClaudeAI, r/OpenAI, r/LocalLLaMA), all landing the same Tue–Thu morning.
- Version 0.2.0 = multi-agent. The write-back port from private cc becomes 0.3.
- Open decision (Malek's staged-launch gate): launch on 0.2.0 or wait for the
  write-back port. The checklist flags it; nothing here blocks on it.
