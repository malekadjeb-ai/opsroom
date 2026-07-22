#!/usr/bin/env python3
"""NOW-fold gate: the live NOW tab is scannable in 10 seconds — at most 7 DO NOW
rows above the fold, exactly ONE alert banner (rest folded), session-chatter
promises live in the PROMISES drawer (never DO NOW) while money-verb promises
still rank, routine sends collapse to one row, and the pace strip is the single
today surface. Exit 0 = green. Fictional fixtures."""
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
offer = "The 2-week ops sprint is $12,000 flat."
'''

CHATTER = "Staged set is now exactly the release. Committing, moving the tag."
MONEY = "Send the Meridian follow-up email and collect the deposit"


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, ops, promises, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        # seed noise: 12 follow-ups due today + 2 promises (chatter + money) + alerts
        for i in range(12):
            ops.followup_add(ocon, f"Target {i:02d}",
                             __import__("datetime").date.today().isoformat(), "meridian")
        promises._ensure(ocon)
        for i, text in enumerate((CHATTER, MONEY)):
            ocon.execute(
                "INSERT INTO promises(id, ts, venture, session_id, text) VALUES (?,?,?,?,?)",
                (f"p-test-{i}", "2026-01-01T00:00:00+00:00", "meridian", "s1", text))
        ocon.commit()
        ops.kv_set(ocon, "missed_calls", "3")
        ops.kv_set(ocon, "advise_error", "exit 1: agent CLI unresolvable")
        ocon.close()

        full = serve._page().decode()
        page = full[full.index("<body>"):]  # skip the stylesheet (its comments
        # mention DO NOW etc.) — every assertion below is about rendered HTML

        # ONE visible banner; the rest fold behind "+N more"
        head = page.split("DO NOW")[0]
        top_banners = re.findall(r"<div class='banner bad'>", head.split("<details>")[0])
        assert len(top_banners) == 1, f"expected exactly 1 unfolded banner, got {len(top_banners)}"
        assert "more alert" in page, "secondary alerts must fold, not vanish"
        # highest severity wins: the advisor error outranks missed calls
        assert page.index("advisor hit an error") < page.index("missed calls")

        # DO NOW: at most 7 rows above the fold, tail folds
        card = page[page.index("DO NOW"):]
        card = card[:card.index("LOG IT")]
        above_fold = card.split("more ranked below")[0]
        assert above_fold.count("class='ar'") <= 7, \
            f"fold broken: {above_fold.count(chr(39) + 'ar' + chr(39))} rows above the fold"
        assert "more ranked below" in card, "overflow must fold, not render"

        # chatter promise: drawer only. Money promise: ranks in DO NOW.
        do_now_card = card
        assert CHATTER[:40] not in do_now_card, "session chatter leaked into DO NOW"
        assert MONEY[:30] in do_now_card, "money promise must rank in DO NOW"
        assert "PROMISES — 2 staged" in page, "promises drawer missing"
        assert CHATTER[:40] in page, "chatter promise must live in the drawer"

        # one today surface: pace strip carries the tape, old tape strip is gone
        assert page.count("TODAY'S PACE") == 1
        assert "touches ·" in page.split("TODAY'S PACE")[1][:400], \
            "pace strip must absorb the tape"
        assert "<div class='tape'>" not in page, "the separate tape strip must be gone"

        # nav: the BOARD and ADVISOR are first-class
        assert 'href="/leads">📇 BOARD' in page and 'href="/counsel">🧠 ADVISOR' in page
    print("now-fold gate: one banner, ≤7 rows above the fold, chatter in the drawer, "
          "money promises rank, one pace surface, first-class nav")
    return 0


if __name__ == "__main__":
    sys.exit(main())
