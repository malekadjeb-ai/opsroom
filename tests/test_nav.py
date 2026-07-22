#!/usr/bin/env python3
"""Nav gate: ONE nav definition drives every surface — the console header and
the workspace subpages render the same four primaries (NOW · BOARD · MONEY ·
ADVISOR) in the same order, minors stay minor, and no second hardcoded <nav>
can drift. Exit 0 = green. Fictional fixtures."""
import os
import re
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
        from opsroom import config, dashboard, db, ops, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ops.connect().close()

        primaries = [label for _, label, _, minor in dashboard.NAV_ITEMS if not minor]
        assert primaries == ["🎯 NOW", "📇 BOARD", "💰 MONEY", "🧠 ADVISOR"], primaries

        def labels_in_order(html, scope_re):
            m = re.search(scope_re, html, re.S)
            assert m, "nav block missing"
            return [x for x in re.findall(r">([^<]+)</a>", m.group(0))
                    if x.strip() in primaries]

        # console header nav
        page = serve._page().decode()
        main_nav = labels_in_order(page, r"<nav>.*?</nav>")
        assert main_nav == primaries, f"console nav drifted: {main_nav}"
        # subpage nav (the board)
        board = dashboard.leads_page("tok", {s: [] for s in ops.STAGES},
                                     {s: 0 for s in (*ops.STAGES, "all")}, "", "", "newest")
        sub_nav = labels_in_order(board, r"class='subnav'.*?</div>")
        assert sub_nav == primaries, f"subnav drifted: {sub_nav}"

        # minors render but stay minor (icon + title, class=minor) on both
        for html in (page, board):
            assert "minor" in html and "engineering activity" in html
        # exactly ONE nav definition in the source: no second hardcoded <nav>
        src = (ROOT / "opsroom" / "dashboard.py").read_text()
        hard = re.findall(r"<nav>", src)
        assert len(hard) <= 1, f"{len(hard)} hardcoded <nav> blocks — NAV_ITEMS must be the only source"
        assert "NAV_ITEMS" in src.split("def _main_nav")[1].split("def ")[0], \
            "_main_nav no longer reads NAV_ITEMS"

    print("nav gate: one definition, four primaries everywhere, minors stay minor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
