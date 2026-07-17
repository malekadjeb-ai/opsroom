# Launch checklist — target: top of GitHub trending (daily)

> **STATUS 2026-07-17:** repo taken PRIVATE by the maintainer's call after a ~10-minute public
> window (nothing was posted anywhere). Relaunch gate: security audit clean + v0.3
> serve (write-back app) polished. When relaunching: flip visibility public, verify
> CI badge renders, then resume at "Launch morning" below. The v0.2.0 release,
> topics, GIF, and screenshots are already in place.

Reality check on the number: #1 daily overall needs roughly 400-800 stars in 24h;
#1 in Python needs roughly 150-300. That volume comes from HN front page + Reddit +
X landing the same morning. The repo just has to not fumble the traffic.

## Gate 0 — the maintainer's call (the only open decision)

- [ ] Launch on v0.2.0 (multi-agent, read-only console) — OR hold for the v0.3
      write-back port from private cc. The "it must feel like a tool" bar is yours.
      Note: the demo + sitrep + BY AGENT already *do* things (send queues, tap-to-dial,
      one-move); this is not the bare dashboard you rejected.

## T-2 days

- [ ] `brew install vhs && vhs docs/launch/demo.tape` → demo.gif; put it at the top
      of README (`![opsroom demo](docs/launch/demo.gif)`).
- [ ] Screenshot the demo console ACTIVITY tab (BY AGENT table visible) → second image.
- [ ] Push to GitHub. Add topics: `claude-code`, `codex`, `chatgpt`, `ai-agents`,
      `developer-tools`, `local-first`, `dashboard`, `productivity`, `sqlite`.
- [ ] Repo Settings → Social preview: upload a 1280x640 card (title + tagline + console shot).
- [ ] Verify CI is green on the public repo (badge in README:
      `![ci](https://github.com/malekadjeb-ai/opsroom/actions/workflows/ci.yml/badge.svg)`).
- [ ] Tag v0.2.0, create a GitHub Release with the demo GIF embedded.
- [ ] Publish to PyPI (`pipx install opsroom` in the README must actually work):
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
