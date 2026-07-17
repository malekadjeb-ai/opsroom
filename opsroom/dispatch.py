"""Agent dispatch — close the loop in BOTH directions. opsroom already reads what
your AI agents did; this hands work back to them. Every action on the console gets
a "do it" brief (the task + your live context pack + your config rails), and one
tap can launch your local agent CLI on it.

Security posture (this can execute a local program, so it's opt-in and rigid):
  - DISABLED by default. Enable per machine in config.toml:
        [agent]
        enabled = true
        command = ["claude", "-p"]     # your agent CLI; brief is appended as ONE argv
  - The command comes ONLY from your config file — never from the request. The
    brief is passed as a single argv element (no shell, no interpolation).
  - Launch requires the console's CSRF-gated POST, loopback only, like every write.
  - Briefs and logs land in <data>/dispatch/ at 600 perms. Nothing leaves the
    machine unless YOUR agent command sends it somewhere.
"""
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config, contextpack, db, ops, state, ventures

MAX_TASK = 300


def build_brief(task: str, venture: str = "") -> str:
    """The hand-off document: the task, the venture's rails, the live context pack."""
    task = (task or "").strip()[:MAX_TASK]
    meta = ventures.VENTURES.get(venture, {})
    lines = ["# DISPATCH — do this now", "", f"TASK: {task}"]
    if venture and meta:
        lines.append(f"VENTURE: {meta.get('label', venture)}")
    rails = [f"- {r}" for r in meta.get("playbook", [])]
    if meta.get("offer"):
        rails.append(f"- Canon offer (quote verbatim, never discount): {meta['offer']}")
    if rails:
        lines += ["", "## RAILS (non-negotiable)"] + rails
    lines += ["", "## LIVE OPERATOR CONTEXT", ""]
    con = db.connect()
    ocon = ops.connect()
    try:
        lines.append(contextpack.build(con, ocon, state.build_state(con)))
    finally:
        con.close()
        ocon.close()
    return "\n".join(lines)


def _dispatch_dir() -> Path:
    d = config.data_dir() / "dispatch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def agent_ready() -> bool:
    return bool(config.load().get("agent", {}).get("enabled"))


def dispatch(task: str, venture: str = "") -> dict:
    """Write the brief; if [agent] enabled, launch the configured CLI on it,
    detached, output to a log file. Returns {brief, log, launched}."""
    brief = build_brief(task, venture)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ddir = _dispatch_dir()
    bf = ddir / f"{ts}-brief.md"
    bf.write_text(brief)
    bf.chmod(0o600)
    out = {"brief": str(bf), "log": "", "launched": False}
    agent = config.load().get("agent", {})
    if not agent.get("enabled"):
        return out
    cmd = [str(c) for c in (agent.get("command") or ["claude", "-p"])] + [brief]
    log = ddir / f"{ts}.log"
    with open(log, "w") as fh:
        subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True,
                         cwd=str(Path.home()))
    log.chmod(0o600)
    out.update(log=str(log), launched=True)
    return out


def recent(limit: int = 8) -> list:
    """Latest dispatches (brief files, newest first) for the /do page."""
    d = config.data_dir() / "dispatch"
    if not d.is_dir():
        return []
    briefs = sorted(d.glob("*-brief.md"), reverse=True)[:limit]
    out = []
    for b in briefs:
        task = ""
        for line in b.read_text().splitlines():
            if line.startswith("TASK: "):
                task = line[6:]
                break
        log = d / b.name.replace("-brief.md", ".log")
        out.append({"ts": b.name[:15], "task": task, "log": log.name if log.exists() else ""})
    return out
