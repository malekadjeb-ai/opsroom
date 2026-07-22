#!/usr/bin/env python3
"""Browser-origin gate: pins the fix for the 'bad token' bug that broke EVERY
form button in Chrome. `Referrer-Policy: no-referrer` makes Chrome send
`Origin: null` on same-origin form POSTs, which the same-origin check rightly
rejects — so the console must serve `Referrer-Policy: same-origin` (the
referrer still never leaves this loopback origin), a REAL same-origin Origin
header must pass, and `Origin: null` (a hostile sandboxed iframe's signature)
must STAY rejected with an error that names the actual problem. Exit 0 =
green. Fictional fixtures."""
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

[[venture]]
key = "meridian"
label = "Meridian Consulting"
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, ops, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ops.connect().close()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        # the page must serve same-origin referrer policy: no-referrer made
        # Chrome null the Origin on every form POST = every button 403'd
        r = urllib.request.urlopen(base + "/", timeout=5)
        assert r.headers.get("Referrer-Policy") == "same-origin", \
            f"Referrer-Policy is {r.headers.get('Referrer-Policy')!r} — Chrome " \
            "will send Origin: null and every button breaks"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)

        def post(origin=None):
            data = urllib.parse.urlencode(
                {"do": "capture", "text": "origin test", "token": serve.TOKEN}).encode()
            req = urllib.request.Request(base + "/act", data)
            if origin is not None:
                req.add_header("Origin", origin)
            try:
                resp = opener.open(req, timeout=5)
                return resp.status, b""
            except urllib.error.HTTPError as e:
                return e.code, e.read()

        # a REAL browser's same-origin POST (Origin: http://127.0.0.1:PORT) passes
        code, _ = post(f"http://127.0.0.1:{port}")
        assert code == 303, f"same-origin browser POST rejected: {code}"
        # Origin: null (sandboxed-iframe signature) STAYS rejected...
        code, body = post("null")
        assert code == 403, f"Origin: null must be rejected, got {code}"
        # ...with an error that names the real problem, not 'bad token'
        assert b"token" not in body.lower(), \
            f"origin failure must not masquerade as a token failure: {body!r}"
        # cross-site origin stays rejected
        code, _ = post("https://evil.example")
        assert code == 403, f"cross-site POST accepted: {code}"
        # and a wrong token still says token, with the right code
        data = urllib.parse.urlencode({"do": "capture", "text": "x",
                                       "token": "wrong"}).encode()
        req = urllib.request.Request(base + "/act", data)
        req.add_header("Origin", f"http://127.0.0.1:{port}")
        try:
            urllib.request.urlopen(req, timeout=5)
            code, body = 200, b""
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        assert code == 403 and b"token" in body.lower()
        httpd.shutdown()

    print("browser-origin gate: same-origin referrer policy, real browser POSTs "
          "pass, null/cross origins rejected with honest errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
