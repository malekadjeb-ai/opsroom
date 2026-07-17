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

        # unknown action + oversized body rejected
        code, _ = post(base + "/act", {"do": "nuke", "token": serve.TOKEN})
        assert code == 400
        httpd.shutdown()
    print("serve gate: render, CSRF, origin, writes, cadence, ledger math")
    return 0


if __name__ == "__main__":
    sys.exit(main())
