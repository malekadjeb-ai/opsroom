#!/usr/bin/env python3
"""Proposals gate: agent output becomes PENDING one-tap ledger writes — never
auto-applied. Covers: fence parse fuzz (injection attempts, caps, indented-fence
immunity), strict validation (verb/venture/amount whitelists), redaction of
agent-derived text, idempotent staging (UNIQUE) and double-tap-safe apply, the
CSRF gate, and the full loop e2e with a fake agent CLI. Exit 0 = green.
Fictional fixtures only."""
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
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import config, db, dispatch, ops, proposals, serve, ventures
        config.load(force=True)
        ventures.refresh()
        db.connect().close()

        # ---------------- parse: fail-closed on everything that isn't clean
        P = proposals.parse
        assert P("") == [] and P("no fences here") == []
        assert P('```opsroom\n{"propose": "cash", "amount": 5}\n```') == \
            [{"propose": "cash", "amount": 5}]
        assert P('```opsroom\nnot json\n```') == [], "malformed JSON must be skipped"
        assert P('```opsroom\n[1,2,3]\n```') == [], "arrays are not proposals"
        assert P('```opsroom\n"just a string"\n```') == []
        big = '```opsroom\n{"propose": "cash", "pad": "' + "x" * 5000 + '"}\n```'
        assert P(big) == [], "oversize block must be dropped"
        # column-0 anchor: an indented fence (like the brief's own example) is inert
        assert P('    ```opsroom\n    {"propose": "cash", "amount": 5}\n    ```') == []
        # the brief appendix echoed verbatim stages NOTHING (brief-echo injection)
        assert [proposals.validate(o) for o in P(proposals.PROTOCOL_APPENDIX)
                if proposals.validate(o)] == [], "brief echo produced a proposal"

        # ---------------- validate: whitelist, venture existence, amount rules
        V = proposals.validate
        assert V({"propose": "drop_table"}) is None, "unknown verb passed"
        assert V({"propose": "cash", "amount": 380, "venture": "meridian"})["amount"] == 380
        assert V({"propose": "cash", "amount": 380, "venture": "nosuch"}) is None
        assert V({"propose": "cash", "amount": "380"}) is None, "string amount passed"
        assert V({"propose": "cash", "amount": -5}) is None, "negative amount passed"
        assert V({"propose": "cash", "amount": 2_000_000}) is None, "cap breached"
        assert V({"propose": "cash", "amount": True}) is None, "bool amount passed"
        assert V({"propose": "cash", "amount": 20})["venture"] == "other"
        assert V({"propose": "lead_touch", "lead": 3, "kind": "collected"}) is None, \
            "$0 collected must be invalid"
        assert V({"propose": "lead_touch", "lead": 3, "kind": "burned"}) is None
        assert V({"propose": "lead_touch", "lead": "3", "kind": "called"}) is None
        assert V({"propose": "followup", "target": "Kestrel", "due": "+2d"})["due"]
        assert V({"propose": "followup", "target": "Kestrel", "due": "+90d"}) is None
        assert V({"propose": "followup", "target": "Kestrel", "due": "someday"}) is None
        assert V({"propose": "dispatch", "task": "call the aged quotes",
                  "venture": "meridian"})["verb"] == "dispatch"
        assert V({"propose": "touch", "target": "", "kind": "called"}) is None
        long_note = V({"propose": "touch", "target": "Kestrel", "note": "n" * 900})
        assert len(long_note["note"]) <= 300, "note cap not enforced"

        # redaction: a secret in agent-proposed text never reaches the payload.
        # fake key assembled from parts (GitHub push protection pattern-matches)
        fake_key = "sk-ant-" + "api03-" + "Abcdefghij1234567890"
        clean = V({"propose": "cash", "amount": 50, "venture": "meridian",
                   "what": f"invoice, key {fake_key}"})
        assert fake_key not in json.dumps(clean), "secret survived validation"

        # ---------------- staging: idempotent, capped
        ocon = ops.connect()
        ts = "20260720-010101-000001"
        many = [V({"propose": "touch", "target": f"Target {i}", "venture": "meridian"})
                for i in range(40)]
        assert proposals.stage(ocon, ts, many) == proposals.MAX_PER_RUN, "per-run cap"
        assert proposals.stage(ocon, ts, many) == 0, "re-stage must be a no-op"
        pend = proposals.pending(ocon)
        assert len(pend) == proposals.MAX_PER_RUN
        for p in pend:  # clear for the e2e below
            proposals.dismiss(ocon, p["id"])
        assert proposals.pending(ocon) == []
        assert proposals.dismiss(ocon, pend[0]["id"]) is False, "double-dismiss claimed"

        # harvest refuses non-timestamp ids (path steering)
        assert proposals.harvest(ocon, "../../../etc/passwd") == 0

        # ---------------- the brief instructs the protocol
        brief = dispatch.build_brief("Call Kestrel back", "meridian")
        assert "PROPOSE RESULTS" in brief and "opsroom" in brief
        assert "one-tap approval" in brief, "no-auto-apply promise missing from brief"

        # ---------------- e2e: fake agent → harvest on reap → strip → one-tap apply
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

        code, _ = _post(base, {"do": "proposal_apply", "pid": "1"})
        assert code == 403, f"tokenless apply accepted: {code}"

        code, _ = _post(base, {"do": "dispatch", "task": "Work the newest leads",
                               "venture": "meridian"}, token=serve.TOKEN)
        for _ in range(80):
            if len(proposals.pending(ocon)) >= 3:
                break
            time.sleep(0.1)
        pend = proposals.pending(ocon)
        assert len(pend) == 3, f"expected 3 proposals from fake agent, got {len(pend)}"
        by_verb = {p["verb"]: p for p in pend}
        assert set(by_verb) == {"cash", "followup", "touch"}, sorted(by_verb)

        # the console renders the strip, escaped, with provenance
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "AGENT PROPOSES" in page and "nothing applies without your tap" in page
        assert "record $380" in page, "cash summary missing from strip"

        # nothing auto-applied: the ledger is untouched until the tap
        assert ops.cash_total(ocon) == 0, "a proposal auto-applied — LOOP BROKEN"

        # one-tap apply moves the real ledger…
        pid = by_verb["cash"]["id"]
        code, _ = _post(base, {"do": "proposal_apply", "pid": pid}, token=serve.TOKEN)
        assert code == 200
        assert ops.cash_total(ocon) == 380, "applied cash proposal didn't land"
        # …and a double-tap cannot apply twice
        code, _ = _post(base, {"do": "proposal_apply", "pid": pid}, token=serve.TOKEN)
        assert code == 200 and ops.cash_total(ocon) == 380, "double-tap double-applied"

        code, _ = _post(base, {"do": "proposal_apply", "pid": by_verb["followup"]["id"]},
                        token=serve.TOKEN)
        assert any(r["target"] == "Kestrel Detailing" for r in
                   ops.followups_upcoming(ocon)), "followup proposal didn't land"
        code, _ = _post(base, {"do": "proposal_dismiss", "pid": by_verb["touch"]["id"]},
                        token=serve.TOKEN)
        assert proposals.pending(ocon) == [], "strip not cleared after decisions"

        # re-harvesting the same finished run stages nothing (UNIQUE + marker)
        assert proposals.harvest_finished(ocon) == 0
        rows = ocon.execute("SELECT COUNT(*) c FROM proposals").fetchone()["c"]
        proposals.harvest_finished(ocon)
        assert ocon.execute("SELECT COUNT(*) c FROM proposals").fetchone()["c"] == rows

        # XSS + secrets via a hostile log: stage directly like a harvested run
        hostile = V({"propose": "lead_add", "name": "<script>alert(1)</script>",
                     "note": f"call про {fake_key}", "venture": "meridian"})
        proposals.stage(ocon, "20260720-020202-000002", [hostile])
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "<script>alert(1)</script>" not in page, "summary XSS"
        assert fake_key not in page, "secret leaked to the console"
        httpd.shutdown()
        ocon.close()
    print("proposals gate: parse fuzz, strict validate, redaction, idempotent stage, "
          "no-auto-apply, one-tap apply + double-tap guard, CSRF, e2e loop w/ fake agent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
