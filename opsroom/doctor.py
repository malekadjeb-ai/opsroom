"""`opsroom doctor` — one command that says why something is quiet.

Read-only. Checks the config, the two databases and their permissions, the
[agent] wiring (including the launchd bare-PATH trap that silently killed
dispatches before v0.10.1), the advisor schedule, and the last advisor error
breadcrumb. Exit 0 = everything load-bearing passes; 1 = at least one FAIL.
"""
import os
import stat
from pathlib import Path

from . import config


def _line(ok, label, detail="", warn=False):
    tag = "PASS" if ok else ("WARN" if warn else "FAIL")
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
    return ok or warn


def run() -> int:
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

    print()
    if good:
        print("all load-bearing checks pass.")
        return 0
    print("at least one FAIL above — fix it and re-run.")
    return 1
