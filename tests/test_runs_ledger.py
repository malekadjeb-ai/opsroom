#!/usr/bin/env python3
"""Runs-ledger gate: every reaped dispatch lands in ops.db with pid, exit code,
duration, output size, and a scrubbed tail; a nonzero exit SURVIVES a console
restart (v0.11 read every restart-orphaned run as "done"); pre-0.12 ledgers
grow the table cleanly; disk-only runs backfill as 'unknown' and never alert.
Exit 0 = green. Fictional fixtures."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[[venture]]
key = "meridian"
label = "Meridian Consulting"
'''


def _agent_block():
    fake = ROOT / "tests" / "fake_agent.py"
    return f'''
[agent]
enabled = true
command = ["{sys.executable}", "{fake}"]
'''


def _wait_outcome(ocon, runs, ts, want, tries=100):
    for _ in range(tries):
        row = runs.get(ocon, ts)
        if row and row["outcome"] in want:
            return row
        time.sleep(0.1)
    return runs.get(ocon, ts)


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG + _agent_block())
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        for k in ("OPSROOM_FAKE_EXIT", "OPSROOM_FAKE_SILENT", "OPSROOM_FAKE_SLEEP"):
            os.environ.pop(k, None)
        from opsroom import config, db, dispatch, ops, runs, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        # a clean run: full accounting
        r = dispatch.dispatch("Work the quote backlog", "meridian")
        assert r["launched"], r
        row = _wait_outcome(ocon, runs, r["ts"], ("done",))
        assert row and row["outcome"] == "done", dict(row) if row else None
        assert row["kind"] == "do" and row["venture"] == "meridian"
        assert isinstance(row["pid"], int) and row["pid"] > 0
        assert row["exit_code"] == 0 and row["duration_s"] > 0
        assert row["stdout_bytes"] > 0 and "Proposing" in row["stderr_tail"]
        assert dispatch.status(r["ts"]) == "done"

        # a failing run: the exit code is a recorded fact...
        os.environ["OPSROOM_FAKE_EXIT"] = "3"
        r2 = dispatch.dispatch("Doomed but talkative", "meridian")
        row2 = _wait_outcome(ocon, runs, r2["ts"], ("failed",))
        assert row2 and row2["exit_code"] == 3 and row2["stdout_bytes"] > 0, \
            dict(row2) if row2 else None
        assert dispatch.status(r2["ts"]) == "exit 3"
        os.environ.pop("OPSROOM_FAKE_EXIT")
        # ...that SURVIVES a console restart (the v0.11 amnesia bug)
        dispatch._PROCS.clear()
        assert dispatch.status(r2["ts"]) == "exit 3", \
            f"restart erased the exit code: {dispatch.status(r2['ts'])!r}"
        # and /do history carries the accounting cross-boot
        hist = {h["tsid"]: h for h in dispatch.recent()}
        assert hist[r2["ts"]]["exit_code"] == 3 and hist[r2["ts"]]["outcome"] == "failed"
        # failed runs alert; done runs don't; ack clears
        fails = runs.unacked_failures(ocon)
        assert [f["ts"] for f in fails] == [r2["ts"]], [dict(f) for f in fails]
        runs.ack(ocon, r2["ts"])
        assert runs.unacked_failures(ocon) == []

        # backfill: a disk-only run (no pid, no row — pre-0.12, or demo seeds)
        # becomes 'unknown' and NEVER alerts — we can't know it failed
        ddir = Path(os.environ["OPSROOM_DATA_DIR"]) / "dispatch"
        ts3 = "20260101-000000-1"
        (ddir / f"{ts3}-brief.md").write_text("# DISPATCH — do this now\n\nTASK: old run\n")
        (ddir / f"{ts3}.log").write_text("some historical output\n")
        runs.sweep(ocon)
        row3 = runs.get(ocon, ts3)
        assert row3 and row3["outcome"] == "unknown" and row3["exit_code"] is None
        assert row3["stdout_bytes"] > 0
        assert runs.unacked_failures(ocon) == [], "an unknown run must never alert"
        # brief-only (agent was disabled): no log, no row at all
        ts4 = "20260101-000001-1"
        (ddir / f"{ts4}-brief.md").write_text("# DISPATCH\n\nTASK: never launched\n")
        runs.sweep(ocon)
        assert runs.get(ocon, ts4) is None, "brief-only run must not get a row"

        # orphan finalize: a 'running' row whose pid is gone — 0 bytes = dead
        # (this is the silent-night signature, and it DOES alert)
        ts5 = "20260101-000002-1"
        (ddir / f"{ts5}-brief.md").write_text("# DISPATCH\n\nTASK: died silently\n")
        (ddir / f"{ts5}.log").write_text("")
        runs.record_launch(ocon, ts5, kind="advise", task="died silently", pid=999999)
        runs.sweep(ocon)
        row5 = runs.get(ocon, ts5)
        assert row5 and row5["outcome"] == "dead", dict(row5) if row5 else None
        assert any(f["ts"] == ts5 for f in runs.unacked_failures(ocon)), \
            "a dead run must alert"
        # same but WITH output = orphaned (console died mid-run) — no alert
        ts6 = "20260101-000003-1"
        (ddir / f"{ts6}-brief.md").write_text("# DISPATCH\n\nTASK: console died\n")
        (ddir / f"{ts6}.log").write_text("got halfway through the task\n")
        runs.record_launch(ocon, ts6, task="console died", pid=999999)
        runs.sweep(ocon)
        row6 = runs.get(ocon, ts6)
        assert row6 and row6["outcome"] == "orphaned"
        assert not any(f["ts"] == ts6 for f in runs.unacked_failures(ocon))
        ocon.close()

    # pre-0.12 compat: an ops.db that has never seen the runs table grows it
    # on first touch and sweeps cleanly (the leads-migration guarantee)
    with tempfile.TemporaryDirectory() as td2:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td2) / "data")
        from opsroom import ops, runs
        ocon = ops.connect()
        tables = {r[0] for r in ocon.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "runs" not in tables, "ops schema should not pre-create runs"
        runs.sweep(ocon)
        assert runs.get(ocon, "20260101-000000-1") is None
        assert runs.unacked_failures(ocon) == []
        ocon.close()

    print("runs-ledger gate: full accounting, exit codes survive restarts, "
          "unknown never alerts, dead always does, pre-0.12 ledgers migrate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
