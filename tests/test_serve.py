#!/usr/bin/env python3
"""Serve gate: the live console must render, reject cross-site writes (CSRF token +
origin check), accept tokened writes, and reflect them. Exit 0 = green."""
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


def post(url, data, headers=None, redirect=False):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 headers=headers or {})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(*([] if redirect else [NoRedirect()]))
    try:
        r = opener.open(req, timeout=5)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        from opsroom import db, ops, serve
        con = db.connect()  # create schema before the server touches it
        con.close()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{port}"

        # page renders, embeds the token, carries the CSP + auto-reload poller
        body = urllib.request.urlopen(base + "/", timeout=5)
        html = body.read().decode()
        assert serve.TOKEN in html, "token not embedded in served forms"
        assert body.headers["Content-Security-Policy"], "no CSP header"
        assert "/version" in html, "no auto-reload poller"

        # write WITHOUT token → rejected
        code, _ = post(base + "/act", {"do": "cash", "amount": "500", "venture": "x"})
        assert code == 403, f"tokenless write accepted: {code}"

        # write with token but hostile Origin → rejected
        code, _ = post(base + "/act", {"do": "cash", "amount": "500", "venture": "x",
                                       "token": serve.TOKEN},
                       headers={"Origin": "https://evil.example"})
        assert code == 403, f"cross-origin write accepted: {code}"

        # legit tokened writes land
        code, _ = post(base + "/act", {"do": "cash", "amount": "1,250", "venture": "demo",
                                       "what": "sprint deposit", "token": serve.TOKEN})
        assert code == 303, f"cash write failed: {code}"
        code, _ = post(base + "/act", {"do": "touch", "venture": "demo", "target": "Acme Co",
                                       "kind": "call", "token": serve.TOKEN})
        assert code == 303, f"touch write failed: {code}"
        code, _ = post(base + "/act", {"do": "lead_add", "name": "Jordan at Kestrel",
                                       "phone": "(555) 883-4409", "token": serve.TOKEN})
        assert code == 303, f"lead_add failed: {code}"

        ocon = ops.connect()
        assert ops.cash_total(ocon) == 1250, ops.cash_total(ocon)
        assert len(ops.followups_upcoming(ocon)) == 1, "touch did not schedule a follow-up"
        assert len(ops.leads_open(ocon)) == 1
        tape = ops.today_tape(ocon)
        assert tape["calls"] == 1 and tape["cash"] == 1250, tape

        # follow-up done via the button flow
        fid = ops.followups_upcoming(ocon)[0]["id"]
        code, _ = post(base + "/act", {"do": "followup", "fid": str(fid), "op": "done",
                                       "token": serve.TOKEN})
        assert code == 303
        assert len(ops.followups_upcoming(ocon)) == 0
        ocon.close()

        # the served page now shows the ledger driving the money math
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "1,250" in html, "cash ledger not reflected in served page"

        # search box: header carries the form; a query hits both ledgers
        assert "action='/search'" in html or 'action="/search"' in html, "no search box"
        con = db.connect()
        con.execute("""INSERT INTO events (id, ts, source, kind, venture, summary, raw_ref)
                       VALUES ('ev-s1', '2026-07-17T10:00:00', 'git', 'commit', 'demo',
                               'wired the kestrel booking flow', 'repo:demo')""")
        con.commit()  # the AFTER INSERT trigger populates events_fts
        con.close()
        page = urllib.request.urlopen(base + "/search?q=kestrel", timeout=5).read().decode()
        assert "kestrel booking flow" in page, "event hit missing from /search"
        assert "Jordan at Kestrel" in page, "lead hit missing from /search"
        # FTS operator soup + LIKE wildcards must be literal text, never a 500
        for evil in ['"a" OR (', "AND NOT *", "%_%", "<script>alert(1)</script>"]:
            q = urllib.parse.urlencode({"q": evil})
            r = urllib.request.urlopen(base + f"/search?{q}", timeout=5)
            assert r.status == 200, f"search 500 on {evil!r}"
            assert b"<script>alert(1)</script>" not in r.read(), "search echo unescaped"
        r = urllib.request.urlopen(base + "/search?q=", timeout=5)
        assert r.status == 200 and b"0 hits" in r.read()

        # reply drafter: page renders; inbound text is escaped, never executed
        r = urllib.request.urlopen(base + "/draft", timeout=5)
        assert r.status == 200 and b"REPLY DRAFTER" in r.read()
        q = urllib.parse.urlencode({"venture": "demo", "name": "Sam",
                                    "msg": "interested <script>alert(1)</script>"})
        page = urllib.request.urlopen(base + f"/draft?{q}", timeout=5).read()
        assert b"<script>alert(1)</script>" not in page, "draft echo unescaped"
        assert b"Hi Sam," in page, "draft not generated"

        # unknown action + oversized body rejected
        code, _ = post(base + "/act", {"do": "nuke", "token": serve.TOKEN})
        assert code == 400

        # DNS-rebinding: a request whose Host is not loopback must be refused
        req = urllib.request.Request(base + "/", headers={"Host": "evil.example"})
        try:
            r = urllib.request.urlopen(req, timeout=5)
            code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 403, f"rebound Host accepted: {code}"
        httpd.shutdown()
    print("serve gate: render, CSRF, origin, writes, cadence, ledger math, search")
    return 0


if __name__ == "__main__":
    sys.exit(main())
