#!/usr/bin/env python3
"""Lead-stage gate: the pipeline verb end to end — ops whitelist + status
mirror + never-demote, the agent proposal path (validate/summarize/apply,
fail-closed on junk), and the POST /act surface (CSRF, stage whitelist 400,
back-to-board redirect). Fictional fixtures only. Exit 0 = green."""
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
[[venture]]
key = "meridian"
label = "Meridian Consulting"
offer = "The 2-week ops sprint is $12,000 flat."
playbook = ["Anchor on the outcome, not hours"]
'''


def _post(base, data, token=None):
    if token:
        data = dict(data, token=token)
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(base + "/act", body)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.getcode(), resp.headers.get("Location", ""), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", ""), e.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, ops, proposals, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()
        ocon = ops.connect()

        lid = ops.add_lead(ocon, "Kestrel Detailing", "555-010-0199",
                           "full detail", venture="meridian")
        assert ops.lead_get(ocon, lid)["stage"] == "new"

        # ---------------- proposal path: validate / summarize / apply
        V = proposals.validate
        good = V({"propose": "lead_stage", "lead": lid, "stage": "talking"})
        assert good == {"verb": "lead_stage", "lead": lid, "stage": "talking",
                        "note": ""}, good
        assert V({"propose": "lead_stage", "lead": lid, "stage": "vip"}) is None
        assert V({"propose": "lead_stage", "lead": True, "stage": "new"}) is None
        assert V({"propose": "lead_stage", "lead": -4, "stage": "new"}) is None
        assert V({"propose": "lead_stage", "stage": "new"}) is None
        assert "→ talking" in proposals.summarize(good)
        proposals.apply_payload(ocon, good)
        row = ops.lead_get(ocon, lid)
        assert row["stage"] == "talking" and row["status"] == "working", dict(row)
        try:
            proposals.apply_payload(ocon, {"verb": "lead_stage", "lead": 99999,
                                           "stage": "new", "note": ""})
            raise AssertionError("apply on a missing lead must raise")
        except ValueError:
            pass

        # never demote: a called touch on a talking lead keeps the stage
        ops.touch_lead(ocon, lid, "called")
        assert ops.lead_get(ocon, lid)["stage"] == "talking"

        # ---------------- HTTP surface
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        opener = urllib.request.build_opener(_NoRedirect)
        urllib.request.install_opener(opener)
        try:
            code, _, _ = _post(base, {"do": "lead_stage", "id": lid, "stage": "quoted"})
            assert code == 403, f"tokenless stage move accepted: {code}"
            code, _, body = _post(base, {"do": "lead_stage", "id": lid,
                                         "stage": "platinum"}, token=serve.TOKEN)
            assert code == 400 and b"unknown stage" in body, (code, body)
            code, loc, _ = _post(base, {"do": "lead_stage", "id": lid, "stage": "quoted",
                                        "back": "/leads"}, token=serve.TOKEN)
            assert code == 303 and loc == "/leads", (code, loc)
            assert ops.lead_get(ocon, lid)["stage"] == "quoted"
            # junk back value never becomes a redirect target
            code, loc, _ = _post(base, {"do": "lead_stage", "id": lid, "stage": "talking",
                                        "back": "https://evil.example"}, token=serve.TOKEN)
            assert code == 303 and loc == "/", (code, loc)
        finally:
            httpd.shutdown()
            urllib.request.install_opener(urllib.request.build_opener())
        ocon.close()
    print("lead-stage gate: whitelist + mirror + never-demote, proposal verb "
          "fail-closed, CSRF + 400 + safe back-redirect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
