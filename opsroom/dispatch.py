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
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, contextpack, db, ops, redact, runs, state, ventures

MAX_TASK = 300
TS_RE = re.compile(r"^\d{8}-\d{6}-\d+$")  # dispatch ids are timestamps, never paths
_PROCS = {}  # ts -> Popen for dispatches launched by THIS console boot
RETRY_BACKOFF_S = 60  # one automatic retry for advise runs that die at 0 bytes
WATCHDOG_GRACE_S = 10  # SIGTERM → this long → SIGKILL


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


_EXTRA_BINS = (Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"),
               Path("/usr/local/bin"))


def _resolve_exe(name: str) -> str:
    """Resolve the agent CLI the way a login shell would. launchd/systemd start
    the always-on console with a bare PATH (/usr/bin:/bin:...), which silently
    broke every dispatch: Popen(['claude', ...]) raised FileNotFoundError into a
    0-byte log. Absolute paths pass through; then PATH; then the usual user bins."""
    p = Path(name).expanduser()
    if p.is_absolute():
        return str(p)
    found = shutil.which(name)
    if found:
        return found
    for d in _EXTRA_BINS:
        cand = d / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return name  # let the launch fail loudly into the log below


def _open_600(path: Path):
    """Create owner-only from the start — no umask window where the brief/log is
    world-readable before a follow-up chmod."""
    return open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w")


def _killpg(proc, sig) -> None:
    """Signal the run's whole process group (start_new_session gave it one), so
    the agent's children die with it. Falls back to the pid alone."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except OSError:
        try:
            proc.send_signal(sig)
        except OSError:
            pass


def _wait_watchdog(proc, timeout_s: float, log: Path):
    """proc.wait() with a deadline. On expiry: SIGTERM the group, grace, SIGKILL,
    and leave a visible marker in the log so the /do tail explains the kill.
    Returns (exit_code, timed_out)."""
    if timeout_s <= 0:
        return proc.wait(), False
    try:
        return proc.wait(timeout=timeout_s), False
    except subprocess.TimeoutExpired:
        pass
    _killpg(proc, signal.SIGTERM)
    try:
        rc = proc.wait(timeout=WATCHDOG_GRACE_S)
    except subprocess.TimeoutExpired:
        _killpg(proc, signal.SIGKILL)
        rc = proc.wait()
    try:
        with open(log, "a") as fh:  # log already exists at 0600
            fh.write(f"\nopsroom watchdog: killed after {timeout_s / 60:.0f}m "
                     f"(config [agent] timeout_minutes)\n")
    except OSError:
        pass
    return rc, True


def dispatch(task: str, venture: str = "", on_exit=None, lead_id: int = None,
             kind: str = "do", question: str = "", attempt: int = 1,
             retry_of: str = None) -> dict:
    """Write the brief; if [agent] enabled, launch the configured CLI on it,
    detached, output to a log file. Returns {brief, log, launched, ts}.
    on_exit (optional) fires from a reaper thread when the agent finishes, so
    open consoles can refresh themselves the moment the work is done.
    Every launch lands in the runs ledger; the reaper records the exit."""
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
    base = [str(c) for c in (agent.get("command") or ["claude", "-p"])]
    base[0] = _resolve_exe(base[0])
    stdin_mode = agent.get("input", "argv") == "stdin"
    cmd = base if stdin_mode else base + [brief]
    log = ddir / f"{ts}.log"
    with _open_600(log) as fh:
        try:
            proc = subprocess.Popen(
                cmd, stdout=fh, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if stdin_mode else subprocess.DEVNULL,
                start_new_session=True, cwd=str(Path.home()))
        except OSError as e:
            # never a silent 0-byte log: the /do tail must explain what happened
            fh.write(f"opsroom: could not launch agent command {cmd[0]!r}: {e}\n"
                     f"hint: the always-on console (launchd/systemd) runs with a "
                     f"minimal PATH — use an absolute path in [agent] command.\n")
            out["error"] = str(e)
            return out
    if stdin_mode:
        try:
            # [agent] input = "stdin": pipe the brief for CLIs that don't take
            # argv prompts. A CLI that closes stdin early must not kill dispatch.
            proc.stdin.write(brief.encode())
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    _PROCS[ts] = proc
    with _open_600(ddir / f"{ts}.pid") as fh:  # survives a console restart
        fh.write(str(proc.pid))
    t0 = time.monotonic()
    try:
        ocon = ops.connect()
        try:
            runs.record_launch(ocon, ts, kind=kind, task=task, venture=venture,
                               pid=proc.pid, attempt=attempt, retry_of=retry_of)
        finally:
            ocon.close()
    except Exception:
        pass  # a ledger hiccup must never block a launch; record_exit self-heals
    timeout_s = runs._timeout_seconds()

    def _reap():
        rc, timed_out = _wait_watchdog(proc, timeout_s, log)
        dur = time.monotonic() - t0
        try:
            nbytes = log.stat().st_size
        except OSError:
            nbytes = 0
        if timed_out:
            outcome = "killed"
        elif nbytes == 0:
            outcome = "dead"
        else:
            outcome = "done" if rc == 0 else "failed"
        try:
            # record the exit FIRST — a harvest crash must never lose the fact
            ocon = ops.connect()
            try:
                runs.record_exit(ocon, ts, rc, dur, nbytes, tail(ts, 1000), outcome)
            finally:
                ocon.close()
        except Exception:
            pass
        if outcome == "dead" and kind == "advise" and attempt == 1:
            # the one unattended run gets ONE automatic retry; operator-launched
            # runs get the red banner instead. Both attempts stay in the ledger.
            try:
                time.sleep(RETRY_BACKOFF_S)
                r2 = dispatch(task, venture, on_exit=on_exit, lead_id=lead_id,
                              kind=kind, question=question, attempt=2, retry_of=ts)
                if r2.get("launched"):
                    from . import counsel
                    ocon = ops.connect()
                    try:
                        counsel.register(ocon, r2["ts"], "advise")
                    finally:
                        ocon.close()
            except Exception:
                pass
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


def _status_from_row(row) -> str:
    """Human status from a runs-ledger row ('' when the row can't say)."""
    if row is None:
        return ""
    oc = row["outcome"]
    if oc == "killed":
        return "killed (timeout)"
    if oc == "cancelled":
        return "cancelled"
    if oc == "dead":
        return f"exit {row['exit_code']} · 0 bytes" if row["exit_code"] is not None \
            else "died (no output)"
    if row["exit_code"] is not None:
        return "done" if row["exit_code"] == 0 else f"exit {row['exit_code']}"
    return ""  # running/orphaned/unknown: let the live checks decide


def cancel(ts: str) -> bool:
    """Operator cancel. Records 'cancelled' FIRST (the reaper never downgrades
    it), then signals: this boot's runs get a group SIGTERM with a SIGKILL
    escalation thread; cross-boot runs get a best-effort pid-file SIGTERM —
    and ONLY while our own .pid file vouches for the number (pid-reuse guard)."""
    if not TS_RE.match(ts or ""):
        return False
    try:
        ocon = ops.connect()
        try:
            marked = runs.mark_cancelled(ocon, ts)
        finally:
            ocon.close()
    except Exception:
        marked = False
    p = _PROCS.get(ts)
    if p is not None and p.poll() is None:
        _killpg(p, signal.SIGTERM)

        def _escalate():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _killpg(p, signal.SIGKILL)
        threading.Thread(target=_escalate, daemon=True).start()
        return True
    pidf = config.data_dir() / "dispatch" / f"{ts}.pid"
    if pidf.is_file():
        try:
            os.kill(int(pidf.read_text().strip()), signal.SIGTERM)
            return True
        except (ValueError, OSError):
            pass
    return marked


def status(ts: str) -> str:
    """'' (brief only) · 'running' · 'done' · 'exit N' · 'killed (timeout)' ·
    'cancelled'. Works across console restarts: this boot's Popen first, then
    the pid file, then the runs ledger (which finally remembers exit codes a
    restart used to erase), then log existence for pre-0.12 runs."""
    if not TS_RE.match(ts or ""):
        return ""
    p = _PROCS.get(ts)
    if p is not None and p.poll() is None:
        return "running"
    d = config.data_dir() / "dispatch"
    if p is None:
        pidf = d / f"{ts}.pid"
        if pidf.is_file():
            try:
                os.kill(int(pidf.read_text().strip()), 0)
                return "running"  # launched by a previous boot, still alive
            except (ValueError, OSError):
                pass
    try:
        ocon = ops.connect()
        try:
            s = _status_from_row(runs.get(ocon, ts))
        finally:
            ocon.close()
        if s:
            return s
    except Exception:
        pass
    if p is not None:  # this boot, ledger silent: the Popen still knows
        rc = p.poll()
        return "done" if rc == 0 else f"exit {rc}"
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
    """Latest dispatches (newest first) with live status + scrubbed log tail +
    the runs-ledger accounting (exit code, duration, output size), for the /do
    page history. One ledger query for the whole batch."""
    d = config.data_dir() / "dispatch"
    if not d.is_dir():
        return []
    briefs = sorted(d.glob("*-brief.md"), reverse=True)[:limit]
    ids = [b.name[:-len("-brief.md")] for b in briefs]
    rows = {}
    try:
        ocon = ops.connect()
        try:
            rows = runs.by_ts(ocon, ids)
        finally:
            ocon.close()
    except Exception:
        pass
    out = []
    for b, ts in zip(briefs, ids):
        log = d / f"{ts}.log"
        row = rows.get(ts)
        st = "running" if (ts in _PROCS and _PROCS[ts].poll() is None) \
            else (_status_from_row(row) or status(ts))
        out.append({"ts": b.name[:15], "tsid": ts, "task": _task_of(ts),
                    "log": log.name if log.exists() else "",
                    "status": st, "tail": tail(ts, 2000),
                    "exit_code": row["exit_code"] if row else None,
                    "duration_s": row["duration_s"] if row else None,
                    "stdout_bytes": row["stdout_bytes"] if row else None,
                    "outcome": row["outcome"] if row else ""})
    return out
