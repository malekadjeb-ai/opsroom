#!/usr/bin/env python3
"""Counsel gate: the console THINKS — ask + autonomous advisor. Covers: fence
fuzz (oversize/indented/first-wins/secrets), plan validation + numbered-line
fallback, the escape-first link-free markdown renderer, registered-runs-only
harvest idempotence, the ask e2e (question → agent → rendered answer + ▶ plan +
proposals on /counsel and the 🧠 NOW card), advisor window math + tick gating,
and CSRF. Exit 0 = green. Fictional fixtures."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = '''
[[venture]]
key = "meridian"
label = "Meridian Consulting"
offer = "The 2-week ops sprint is $12,000 flat."
'''


def _post(base, data, token=None):
    if token:
        data = dict(data, token=token)
    body = urllib.parse.urlencode(data).encode()
    try:
        resp = urllib.request.urlopen(urllib.request.Request(base + "/act", body), timeout=10)
        return resp.getcode(), resp.read(), resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, counsel, dashboard, db, dispatch, ops, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        # ---------------- answer fence fuzz
        A = counsel.parse_answer
        assert A("") == "" and A("no fences") == ""
        assert A("```counsel\nhello **world**\n```") == "hello **world**"
        assert A("    ```counsel\n    indented\n    ```") == "", "indented fence parsed"
        assert A("```counsel\nfirst\n```\n```counsel\nsecond\n```") == "first"
        assert A("```counsel\nunterminated") == ""
        assert A("```counsel\n\n```") == "", "empty block kept"
        big = A("```counsel\n" + "x" * 20000 + "\n```")
        assert len(big) <= counsel.MAX_ANSWER + 20 and big.endswith("…(truncated)")
        fake_key = "sk-ant-" + "api03-" + "Abcdefghij1234567890"
        assert fake_key not in A(f"```counsel\nkey {fake_key}\n```"), "secret stored"
        # the brief appendix echoed verbatim yields nothing (examples indented)
        assert A(counsel.ANSWER_APPENDIX) == "", "appendix echo parsed as answer"

        # ---------------- plan validation + fallback
        P = counsel.parse_plan
        good = P('```counsel-plan\n{"steps": [{"task": "Call them", "venture": "meridian", "why": "w"}]}\n```')
        assert good == [{"task": "Call them", "venture": "meridian", "why": "w"}]
        coerced = P('```counsel-plan\n{"steps": [{"task": "X", "venture": "nosuch"}]}\n```')
        assert coerced[0]["venture"] == "", "unknown venture not coerced"
        many = P('```counsel-plan\n' + json.dumps(
            {"steps": [{"task": f"t{i}"} for i in range(10)]}) + '\n```')
        assert len(many) == counsel.MAX_STEPS
        assert P('```counsel-plan\n{"steps": [{"task": 42}]}\n```') == []
        # broken JSON -> numbered-line fallback from the answer markdown
        fb = P('```counsel-plan\nnot json\n```', "intro\n1. Call the quotes\n2. Send the PDF\n")
        assert [s["task"] for s in fb] == ["Call the quotes", "Send the PDF"], fb
        assert P("", "") == []

        # ---------------- md_html: escape-first, link-free
        H = dashboard.md_html
        out = H("## Head\n**bold** `code`\n- a\n- b\n1. one\n2. two\n<script>alert(1)</script>\n[x](javascript:alert(2)) https://evil.example")
        assert "<script>" not in out and "alert(1)" in out, "script not escaped"
        assert "<h4>" in out and "<b>bold</b>" in out and "<code>code</code>" in out
        assert "<ul>" in out and "<ol>" in out
        assert "<a" not in out, "renderer minted a link"
        assert "javascript:" in out and "href" not in out, "javascript: became live"

        # ---------------- register/harvest: registered-runs-only + idempotent
        ts = "20260720-050505-000005"
        ddir = Path(os.environ["OPSROOM_DATA_DIR"]) / "dispatch"
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / f"{ts}.log").write_text("```counsel\nsmuggled\n```")
        assert counsel.harvest(ocon, ts) is False, "unregistered run harvested"
        assert counsel.get(ocon, ts) is None
        assert counsel.register(ocon, ts, "ask", "what now?") > 0
        assert counsel.register(ocon, ts, "ask", "what now?") == 0, "double register"
        assert counsel.register(ocon, "20260720-060606-000006", "evil", "") == 0
        assert counsel.harvest(ocon, ts) is True
        row = counsel.get(ocon, ts)
        assert row["answer"] == "smuggled" and row["question"] == "what now?"
        assert counsel.harvest(ocon, "../../etc/passwd") is False
        assert counsel.archive(ocon, row["id"]) is True
        assert counsel.archive(ocon, row["id"]) is False, "double archive claimed"

        # ---------------- advisor window math (pure, clock-injected)
        D = counsel.advise_due
        loc = datetime.now().astimezone().tzinfo
        t = lambda y, mo, d, h: datetime(y, mo, d, h, 1, tzinfo=loc)
        assert D("off", "") is False and D(None, "") is False and D(True, "") is False
        assert D("daily", "", t(2026, 7, 20, 5)) is False, "fired before 6am"
        assert D("daily", "", t(2026, 7, 20, 7)) is True, "never-run didn't fire"
        assert D("daily", t(2026, 7, 20, 7).isoformat(), t(2026, 7, 20, 9)) is False
        assert D("daily", t(2026, 7, 19, 7).isoformat(), t(2026, 7, 20, 7)) is True
        assert D(4, t(2026, 7, 20, 7).isoformat(), t(2026, 7, 20, 10)) is False
        assert D(4, t(2026, 7, 20, 7).isoformat(), t(2026, 7, 20, 11, ).replace(minute=2)) is True
        assert D(1, "", t(2026, 7, 20, 7)) is False, "hours below floor accepted"
        assert D(400, "", t(2026, 7, 20, 7)) is False, "hours above cap accepted"
        assert D("daily", "garbage-date", t(2026, 7, 20, 7)) is True, "malformed last must fire"

        # advise_tick gating: disabled agent -> no fire, no kv write
        assert counsel.advise_tick(ocon) == ""
        assert ops.kv_get(ocon, "advise_last", "") == ""

        # ---------------- ask e2e with the counsel-mode fake agent
        os.environ["OPSROOM_FAKE_COUNSEL"] = "1"
        (cfg_dir / "config.toml").write_text(CONFIG + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{ROOT / 'tests' / 'fake_agent.py'}"]
''')
        config.load(force=True)
        ventures.refresh()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        code, _, _ = _post(base, {"do": "ask", "question": "what next?"})
        assert code == 403, f"tokenless ask accepted: {code}"
        code, body, url = _post(base, {"do": "ask", "question": "What should I do about the aged quotes?",
                                       "venture": "meridian"}, serve.TOKEN)
        assert code == 200 and "/counsel?ts=" in url, (code, url)
        ask_ts = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["ts"][0]
        for _ in range(80):
            r = counsel.get(ocon, ask_ts)
            if r and r["answer"]:
                break
            time.sleep(0.1)
        r = counsel.get(ocon, ask_ts)
        assert r and "healthy on cash" in r["answer"], "answer not harvested"
        assert fake_key not in json.dumps(dict(r)), "secret in stored counsel"
        assert len(r["plan"]) == 3 and r["plan"][2]["venture"] == "", "plan/coercion"

        page = urllib.request.urlopen(base + f"/counsel?ts={ask_ts}", timeout=5).read().decode()
        assert "aged quotes" in page and "<b>healthy on cash</b>" in page
        assert "<script>alert(1)</script>" not in page, "counsel XSS"
        assert "THE PLAN" in page and page.count("/do?task=") >= 3, "plan ▶ links missing"
        assert "dispatch_queue" in page, "queue buttons missing"
        assert "record $380" in page, "run's proposals missing from /counsel"

        now_page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "🧠 COUNSEL" in now_page, "NOW card missing"
        assert "ask the board anything" in now_page, "ask bar missing"
        cid = counsel.get(ocon, ask_ts)["id"]
        _post(base, {"do": "counsel_archive", "cid": cid}, serve.TOKEN)
        now_page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "🧠 COUNSEL" not in now_page, "archive didn't clear the card"

        # ---------------- advise_tick fires for real (hours window, runway clear)
        (cfg_dir / "config.toml").write_text(CONFIG + f'''
[agent]
enabled = true
command = ["{sys.executable}", "{ROOT / 'tests' / 'fake_agent.py'}"]
advise = 4
''')
        config.load(force=True)
        adv_ts = counsel.advise_tick(ocon)
        assert adv_ts, "due advisor didn't fire"
        assert ops.kv_get(ocon, "advise_last", ""), "window not claimed"
        assert counsel.advise_tick(ocon) == "", "second tick double-fired"
        row = counsel.get(ocon, adv_ts)
        assert row and row["kind"] == "advise"
        for _ in range(80):
            if counsel.get(ocon, adv_ts)["answer"]:
                break
            time.sleep(0.1)
        assert counsel.get(ocon, adv_ts)["answer"], "advise run not harvested"
        now_page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "TODAY'S BRIEFING" in now_page, "briefing card missing"
        # the advise brief carried the mandate
        brief = (Path(os.environ["OPSROOM_DATA_DIR"]) / "dispatch" / f"{adv_ts}-brief.md").read_text()
        assert "ADVISOR MANDATE" in brief and "BEYOND the derived DO NOW" in brief
        httpd.shutdown()
        ocon.close()
        del os.environ["OPSROOM_FAKE_COUNSEL"]
    print("counsel gate: fence fuzz, plan fallback, escape-first link-free renderer, "
          "registered-only harvest, ask e2e (answer+plan+proposals+card), advisor "
          "window math + claim-first tick, CSRF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
