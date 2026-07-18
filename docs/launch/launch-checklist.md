# Launch checklist — target: top of GitHub trending (daily)

> **STATUS 2026-07-18 (current):** repo is PUBLIC. **v0.7.0** released on GitHub, CI green,
> topics set, two security audits clean, hero GIF live. Nothing has been posted anywhere yet.
> Launch scheduled **Tue 2026-07-21, 8:00 AM CT** — resume at "Launch morning" below.
> The product grew far past a dashboard since v0.3.0: live SEARCH, a reply DRAFTER,
> leads/replies inbox, real per-venture P&L + simulator, agent DISPATCH (write-back loop),
> a live AGENTS-RUNNING panel, and a reorganized one-ranked-stack console.
> Remaining pre-launch items: PyPI upload of v0.7.0 (maintainer's token), fresh-machine
> install test, social-preview upload check. Screenshots regenerated from the current console.

Reality check on the number: #1 daily overall needs roughly 400-800 stars in 24h;
#1 in Python needs roughly 150-300. That volume comes from HN front page + Reddit +
X landing the same morning. The repo just has to not fumble the traffic.

## Gate 0 — the maintainer's call (RESOLVED)

- [x] Decided: launch on the current release (**v0.7.0** — operator console: ranked
      DO NOW stack, search, drafter, leads/replies inbox, P&L + simulator, agent
      dispatch, live sessions). The "it must feel like a tool" bar is long past met.

## T-2 days

- [ ] `brew install vhs && vhs docs/launch/demo.tape` → demo.gif; put it at the top
      of README (`![opsroom demo](docs/launch/demo.gif)`).
- [ ] Screenshot the demo console ACTIVITY tab (BY AGENT table visible) → second image.
- [ ] Push to GitHub. Add topics: `claude-code`, `codex`, `chatgpt`, `ai-agents`,
      `developer-tools`, `local-first`, `dashboard`, `productivity`, `sqlite`.
- [ ] Repo Settings → Social preview: upload a 1280x640 card (title + tagline + console shot).
- [ ] Verify CI is green on the public repo (badge in README:
      `![ci](https://github.com/malekadjeb-ai/opsroom/actions/workflows/ci.yml/badge.svg)`).
- [x] Tagged through v0.7.0, GitHub Releases created, demo GIF embedded.
- [ ] Publish v0.7.0 to PyPI (`pipx install opsroom-console` must serve the latest):
      `python -m build && twine upload dist/*`.
- [ ] Fresh-machine test: `pipx install opsroom-console && opsroom demo` on a clean user account.

## Launch morning (Tue/Wed/Thu, 6:00-8:00 AM Pacific)

- [ ] Submit Show HN (docs/launch/show-hn.md), post first comment immediately.
- [ ] 30 min later: X thread (docs/launch/x-thread.md) with the GIF.
- [ ] Reddit posts (docs/launch/reddit.md): r/ClaudeAI, r/OpenAI or r/ChatGPTCoding,
      r/LocalLLaMA — each its own angle, never verbatim cross-posts.
- [ ] Stay at the keyboard 4-6 hours answering every HN/Reddit comment fast.
      Response speed is the #1 controllable ranking factor.
- [ ] If HN traction: submit to Lobsters (show tag) in the afternoon.

## T+1

- [ ] Ship one visible improvement from launch-day feedback and comment about it —
      "shipped your suggestion" comments re-spike threads.
- [ ] Newsletter pitches: TLDR, Console.dev, Changelog News (all take submissions).
