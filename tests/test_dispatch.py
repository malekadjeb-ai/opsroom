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

        # kind='do' (the default) carries NO counsel protocol — v0.9 brief unchanged
        assert "ANSWER PROTOCOL" not in brief and "OPERATOR QUESTION" not in brief
        # kind='ask' carries the question + answer protocol
        ask = dispatch.build_brief("Answer the operator's question", "meridian",
                                   kind="ask", question="What about the aged quotes?")
        assert "## OPERATOR QUESTION" in ask and "What about the aged quotes?" in ask
        assert "ANSWER PROTOCOL" in ask and "ADVISOR MANDATE" not in ask
        # kind='advise' carries the autonomous mandate
        adv = dispatch.build_brief("Advisor briefing", kind="advise")
        assert "ADVISOR MANDATE" in adv and "BEYOND the derived DO NOW" in adv

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
            f"open({str(marker)!r}, 'w'))\n"
            "print('done')\n")  # a 0-byte log now honestly reads as a dead run
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

        # result feedback: the run is tracked to completion, never fire-and-forget
        for _ in range(50):
            if dispatch.status(hist[0]["tsid"]) == "done":
                break
            time.sleep(0.1)
        assert dispatch.status(hist[0]["tsid"]) == "done", dispatch.status(hist[0]["tsid"])
        assert dispatch.tail("../../../etc/passwd") == "", "tail accepted a path"

        # a long-running dispatch reads 'running', appears in running(), then lands.
        # fake secret assembled from parts: the repo must never contain a
        # secret-shaped literal (GitHub push protection pattern-matches these)
        fake_key = "sk-live-Abcdefghij1234567890" + "T3Blb" + "kFJx"
        slow = Path(td) / "slow.py"
        slow.write_text("import sys,time\nprint('agent working on it')\n"
                        f"sys.stdout.flush()\ntime.sleep(4)\nprint({fake_key!r})\n")
        (cfg_dir / "config.toml").write_text(CONFIG_OFF + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{slow}"]
''')
        config.load(force=True)
        time.sleep(1.1)
        r = dispatch.dispatch("Research the Brightline expansion", "meridian")
        assert dispatch.status(r["ts"]) == "running", "fresh dispatch must read running"
        assert any(d["ts"] == r["ts"] for d in dispatch.running()), "missing from running()"
        for _ in range(30):
            if "agent working on it" in dispatch.tail(r["ts"]):
                break
            time.sleep(0.2)
        assert "agent working on it" in dispatch.tail(r["ts"]), "live tail not readable"
        for _ in range(80):
            if dispatch.status(r["ts"]) == "done":
                break
            time.sleep(0.1)
        assert dispatch.status(r["ts"]) == "done"
        assert fake_key not in dispatch.tail(r["ts"]), \
            "agent log tail leaked a secret — scrub failed"

        # a missing agent binary fails LOUDLY into the log, never a 0-byte mystery
        (cfg_dir / "config.toml").write_text(CONFIG_OFF + '''
[agent]
enabled = true
command = ["definitely-not-a-real-binary-540d1"]
''')
        config.load(force=True)
        time.sleep(1.1)
        r = dispatch.dispatch("Doomed run", "meridian")
        assert r.get("error"), "missing binary did not surface an error"
        assert "could not launch" in Path(r["log"]).read_text() if r["log"] else True
        assert "could not launch" in dispatch.tail(r["ts"]), "log tail silent on failure"
        # absolute paths pass through _resolve_exe untouched
        assert dispatch._resolve_exe(sys.executable) == sys.executable
        assert dispatch._resolve_exe("sh").endswith("/sh"), "PATH resolution broken"
        (cfg_dir / "config.toml").write_text(CONFIG_OFF + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{slow}"]
''')
        config.load(force=True)

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
        resp = urllib.request.urlopen(urllib.request.Request(base + "/act", data),
                                      timeout=10)
        body = resp.read()
        # PRG: the POST redirected to /do?launched=<ts> and the page shows live status
        assert "launched=" in resp.geturl(), f"expected redirect, got {resp.geturl()}"
        assert b"dispatched" in body or b"agent finished" in body, "no status banner"
        assert b"recent dispatches" in body and b"live status" in body
        httpd.shutdown()
    print("dispatch gate: brief content, off-by-default, argv launch, CSRF gate, live status + scrubbed tail, PRG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
