#!/usr/bin/env python3
"""Resources-per-task gate: every task row carries every source it needs, and
never a dead one. The link registry ([links] + per-venture links) renders as
↗ chips on the rows their kind maps to; the extended reveal verbs
(daily/pipelines/note/venture) resolve server-side from config NAMES only —
unconfigured or missing paths are refused with 400 and never render a chip;
non-http(s) registry values are dropped. Exit 0 = green. Fictional fixtures."""
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[goal]
amount = 50000
deadline = "2099-12-31"
label = "Q3 $50K sprint"

[links]
mail_drafts = "https://mail.example/drafts"
leads = "https://ads.example/leads"
calendar = "https://cal.example/week"
evil = "javascript:alert(1)"

[paths]
scan_roots = ["{scan}"]
pipeline_dir = "{pipe}"
daily_dir = "{daily}"
dashboard_note = "{note}"

[[venture]]
key = "meridian"
label = "Meridian Consulting"
path_needles = ["meridian-ops"]
links = {{gbp = "https://business.example/meridian", bad = "ftp://x"}}
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        os.environ["OPSROOM_DATA_DIR"] = str(td / "data")
        cfg_dir = td / "config"
        cfg_dir.mkdir()
        pipe = td / "pipelines"
        pipe.mkdir()
        daily = td / "daily"
        daily.mkdir()
        note = td / "dashboard.md"
        note.write_text("# ok\n")
        scan_root = td / "code"
        (scan_root / "meridian-ops").mkdir(parents=True)
        (cfg_dir / "config.toml").write_text(
            CONFIG.format(scan=scan_root, pipe=pipe, daily=daily, note=note))
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, ops, resources, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()
        ops.add_lead(ocon, "Casey Ito", phone="555-0101", service="interior",
                     venture="meridian")
        ops.followup_add(ocon, "Casey Ito",
                         __import__("datetime").date.today().isoformat(), "meridian")
        ocon.commit()
        ocon.close()

        # ---- registry: validated, venture links carried, junk dropped
        g = resources.global_links()
        assert set(g) == {"mail_drafts", "leads", "calendar"}, g
        vl = resources.venture_links("meridian")
        assert vl == {"gbp": "https://business.example/meridian"}, vl
        pairs = dict(resources.for_task("send", "meridian"))
        assert "mail_drafts" in pairs and "gbp" in pairs, pairs
        assert "javascript:alert(1)" not in str(g) + str(vl)

        # ---- reveal resolution: names resolve server-side; junk refused
        assert resources.reveal_target("daily") == daily
        assert resources.reveal_target("pipelines") == pipe
        assert resources.reveal_target("note") == note
        assert resources.reveal_target("venture", "meridian") == scan_root / "meridian-ops"
        assert resources.reveal_target("venture", "nope") is None
        assert resources.reveal_target("../../etc") is None

        # ---- the served page: rows carry their sources; no dead/evil links
        revealed = []
        serve._reveal_target = lambda p: revealed.append(str(p))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        page = urllib.request.urlopen(f"{base}/").read().decode()

        assert "https://business.example/meridian" in page, "venture link missing from rows"
        assert "☎ call" in page, "known-lead follow-up must carry tel"
        assert "https://cal.example/week" in page, "calendar link missing from follow-up"
        assert "javascript:alert(1)" not in page, "evil registry link leaked"
        assert "ftp://x" not in page, "non-http venture link leaked"
        assert "⚡ QUICK" in page, "rail quick-links card missing"

        def post(fields):
            fields = {**fields, "token": serve.TOKEN}
            req = urllib.request.Request(
                f"{base}/act", data=urllib.parse.urlencode(fields).encode(),
                headers={"Origin": base})
            try:
                return urllib.request.urlopen(req).status
            except urllib.error.HTTPError as e:
                return e.code

        # urllib follows the PRG 303 back to "/", so success reads as 200
        assert post({"do": "reveal", "what": "daily"}) == 200
        assert post({"do": "reveal", "what": "pipelines"}) == 200
        assert post({"do": "reveal", "what": "note"}) == 200
        assert post({"do": "reveal", "what": "venture", "key": "meridian"}) == 200
        assert revealed == [str(daily), str(pipe), str(note),
                            str(scan_root / "meridian-ops")], revealed
        assert post({"do": "reveal", "what": "venture", "key": "zzz"}) == 400
        assert post({"do": "reveal", "what": "../etc/passwd"}) == 400
        assert post({"do": "reveal", "what": "note/../secret"}) == 400
        assert len(revealed) == 4, "a refused reveal still opened something"

        httpd.shutdown()

    print("resources gate: registry validated, rows carry their sources, "
          "reveal names resolve server-side, junk refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
