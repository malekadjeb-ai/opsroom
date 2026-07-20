# Reddit drafts — post the same morning, each written for its sub. Never cross-post verbatim.

## r/ClaudeAI

**Title:** I built a local dashboard that reads ~/.claude/projects and tells me whether my Claude Code sessions actually pay

**Body:**

Claude Code keeps beautiful JSONL logs of everything it does, and I realized I never
look at them. So I built opsroom: it parses ~/.claude/projects (read-only), joins the
sessions with my git repos and markdown notes, and renders one local HTML console —
which venture each session worked on, gap-capped active minutes (not wall clock),
sessions that ended with "next I'll…" and no follow-up commit, and hours in
$0-revenue projects vs projects that pay.

It also ingests Codex CLI logs and ChatGPT exports, so if you run multiple agents
you get a BY AGENT comparison table — and a live panel of which Claude Code sessions
are running right now (interactive/cowork/background), attributed per project.

Then it goes further than a dashboard: the console is a local app where everything
worth doing collapses into one ranked DO NOW list, and any action can be handed back
to your local agent CLI with a full context brief. And the loop now closes both
ways — when the dispatched session finishes, opsroom parses the agent's output into
proposed ledger writes ("record $380 collected", "schedule the follow-up", "run
this next") that wait as pending rows for your one-tap approval. Nothing applies
without your tap; agent output is treated as untrusted input (strict verb
whitelist, redaction, caps).

Local-only (SQLite, no network egress, fail-closed secret redaction since it reads
terminal history). `pipx install opsroom-console && opsroom demo` shows a fictional loaded
console in ten seconds. MIT, stdlib-only.

GitHub: https://github.com/malekadjeb-ai/opsroom

## r/OpenAI (or r/ChatGPTCoding)

**Title:** Codex CLI keeps full session logs in ~/.codex/sessions — I built a local dashboard on top of them

**Body:**

If you use Codex CLI, every session is a rollout JSONL under ~/.codex/sessions with
the cwd, every prompt, every tool call. opsroom parses those (read-only), plus
Claude Code logs and your ChatGPT data export, and shows where your agent-hours
actually went — by project, by agent, with the money question attached: did any of
this ship revenue?

Everything local: one SQLite file, no cloud, no accounts, aggressive secret
redaction before anything is stored. `pipx install opsroom-console && opsroom demo`.

GitHub: https://github.com/malekadjeb-ai/opsroom

## r/LocalLLaMA

**Title:** opsroom: local-first, zero-egress console that fuses your AI agent logs, git repos and notes into one dashboard

**Body:**

The r/LocalLLaMA angle: this thing never touches the network. All parsing is local,
the DB is a 600-perm SQLite file that refuses to live in a cloud-sync folder, the
rendered HTML loads zero external resources, and every event passes a fail-closed
secret redactor before it's written. Stdlib-only Python installed straight from the
repo (`pipx install opsroom-console`) — you can read the
entire supply chain in an afternoon.

It reads Claude Code and Codex CLI session logs, ChatGPT/Claude exports, git, and
markdown notes; shows per-agent activity, abandoned work ("open loops"), and
effort-vs-revenue drift. Collectors are ~100-line files with one collect(con) entry
point — a Gemini CLI or Aider collector would be an easy PR.

GitHub: https://github.com/malekadjeb-ai/opsroom
