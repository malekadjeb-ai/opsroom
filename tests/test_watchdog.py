#!/usr/bin/env python3
"""Watchdog gate: a run that exceeds [agent] timeout_minutes is killed (whole
process group), the kill is a recorded fact ('killed', never a silent hang),
the log says why, and status() reports it across a restart. Exit 0 = green.
Fictional fixtures."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        fake = ROOT / "tests" / "fake_agent.py"
        (cfg_dir / "config.toml").write_text(f'''
[[venture]]
key = "meridian"
label = "Meridian Consulting"

[agent]
enabled = true
command = ["{sys.executable}", "{fake}"]
timeout_minutes = 0.02
''')
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        os.environ["OPSROOM_FAKE_SLEEP"] = "60"
        for k in ("OPSROOM_FAKE_EXIT", "OPSROOM_FAKE_SILENT"):
            os.environ.pop(k, None)
        from opsroom import config, db, dispatch, ops, runs, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        assert abs(runs._timeout_seconds() - 1.2) < 0.01, runs._timeout_seconds()

        ocon = ops.connect()
        r = dispatch.dispatch("Hangs forever", "meridian")
        assert r["launched"], r
        row = None
        for _ in range(200):  # 1.2s timeout + up to 10s TERM grace
            row = runs.get(ocon, r["ts"])
            if row and row["outcome"] not in ("running",):
                break
            time.sleep(0.1)
        assert row and row["outcome"] == "killed", dict(row) if row else None
        assert row["exit_code"] is not None  # negative = died by signal
        # the process (group) is actually gone
        try:
            os.kill(row["pid"], 0)
            alive = True
        except OSError:
            alive = False
        assert not alive, f"watchdog reported a kill but pid {row['pid']} lives"
        # the log explains the kill; status reports it, even across a restart
        assert "watchdog" in dispatch.tail(r["ts"]), dispatch.tail(r["ts"])
        dispatch._PROCS.clear()
        assert dispatch.status(r["ts"]) == "killed (timeout)", dispatch.status(r["ts"])
        # killed runs alert
        assert any(f["ts"] == r["ts"] for f in runs.unacked_failures(ocon))
        ocon.close()
        os.environ.pop("OPSROOM_FAKE_SLEEP")

    print("watchdog gate: over-timeout runs killed, recorded, explained, alerted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
