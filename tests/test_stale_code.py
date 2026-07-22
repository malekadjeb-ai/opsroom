#!/usr/bin/env python3
"""Stale-code tripwire gate: when the on-disk version differs from the booted
one, the console says so (with the restart command); equal versions and read
failures render nothing (fail-closed — never a false banner). Exit 0 = green.
Fictional fixtures."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[goal]
amount = 50000
deadline = "2099-12-31"
label = "Q3 $50K sprint"

[[venture]]
key = "meridian"
label = "Meridian Consulting"
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()

        real_iv = serve._installed_version

        def _fresh(fn):
            serve._installed_version = fn
            serve._VER_CACHE[0] = -1e9  # bust the 60s cache
            page = serve._page().decode()
            return page[page.index("<body>"):]

        try:
            # versions match (the normal case): no banner
            body = _fresh(lambda: serve.BOOT_VERSION)
            assert "restart it" not in body, "false stale-code banner"
            # the tripwire actually reads the real on-disk version correctly
            assert real_iv() == serve.BOOT_VERSION, \
                f"disk={real_iv()!r} != boot={serve.BOOT_VERSION!r} in a clean checkout"

            # drift: the banner names both versions and the fix
            body = _fresh(lambda: "99.0.0")
            assert "v99.0.0 is installed" in body and "kickstart" in body, \
                "stale-code banner missing"
            assert f"running v{serve.BOOT_VERSION}" in body

            # a reader that blows up: fail closed, no banner, page still renders
            def _boom():
                raise OSError("disk on fire")
            body = _fresh(_boom)
            assert "restart it" not in body, "a failing reader must stay silent"
            # and an empty read too
            body = _fresh(lambda: "")
            assert "restart it" not in body, "an empty read must stay silent"
        finally:
            serve._installed_version = real_iv
            serve._VER_CACHE[0] = -1e9

    print("stale-code gate: drift banners with the kickstart fix, "
          "equality and failure stay silent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
