#!/usr/bin/env python3
"""Onboarding gate: `opsroom connect` writes [agent] only with consent and never
rewrites an existing one; `opsroom doctor` is read-only, prints the advisor
error breadcrumb, and exits 1 on a broken agent command; the advisor error also
surfaces on the console with a clear action. The web-setup wall stands. Exit 0
= green. Fictional fixtures."""
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[goal]
amount = 50000
label = "Q3 sprint"

[[venture]]
key = "meridian"
label = "Meridian Consulting"
offer = "The 2-week ops sprint is $12,000 flat."
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        cfg_path = cfg_dir / "config.toml"
        cfg_path.write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        # a fake agent CLI on PATH so connect finds one on any machine
        bin_dir = Path(td) / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

        from opsroom import config, db, doctor, ops, setup
        config.load(force=True)
        db.connect().close()

        # ---- connect: writes [agent] with --yes, chmods 600, enables advise
        rc = setup.connect(yes=True)
        assert rc == 0, f"connect failed: {rc}"
        text = cfg_path.read_text()
        assert "[agent]" in text and 'command = ["claude", "-p"]' in text, text
        assert 'advise = "daily"' in text, text
        assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o600
        # never rewrites an existing [agent]
        rc = setup.connect(yes=True)
        assert rc == 1, "connect must refuse when [agent] exists"
        assert text == cfg_path.read_text(), "connect modified an existing [agent]"

        # ---- the web-setup wall still stands: it refuses configs with [agent]
        try:
            setup.write_web_setup({"amount": 1}, [])
            raise AssertionError("web setup must refuse a config containing [agent]")
        except ValueError:
            pass

        # ---- doctor: healthy wiring passes
        rc = doctor.run()
        assert rc == 0, "doctor must pass with a resolvable agent"

        # broken agent command → FAIL, exit 1
        cfg_path.write_text(CONFIG + '\n[agent]\nenabled = true\n'
                            'command = ["no-such-cli-xyz"]\nadvise = "off"\n')
        config.load(force=True)
        rc = doctor.run()
        assert rc == 1, "doctor must fail on an unresolvable agent command"

        # advisor breadcrumb prints and fails the run
        cfg_path.write_text(CONFIG)
        config.load(force=True)
        ocon = ops.connect()
        ops.kv_set(ocon, "advise_error", "exit 1: agent CLI unresolvable")
        ocon.close()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = doctor.run()
        assert rc == 1 and "agent CLI unresolvable" in buf.getvalue(), \
            "doctor must surface the advise_error breadcrumb"

        # ---- the console surfaces the same breadcrumb with a clear action
        from opsroom import serve, ventures
        ventures.refresh()
        page = serve._page().decode()
        assert "advisor hit an error" in page and "opsroom doctor" in page
        # and the clear verb wipes it
        ocon = ops.connect()
        ops.kv_set(ocon, "advise_error", "")
        assert ops.kv_get(ocon, "advise_error", "") == ""
        ocon.close()
    print("onboarding gate: connect consent + no-rewrite + web wall, doctor "
          "read-only checks + breadcrumb, console error chip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
