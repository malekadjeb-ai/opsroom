#!/usr/bin/env python3
"""Palette gate: the command palette ships as an inert JSON blob + stdlib JS,
every 'post' action maps to a verb POST /act actually handles, every link is
same-origin relative, the CSRF token in the blob is the page's own, hostile
text can't break out of the script tag, and the static (no-serve) console
carries none of it. Exit 0 = green. Fictional fixtures."""
import json
import os
import re
import sys
import tempfile
from datetime import date
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

# every do= verb POST /act handles (mirrors the serve.py dispatch chain)
ACT_VERBS = {"touch", "followup", "cash", "spend", "lead_add", "lead_touch",
             "lead_stage", "advise_error_clear", "run_ack", "dispatch_cancel",
             "loop", "capture", "capture_set", "promise", "reply", "missed_clear",
             "dispatch", "proposal_apply", "proposal_dismiss", "ask",
             "counsel_archive", "dispatch_queue", "setup_save"}


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, dashboard, db, ops, proposals, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        # seed palette-reachable work: a due follow-up, a pending proposal, a lead
        # whose name tries to escape the script tag
        ops.followup_add(ocon, "Kestrel Detailing", date.today().isoformat(), "meridian")
        payload = proposals.validate({"propose": "cash", "amount": 120,
                                      "venture": "meridian", "what": "test"})
        assert payload, "fixture proposal failed validation"
        proposals.stage(ocon, "", [payload])
        ops.add_lead(ocon, "</script><script>alert(1)", "5550009999", stage="talking")
        ocon.close()

        page = serve._page().decode()
        # markup present, blob parses
        assert 'id="pal"' in page and 'id="pal-data"' in page and "palOpen" in page
        m = re.search(r'<script id="pal-data" type="application/json">(.*?)</script>',
                      page, re.S)
        assert m, "palette blob missing"
        blob = json.loads(m.group(1).replace("<\\/", "</"))
        assert blob["token"] == serve.TOKEN, "palette token != page token"
        assert len(blob["items"]) >= 10
        # every post entry is a whitelisted verb; every link stays on this origin
        for it in blob["items"]:
            if it["kind"] == "post":
                assert it["fields"]["do"] in ACT_VERBS, it
            elif it["kind"] == "link":
                assert it["href"].startswith(("/", "#")), f"off-origin link: {it}"
            else:
                assert it["kind"] == "focus", it
        # the seeded work is reachable from the keyboard
        labels = " ".join(it["label"] for it in blob["items"])
        assert "Kestrel Detailing" in labels and "apply proposal" in labels
        # hostile lead text cannot close the script tag
        assert "</script><script>alert(1)" not in m.group(1), \
            "palette blob is script-tag breakable"
        assert "<\\/script>" in m.group(1), "escaping marker missing"

        # the static console (opsroom dash, no serve_ctx) has no palette at all —
        # no token exists there and no actions could fire
        from opsroom import enrich, state
        con = db.connect()
        static = dashboard.render(state.build_state(con), enrich.drift(con), [], [])
        con.close()
        assert "pal-data" not in static and "palOpen" not in static

    print("palette gate: whitelisted verbs only, same-origin links, page token, "
          "breakout-proof blob, absent from static")
    return 0


if __name__ == "__main__":
    sys.exit(main())
