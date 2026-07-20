#!/usr/bin/env python3
"""Console-native onboarding gate: a truly-empty install shows the on-page setup
card; saving writes a valid 0600 config.toml (goal + ventures, NO [agent] — ever);
the console re-renders configured without a restart; and any config that already
has a goal, ventures, or an [agent] section refuses the web write with 409.
Exit 0 = green. Fictional fixtures."""
import os
import sys
import tempfile
import threading
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _post(base, data, token):
    body = urllib.parse.urlencode(dict(data, token=token)).encode()
    try:
        resp = urllib.request.urlopen(urllib.request.Request(base + "/act", body), timeout=10)
        return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, ops, serve, setup, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ops.connect().close()
        assert config.setup_needed(), "fresh install must read setup_needed"

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        # empty console leads with the setup card, and promises [agent] stays manual
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "SET UP YOUR ROOM" in page, "setup card missing on fresh install"
        assert "terminal-only" in page, "[agent] boundary not stated"

        # save: goal + two ventures (one with a hostile label; one with an offer)
        code, body = _post(base, {
            "do": "setup_save", "goal_amount": "25000", "goal_deadline": "2026-10-01",
            "goal_label": 'Q3 "sprint"', "v1_name": "Meridian Detailing",
            "v1_path": "~/code/meridian-app", "v1_offer": "Full detail is $380 flat.",
            "v2_name": "Shopkit", "v2_offer": ""}, serve.TOKEN)
        assert code == 200, (code, body[:200])

        cfg_path = cfg_dir / "config.toml"
        assert cfg_path.is_file(), "config.toml not written"
        assert oct(cfg_path.stat().st_mode & 0o777) == "0o600", "config not 0600"
        raw = tomllib.loads(cfg_path.read_text())  # must parse — quotes escaped
        assert raw["goal"]["amount"] == 25000 and raw["goal"]["deadline"] == "2026-10-01"
        assert raw["goal"]["label"] == 'Q3 "sprint"'
        keys = [v["key"] for v in raw["venture"]]
        assert keys == ["meridian-detailing", "shopkit"], keys
        assert raw["venture"][0]["offer"] == "Full detail is $380 flat."
        assert "meridian-app" in raw["venture"][0]["path_needles"], "path needle lost"
        assert "agent" not in raw, "web setup wrote an [agent] section — FORBIDDEN"
        assert "agent" not in cfg_path.read_text(), "[agent] text present in config"

        # the console re-renders configured, no restart: card gone, ventures live
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "SET UP YOUR ROOM" not in page, "setup card still shown after save"
        assert "Meridian Detailing" in page, "saved venture not on the page"

        # second save refuses — the page can never modify an existing config
        code, body = _post(base, {"do": "setup_save", "goal_amount": "1",
                                  "v1_name": "Takeover"}, serve.TOKEN)
        assert code == 409, f"re-setup allowed: {code}"

        # a config WITH [agent] (goal/ventures stripped) also refuses — mechanically
        # guarantees the web path can never rewrite an [agent] section
        cfg_path.write_text('[agent]\nenabled = true\ncommand = ["claude", "-p"]\n')
        config.load(force=True)
        try:
            setup.write_web_setup({"amount": 1}, [])
            assert False, "write_web_setup overwrote a config that has [agent]"
        except ValueError:
            pass
        code, _ = _post(base, {"do": "setup_save", "goal_amount": "1",
                               "v1_name": "X"}, serve.TOKEN)
        assert code == 409, f"web setup touched a config with [agent]: {code}"
        assert "enabled = true" in cfg_path.read_text(), "[agent] config was rewritten"

        # terminal init and web setup emit identical venture TOML (shared builder)
        blocks = setup.venture_blocks([{"key": "shopkit", "label": "Shopkit",
                                        "trap": False}])
        assert 'key = "shopkit"' in blocks and 'track = "A"' in blocks
        httpd.shutdown()
    print("setup-web gate: fresh-install card, 0600 TOML write (goal+ventures, no "
          "[agent] ever), live re-render, 409 on existing config, shared builder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
