#!/usr/bin/env python3
"""doctor --fire gate: the end-to-end test dispatch goes through the REAL
configured command and verdicts on the runs ledger — pass on a working agent,
exit 1 on a failing one, and REFUSE (launching nothing) when [agent] is
disabled. Exit 0 = green. Fictional fixtures."""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = '''
[goal]
amount = 50000
deadline = "2099-12-31"
label = "Q3 $50K sprint"

[[venture]]
key = "meridian"
label = "Meridian Consulting"
'''


def _run_doctor(fire=True):
    from opsroom import doctor
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = doctor.run(fire=fire)
    return rc, buf.getvalue()


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        for k in ("OPSROOM_FAKE_EXIT", "OPSROOM_FAKE_SILENT", "OPSROOM_FAKE_SLEEP"):
            os.environ.pop(k, None)
        from opsroom import config, db, doctor, ops, runs, ventures
        doctor.FIRE_POLL_S = 0.2
        fake = ROOT / "tests" / "fake_agent.py"

        # disabled [agent]: --fire refuses, exits 1, and launches NOTHING
        (cfg_dir / "config.toml").write_text(BASE)
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        rc, out = _run_doctor()
        assert rc == 1 and "opsroom connect" in out, out
        ddir = Path(os.environ["OPSROOM_DATA_DIR"]) / "dispatch"
        assert not ddir.is_dir() or not list(ddir.glob("*.log")), \
            "--fire launched something with [agent] disabled"

        # working agent: --fire passes and the run is a ledger fact, kind=doctor
        (cfg_dir / "config.toml").write_text(BASE + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{fake}"]
''')
        config.load(force=True)
        rc, out = _run_doctor()
        assert rc == 0, out
        assert "fire" in out and "exit 0" in out and "bytes" in out, out
        ocon = ops.connect()
        n = ocon.execute("SELECT COUNT(*) FROM runs WHERE kind='doctor'"
                         " AND outcome='done'").fetchone()[0]
        assert n == 1, f"expected 1 done doctor run, found {n}"
        ocon.close()

        # failing agent: --fire exits 1 with the exit code in the verdict
        os.environ["OPSROOM_FAKE_EXIT"] = "2"
        rc, out = _run_doctor()
        assert rc == 1 and "exit 2" in out, out
        os.environ.pop("OPSROOM_FAKE_EXIT")

        # silent agent (the exact overnight failure): --fire catches it too
        os.environ["OPSROOM_FAKE_SILENT"] = "1"
        rc, out = _run_doctor()
        assert rc == 1 and "0 bytes" in out, out
        os.environ.pop("OPSROOM_FAKE_SILENT")

    print("doctor-fire gate: refuses when disabled, verdicts exit/duration/bytes, "
          "catches the silent death")
    return 0


if __name__ == "__main__":
    sys.exit(main())
