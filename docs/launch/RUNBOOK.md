# Launch-morning runbook

Repo is **public and live**: https://github.com/malekadjeb-ai/opsroom
Everything below is the human-in-the-loop launch. Do it on a **Tue/Wed/Thu, 6:00–8:00 AM
Pacific**. Block 4–6 hours after — you must answer comments fast, that's the #1 lever.

## Already done (no action needed)
- [x] Code pushed, repo public, v0.3.0 tagged + released, CI green on public repo
- [x] `pipx install git+https://github.com/malekadjeb-ai/opsroom` verified on a clean venv
- [x] Social preview card uploaded, topics set, demo GIF + screenshots in README
- [x] 2 secret-scanning alerts (fake test fixtures) dismissed as used-in-tests

## T-0: the posts (in this order, ~30 min apart)

1. **Show HN** — copy title + body from `show-hn.md`. Submit at news.ycombinator.com/submit,
   then immediately paste the first comment. Do NOT ask anyone to upvote.
2. **X thread** (~30 min later) — post `x-thread.md`, tweet 1 with `demo.gif` attached.
3. **Reddit** — `reddit.md`, three separate posts, each its own subreddit and angle:
   r/ClaudeAI, r/OpenAI (or r/ChatGPTCoding), r/LocalLLaMA. Never paste the same body twice.

## T-0 through T+4h
- Sit on HN + Reddit. Answer every comment within minutes. Be technical, be humble,
  fix small things live and reply "shipped."
- If HN gains traction by mid-morning, submit to Lobsters (show tag).

## T+1 day
- Ship one visible improvement from feedback, comment about it (re-spikes threads).
- Submit to newsletters: TLDR, Console.dev, Changelog News.

## Two decisions still open (yours)
- **PyPI name**: `opsroom` is taken. Install is the git URL (works). If you want a clean
  `pip install <name>`, register e.g. `opsroom-console` before posting so the HN crowd
  gets a one-word install.
- **Author identity**: `pyproject.toml` carries your real name + email publicly. Fine for
  a personal project; just know it's visible.

## Want me to drive it?
Ping me on a valid launch morning and I'll post all three via your browser while you watch,
then help you answer comments in real time. I did NOT auto-fire them: a Show HN posted while
you're asleep dies in /new, and you need to be present for the first hours regardless.
