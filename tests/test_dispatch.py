#!/usr/bin/env python3
"""Dispatch gate: the do-it brief carries task + rails + context, launch is OFF by
default (brief written, nothing executed), opt-in launch runs the CONFIG command
with the brief as one argv (no shell), and the endpoint is CSRF-gated. Exit 0 =
green. Fictional fixtures."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG_OFF = '''
[[venture]]
key = "meridian"
label = "Meridian Consulting"
offer = "The 2-week ops sprint is $12,000 flat."
playbook = ["Anchor on the outcome, not hours"]
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG_OFF)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, dispatch, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()

        # brief: task + venture rails + offer + live context pack
        brief = dispatch.build_brief("Call Kestrel back about the sprint", "meridian")
        assert "TASK: Call Kestrel back about the sprint" in brief
        assert "Anchor on the outcome, not hours" in brief, "playbook rail missing"
        assert "$12,000" in brief, "canon offer missing"
        assert "OPERATOR" in brief.upper(), "context pack missing"

        # default: DISABLED — brief written, nothing launched
        assert dispatch.agent_ready() is False
        r = dispatch.dispatch("Write the case study", "meridian")
        assert r["launched"] is False and Path(r["brief"]).is_file(), r
        assert oct(Path(r["brief"]).stat().st_mode & 0o777) == "0o600"

        # opt-in: config command runs with the brief as ONE argv, no shell
        marker = Path(td) / "ran.json"
        runner = Path(td) / "runner.py"
        runner.write_text(
            "import json,sys\n"
            f"json.dump({{'argc': len(sys.argv), 'head': sys.argv[1][:60]}}, "
            f"open({str(marker)!r}, 'w'))\n")
        (cfg_dir / "config.toml").write_text(CONFIG_OFF + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{runner}"]
''')
        config.load(force=True)
        ventures.refresh()
        assert dispatch.agent_ready() is True
        time.sleep(1.1)  # distinct timestamp -> distinct brief/log filenames
        r = dispatch.dispatch("Send the proposal to Harbor & Co", "meridian")
        assert r["launched"] is True, r
        for _ in range(50):
            if marker.is_file():
                break
            time.sleep(0.1)
        ran = json.loads(marker.read_text())
        assert ran["argc"] == 2, ran            # brief arrived as exactly one argv
        assert ran["head"].startswith("# DISPATCH"), ran
        hist = dispatch.recent()
        assert len(hist) == 2 and hist[0]["task"] == "Send the proposal to Harbor & Co", hist

        # served: /do renders the brief; POST dispatch is CSRF-gated
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        q = urllib.parse.urlencode({"task": "Call <script>x</script> back", "venture": "meridian"})
        page = urllib.request.urlopen(base + f"/do?{q}", timeout=5).read()
        assert b"DO IT" in page and b"# DISPATCH" in page
        assert b"<script>x</script>" not in page, "task echo unescaped"
        data = urllib.parse.urlencode({"do": "dispatch", "task": "x"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/act", data), timeout=5)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 403, f"tokenless dispatch accepted: {code}"
        data = urllib.parse.urlencode({"do": "dispatch", "task": "Ship the deck",
                                       "venture": "meridian", "token": serve.TOKEN}).encode()
        time.sleep(1.1)
        body = urllib.request.urlopen(urllib.request.Request(base + "/act", data),
                                      timeout=10).read()
        assert b"dispatched" in body, "tokened dispatch did not run"
        httpd.shutdown()
    print("dispatch gate: brief content, off-by-default, argv launch, CSRF gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
