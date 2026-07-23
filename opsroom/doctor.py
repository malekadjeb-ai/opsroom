"""`opsroom doctor` — one command that says why something is quiet.

Read-only, with one exception: `--fire` runs an end-to-end test dispatch
through the REAL configured [agent] command — the whole loop the silent nights
broke (resolve → launch → log → reap → runs ledger) — and prints an
exit/duration/output-size verdict. It only ever runs YOUR configured command
on a synthetic brief, and refuses when [agent] is disabled.

The base checks: config, the two databases and their permissions, the [agent]
wiring (including the launchd bare-PATH trap that silently killed dispatches
before v0.10.1), the advisor schedule, and the last advisor error breadcrumb.
Exit 0 = everything load-bearing passes; 1 = at least one FAIL.
"""
import os
import stat
import time
from pathlib import Path

from . import config

FIRE_TASK = "Doctor self-test: reply with the single word OK and nothing else."
FIRE_POLL_S = 2


def _line(ok, label, detail="", warn=False):
    tag = "PASS" if ok else ("WARN" if warn else "FAIL")
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
    return ok or warn


def _fire() -> bool:
    """The end-to-end test dispatch. True = the whole loop works."""
    from . import dispatch, ops, runs
    r = dispatch.dispatch(FIRE_TASK, kind="doctor")
    if not r.get("launched"):
        _line(False, "fire", r.get("error") or "dispatch did not launch")
        return False
    print(f"  [....] fire: launched pid via {config.load()['agent']['command'][0]}"
          f" — waiting (ts {r['ts']})")
    budget = min(runs._timeout_seconds() or 300, 300) + 15  # watchdog + grace
    deadline = time.monotonic() + budget
    row = None
    while time.monotonic() < deadline:
        ocon = ops.connect()
        try:
            row = runs.get(ocon, r["ts"])
        finally:
            ocon.close()
        if row and row["outcome"] not in ("running",):
            break
        time.sleep(FIRE_POLL_S)
    if not row or row["outcome"] == "running":
        _line(False, "fire", f"no verdict after {budget:.0f}s — check the log: {r['log']}")
        return False
    ok = row["outcome"] == "done"
    dur = f"{row['duration_s']:.1f}s" if row["duration_s"] is not None else "?"
    nb = row["stdout_bytes"] if row["stdout_bytes"] is not None else 0
    _line(ok, "fire", f"exit {row['exit_code']} · {dur} · {nb:,} bytes"
          + ("" if ok else f" ({row['outcome']})"))
    if not ok and row["stderr_tail"]:
        for tl in row["stderr_tail"].strip().splitlines()[-3:]:
            print(f"         {tl[:160]}")
    return ok


def run(fire: bool = False) -> int:
    from . import counsel, db, dispatch, inbox, ops
    good = True
    print("opsroom doctor\n")

    # ---- config
    cfg_path = config.config_dir() / "config.toml"
    try:
        cfg = config.load(force=True)
        good &= _line(True, "config parses", str(cfg_path))
    except Exception as e:
        _line(False, "config parses", f"{cfg_path}: {e}")
        print("\nfix the config first — nothing below is meaningful until it parses.")
        return 1
    good &= _line(bool(config.goal_amount(cfg)), "goal set",
                  cfg["goal"].get("label") or "no [goal] — the money bar is blind",
                  warn=True)
    good &= _line(bool(cfg["ventures"]), "ventures configured",
                  f"{len(cfg['ventures'])} defined" if cfg["ventures"]
                  else "run `opsroom init`", warn=True)

    # ---- the link registry (resources-per-task: rows carry their sources)
    from . import resources, ventures as _v
    n_global = len(resources.global_links())
    n_vlinks = sum(len(resources.venture_links(k)) for k in _v.VENTURES)
    _line(bool(n_global), "[links] registry",
          f"{n_global} global link{'s' if n_global != 1 else ''}"
          + (f" + {n_vlinks} venture" if n_vlinks else "")
          if n_global or n_vlinks else
          'empty — task rows can carry every source they need: add e.g. '
          'mail_drafts / leads / calendar under [links], and links = '
          '{gbp = "https://…"} on a [[venture]]', warn=True)

    # ---- databases + permissions
    for name, p in (("activity.db", db.DB_PATH), ("ops.db", ops.db_path())):
        if p.exists():
            mode = stat.S_IMODE(p.stat().st_mode)
            good &= _line(mode == 0o600, f"{name} perms",
                          f"{p} is {oct(mode)}" + ("" if mode == 0o600 else " (want 600)"))
        else:
            _line(True, f"{name}", "not created yet (first run does)", warn=True)

    # ---- [agent] wiring
    agent = cfg["agent"]
    if not agent.get("enabled"):
        _line(True, "[agent] dispatch", "disabled — briefs still write; run "
              "`opsroom connect` for one-tap launch", warn=True)
    else:
        cmd = agent.get("command") or []
        if not cmd:
            good &= _line(False, "[agent] command", "enabled but empty")
        else:
            resolved = dispatch._resolve_exe(cmd[0])
            if Path(resolved).is_absolute():
                via_path = bool(__import__("shutil").which(cmd[0]))
                hint = "" if via_path else \
                    ("resolved outside PATH — fine here, but launchd/systemd " \
                     "consoles get a bare PATH; consider the absolute path in config")
                good &= _line(True, "[agent] command resolves", f"{cmd[0]} → {resolved}"
                              + (f" ({hint})" if hint else ""))
            else:
                good &= _line(False, "[agent] command resolves",
                              f"'{cmd[0]}' not found — dispatches will die into the log. "
                              "Use an absolute path in [agent] command.")
        mode = agent.get("advise", "off")
        ok_mode = mode == "off" or mode == "daily" or (
            isinstance(mode, int) and not isinstance(mode, bool) and 2 <= mode <= 168)
        good &= _line(ok_mode, "advise mode",
                      f"{mode!r}" + ("" if ok_mode else " — want 'off', 'daily', or hours 2..168"))

    # ---- advisor breadcrumbs + drops (only when the ledger exists)
    if ops.db_path().exists():
        ocon = ops.connect()
        try:
            err = ops.kv_get(ocon, "advise_error", "")
            good &= _line(not err, "last advisor run",
                          err or "no error breadcrumb")
            last = ops.kv_get(ocon, "advise_last", "")
            if last:
                _line(True, "advisor last fired", last, warn=True)
        finally:
            ocon.close()
    for label, p in (("leads drop", inbox.leads_drop_path()),
                     ("replies drop", inbox.replies_drop_path())):
        _line(True, label, str(p) + ("" if p.exists() else " (no file yet — that's fine)"),
              warn=True)

    # ---- --fire: the end-to-end loop, through the real configured command
    if fire:
        print()
        if not cfg["agent"].get("enabled"):
            _line(False, "fire", "--fire needs [agent] enabled — run `opsroom connect`")
            good = False
        else:
            good &= _fire()

    print()
    if good:
        print("all load-bearing checks pass.")
        return 0
    print("at least one FAIL above — fix it and re-run.")
    return 1
