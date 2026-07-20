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
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config, contextpack, db, ops, redact, state, ventures

MAX_TASK = 300
TS_RE = re.compile(r"^\d{8}-\d{6}-\d+$")  # dispatch ids are timestamps, never paths
_PROCS = {}  # ts -> Popen for dispatches launched by THIS console boot


def build_brief(task: str, venture: str = "", lead_id: int = None,
                kind: str = "do", question: str = "") -> str:
    """The hand-off document: the task, the venture's rails, the lead's context
    when dispatched from a lead row, and the live context pack. kind='ask' adds
    the operator's question + answer protocol; kind='advise' adds the autonomous
    advisor mandate; kind='do' output is unchanged from v0.9."""
    task = (task or "").strip()[:MAX_TASK]
    meta = ventures.VENTURES.get(venture, {})
    lines = ["# DISPATCH — do this now", "", f"TASK: {task}"]
    if kind == "ask" and question:
        lines += ["", "## OPERATOR QUESTION",
                  redact.scrub((question or "").strip())[:500]]
    if venture and meta:
        lines.append(f"VENTURE: {meta.get('label', venture)}")
    rails = [f"- {r}" for r in meta.get("playbook", [])]
    if meta.get("offer"):
        rails.append(f"- Canon offer (quote verbatim, never discount): {meta['offer']}")
    if rails:
        lines += ["", "## RAILS (non-negotiable)"] + rails
    con = db.connect()
    ocon = ops.connect()
    try:
        if lead_id:
            row = ops.lead_get(ocon, lead_id)
            if row:
                lines += ["", "## LEAD CONTEXT",
                          f"- lead id: {row['id']} (use this id in lead_touch proposals)",
                          f"- name: {row['name']}"]
                for label, val in (("phone", row["phone"]), ("service", row["service"]),
                                   ("status", row["status"]), ("note", row["note"])):
                    if val:
                        lines.append(f"- {label}: {val}")
                if row["quoted"]:
                    lines.append(f"- quoted: ${int(row['quoted']):,}")
                hist = ops.lead_touches(ocon, row["name"])
                if hist:
                    lines.append("- recent touches: " + "; ".join(
                        f"{t['ts'][:10]} {t['kind']}" for t in hist))
        lines += ["", "## LIVE OPERATOR CONTEXT", ""]
        lines.append(contextpack.build(con, ocon, state.build_state(con)))
    finally:
        con.close()
        ocon.close()
    from . import proposals
    lines.append(proposals.PROTOCOL_APPENDIX)
    if kind in ("ask", "advise"):
        from . import counsel
        lines.append(counsel.ANSWER_APPENDIX)
        if kind == "advise":
            lines.append(counsel.ADVISE_APPENDIX)
    # fail-closed scrub: the brief is written to disk AND passed to a subprocess, so
    # a secret that slipped into a note/capture/offer never leaves in cleartext.
    return redact.scrub("\n".join(lines))


def _dispatch_dir() -> Path:
    d = config.data_dir() / "dispatch"
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    return d


def agent_ready() -> bool:
    return bool(config.load().get("agent", {}).get("enabled"))


def _open_600(path: Path):
    """Create owner-only from the start — no umask window where the brief/log is
    world-readable before a follow-up chmod."""
    return open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w")


def dispatch(task: str, venture: str = "", on_exit=None, lead_id: int = None,
             kind: str = "do", question: str = "") -> dict:
    """Write the brief; if [agent] enabled, launch the configured CLI on it,
    detached, output to a log file. Returns {brief, log, launched, ts}.
    on_exit (optional) fires from a reaper thread when the agent finishes, so
    open consoles can refresh themselves the moment the work is done."""
    brief = build_brief(task, venture, lead_id=lead_id, kind=kind, question=question)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")  # microseconds: no collision
    ddir = _dispatch_dir()
    bf = ddir / f"{ts}-brief.md"
    with _open_600(bf) as fh:
        fh.write(brief)
    out = {"brief": str(bf), "log": "", "launched": False, "ts": ts}
    agent = config.load().get("agent", {})
    if not agent.get("enabled"):
        return out
    cmd = [str(c) for c in (agent.get("command") or ["claude", "-p"])] + [brief]
    log = ddir / f"{ts}.log"
    with _open_600(log) as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                cwd=str(Path.home()))
    _PROCS[ts] = proc
    with _open_600(ddir / f"{ts}.pid") as fh:  # survives a console restart
        fh.write(str(proc.pid))

    def _reap():
        proc.wait()
        try:
            # harvest the agent's output into PROPOSED ledger writes (pending,
            # one-tap approve on the console). A bad log must never kill the reaper.
            from . import proposals
            ocon = ops.connect()
            try:
                proposals.harvest(ocon, ts)
            finally:
                ocon.close()
        except Exception:
            pass
        try:
            # counsel: fill the answer for REGISTERED ask/advise runs (no-op for
            # ordinary dispatches) — before on_exit so the reload shows the answer
            from . import counsel
            ocon = ops.connect()
            try:
                counsel.harvest(ocon, ts)
            finally:
                ocon.close()
        except Exception:
            pass
        try:
            fire_next(on_exit)  # the work queue: next queued dispatch auto-fires
        except Exception:
            pass
        if on_exit:
            try:
                on_exit()
            except Exception:
                pass
    threading.Thread(target=_reap, daemon=True).start()
    out.update(log=str(log), launched=True)
    return out


def fire_next(on_exit=None) -> bool:
    """Work-queue lite: when the runway is clear ([agent] on, nothing running),
    launch the oldest queued dispatch. Called by the reaper after each run and by
    the serve sync tick (which rescues items stranded by a console restart)."""
    from . import proposals
    if not agent_ready() or running():
        return False
    ocon = ops.connect()
    try:
        p = proposals.pop_queued(ocon)
    finally:
        ocon.close()
    if not p:
        return False
    dispatch(p["task"], p.get("venture", ""), on_exit=on_exit,
             lead_id=p.get("lead"))
    return True


def status(ts: str) -> str:
    """'' (brief only) · 'running' · 'done' · 'exit N'. Works across console
    restarts: falls back to the pid file, then to log existence."""
    if not TS_RE.match(ts or ""):
        return ""
    p = _PROCS.get(ts)
    if p is not None:
        rc = p.poll()
        if rc is None:
            return "running"
        return "done" if rc == 0 else f"exit {rc}"
    d = config.data_dir() / "dispatch"
    pidf = d / f"{ts}.pid"
    if pidf.is_file():
        try:
            os.kill(int(pidf.read_text().strip()), 0)
            return "running"  # launched by a previous boot, still alive
        except (ValueError, OSError):
            pass
    return "done" if (d / f"{ts}.log").exists() else ""


def tail(ts: str, max_bytes: int = 4000) -> str:
    """The last chunk of a dispatch log, scrubbed. ts is validated — this function
    can never be steered to an arbitrary path."""
    if not TS_RE.match(ts or ""):
        return ""
    log = config.data_dir() / "dispatch" / f"{ts}.log"
    if not log.is_file():
        return ""
    size = log.stat().st_size
    with open(log, "rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
        txt = fh.read().decode(errors="replace")
    if size > max_bytes:
        txt = "…" + txt.split("\n", 1)[-1]
    # agent output is NEW text that never passed the write-path scrub — scrub here
    return redact.scrub(txt)


def running() -> list:
    """Live dispatches from this boot, for the AGENTS RUNNING panel."""
    out = []
    for ts, p in list(_PROCS.items()):
        if p.poll() is None:
            out.append({"ts": ts, "task": _task_of(ts)})
    return sorted(out, key=lambda r: r["ts"], reverse=True)


def _task_of(ts: str) -> str:
    bf = config.data_dir() / "dispatch" / f"{ts}-brief.md"
    try:
        for line in bf.read_text().splitlines():
            if line.startswith("TASK: "):
                return line[6:]
    except OSError:
        pass
    return ""


def recent(limit: int = 8) -> list:
    """Latest dispatches (newest first) with live status + scrubbed log tail,
    for the /do page history."""
    d = config.data_dir() / "dispatch"
    if not d.is_dir():
        return []
    briefs = sorted(d.glob("*-brief.md"), reverse=True)[:limit]
    out = []
    for b in briefs:
        ts = b.name[:-len("-brief.md")]
        log = d / f"{ts}.log"
        out.append({"ts": b.name[:15], "tsid": ts, "task": _task_of(ts),
                    "log": log.name if log.exists() else "",
                    "status": status(ts), "tail": tail(ts, 2000)})
    return out
