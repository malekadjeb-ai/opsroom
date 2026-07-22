#!/usr/bin/env python3
"""Retry gate: an advise run that dies at 0 bytes (the silent-night signature)
gets exactly ONE automatic retry — both attempts recorded and linked — and a
second death stops there. Operator-launched (kind='do') 0-byte runs never
retry; they get the red banner instead. Exit 0 = green. Fictional fixtures."""
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
''')
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        os.environ["OPSROOM_FAKE_SILENT"] = "1"
        for k in ("OPSROOM_FAKE_EXIT", "OPSROOM_FAKE_SLEEP"):
            os.environ.pop(k, None)
        from opsroom import config, counsel, db, dispatch, ops, runs, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        dispatch.RETRY_BACKOFF_S = 0  # tests don't wait a real minute

        ocon = ops.connect()
        r = dispatch.dispatch(counsel.ADVISE_TASK, kind="advise")
        counsel.register(ocon, r["ts"], "advise")
        # attempt 1 dies at 0 bytes -> exactly one linked retry, which also dies
        row1 = row2 = None
        for _ in range(150):
            row1 = runs.get(ocon, r["ts"])
            row2 = ocon.execute("SELECT * FROM runs WHERE retry_of=?",
                                (r["ts"],)).fetchone()
            if row1 and row1["outcome"] == "dead" and row2 and \
                    row2["outcome"] == "dead":
                break
            time.sleep(0.1)
        assert row1 and row1["outcome"] == "dead" and row1["attempt"] == 1, \
            dict(row1) if row1 else None
        assert row2 and row2["attempt"] == 2 and row2["kind"] == "advise", \
            "no linked retry fired"
        # the retry is registered for counsel harvest like any advise run
        assert ocon.execute("SELECT 1 FROM counsel WHERE dispatch_ts=?",
                            (row2["ts"],)).fetchone(), "retry not registered"
        time.sleep(1.0)  # any illegal third attempt would land by now
        n = ocon.execute("SELECT COUNT(*) FROM runs WHERE kind='advise'").fetchone()[0]
        assert n == 2, f"expected exactly 2 advise attempts, found {n}"
        assert ocon.execute("SELECT COUNT(*) FROM runs WHERE retry_of=?",
                            (row2["ts"],)).fetchone()[0] == 0, "retry retried itself"

        # kind='do' never retries — the operator gets the banner, not a loop
        r3 = dispatch.dispatch("Silent operator task", "meridian")
        for _ in range(100):
            row3 = runs.get(ocon, r3["ts"])
            if row3 and row3["outcome"] == "dead":
                break
            time.sleep(0.1)
        time.sleep(0.7)
        assert ocon.execute("SELECT COUNT(*) FROM runs WHERE retry_of=?",
                            (r3["ts"],)).fetchone()[0] == 0, "a do-run retried"
        assert any(f["ts"] == r3["ts"] for f in runs.unacked_failures(ocon))
        ocon.close()
        os.environ.pop("OPSROOM_FAKE_SILENT")

    print("retry gate: one linked advise retry on 0-byte death, never a loop, "
          "operator runs banner instead")
    return 0


if __name__ == "__main__":
    sys.exit(main())
