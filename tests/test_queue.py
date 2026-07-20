#!/usr/bin/env python3
"""Work-queue gate: a dispatch queued while an agent runs auto-fires when the
runner reaps; queue is FIFO with a race-safe pop; an applied dispatch-proposal
queues instead of double-launching while busy; queued chips render with a working
dismiss; the sync-tick rescue fires stranded items. Exit 0 = green. Fictional
fixtures."""
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[[venture]]
key = "meridian"
label = "Meridian Consulting"
'''


def _post(base, data, token):
    body = urllib.parse.urlencode(dict(data, token=token)).encode()
    return urllib.request.urlopen(urllib.request.Request(base + "/act", body), timeout=10)


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        slow = Path(td) / "slow.py"
        slow.write_text("import sys,time\nprint('working')\nsys.stdout.flush()\n"
                        "time.sleep(1.2)\nprint('done with', len(sys.argv[1]))\n")
        (cfg_dir / "config.toml").write_text(CONFIG + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{slow}"]
''')
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, dispatch, ops, proposals, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        # launch one (slow) agent, then queue two more while it runs — FIFO
        _post(base, {"do": "dispatch", "task": "First run", "venture": "meridian"},
              serve.TOKEN)
        assert len(dispatch.running()) == 1
        _post(base, {"do": "dispatch_queue", "task": "Second run",
                     "venture": "meridian"}, serve.TOKEN)
        _post(base, {"do": "dispatch_queue", "task": "Third run",
                     "venture": "meridian"}, serve.TOKEN)
        qd = proposals.queued(ocon)
        assert [q["verb"] for q in qd] == ["dispatch", "dispatch"], "queue not staged"
        assert len(dispatch.running()) == 1, "queued item launched while busy"

        # queued chips render on the console with a live dismiss
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "⏳ queued" in page and "Second run" in page and "2 queued" in page

        # the whole chain drains: reaper fires Second, then Third, FIFO
        deadline = time.time() + 15
        while time.time() < deadline:
            if not dispatch.running() and not proposals.queued(ocon) \
                    and len(dispatch.recent()) >= 3:
                if all(h["status"] == "done" for h in dispatch.recent()):
                    break
            time.sleep(0.2)
        hist = dispatch.recent()  # newest first
        tasks = [h["task"] for h in hist]
        assert tasks == ["Third run", "Second run", "First run"], f"FIFO broken: {tasks}"
        assert all(h["status"] == "done" for h in hist), [h["status"] for h in hist]

        # dismissing a queued item works (queued rows are claimable)
        proposals.enqueue(ocon, "Never run this", "meridian")
        pid = proposals.queued(ocon)[0]["id"]
        _post(base, {"do": "proposal_dismiss", "pid": pid}, serve.TOKEN)
        assert proposals.queued(ocon) == [], "queued dismiss failed"

        # an applied dispatch-PROPOSAL queues instead of double-launching while busy
        time.sleep(1.1)  # distinct dispatch timestamp
        _post(base, {"do": "dispatch", "task": "Busy again", "venture": "meridian"},
              serve.TOKEN)
        assert len(dispatch.running()) == 1
        proposals.stage(ocon, "20260720-030303-000003",
                        [proposals.validate({"propose": "dispatch",
                                             "task": "Chained follow-on",
                                             "venture": "meridian"})])
        pid = proposals.pending(ocon)[0]["id"]
        _post(base, {"do": "proposal_apply", "pid": pid}, serve.TOKEN)
        assert len(dispatch.running()) == 1, "apply double-launched while busy"
        assert any("Chained follow-on" in (q["summary"] or "")
                   for q in proposals.queued(ocon)), "apply didn't queue while busy"
        deadline = time.time() + 15
        while time.time() < deadline:
            hist = dispatch.recent()
            if hist and hist[0]["task"] == "Chained follow-on" \
                    and hist[0]["status"] == "done":
                break
            time.sleep(0.2)
        assert dispatch.recent()[0]["task"] == "Chained follow-on", "chain never fired"

        # race-safe pop: one winner per item
        proposals.enqueue(ocon, "Pop me", "meridian")
        a = proposals.pop_queued(ocon)
        b = proposals.pop_queued(ocon)
        assert a and a["task"] == "Pop me" and b is None, (a, b)
        httpd.shutdown()
        ocon.close()
    print("work-queue gate: FIFO auto-fire on reap, queue-while-busy (buttons + "
          "applied proposals), queued chips + dismiss, race-safe pop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
