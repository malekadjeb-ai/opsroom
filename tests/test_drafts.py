#!/usr/bin/env python3
"""Drafter gate: deterministic rails-correct replies from config — the offer is
quoted verbatim, inbound digits are NEVER echoed, unknown intent carries no prices.
Exit 0 = green. Fixtures are fictional."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


CONFIG = '''
[[venture]]
key = "meridian"
label = "Meridian Consulting"
offer = "The 2-week ops sprint is $12,000 flat — scoped up front, no retainers."
draft_style = "b2b"

[[venture]]
key = "detailpro"
label = "DetailPro"
offer = "Full details start at $249, interiors at $189 — I come to you."
draft_style = "service"

[[venture]]
key = "bare"
label = "Bare Venture"
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        cfg_dir = Path(td) / "config"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(CONFIG)
        os.environ["OPSROOM_CONFIG_DIR"] = str(cfg_dir)
        from opsroom import drafts, ventures
        ventures.refresh()

        # intent detection
        assert "price" in drafts.detect("how much do you charge?")
        assert "schedule" in drafts.detect("can you come out tomorrow")
        assert "interest" in drafts.detect("I'm interested, tell me more")
        assert "call" in drafts.detect("can we talk Thursday")
        assert drafts.detect("lorem ipsum") == set()

        # deterministic: same input -> same output
        a = drafts.draft_reply("meridian", "what's the price?", "Jordan")
        b = drafts.draft_reply("meridian", "what's the price?", "Jordan")
        assert a == b, "drafter is not deterministic"

        # config offer quoted verbatim on a priced ask; greeting uses the name
        assert "The 2-week ops sprint is $12,000 flat" in a, a
        assert a.startswith("Hi Jordan,"), a

        # service style: schedule ask books a day, not a call
        d = drafts.draft_reply("detailpro", "when are you available?", "Sam")
        assert "$249" in d and "What day" in d, d

        # THE HARD RAIL: digits from the inbound message never appear in the draft
        hostile = "my budget is $77,777 and my number is 555-010-9999, what's the cost?"
        for v in ("meridian", "detailpro"):
            out = drafts.draft_reply(v, hostile, "Pat 555-010-9999")
            assert "77,777" not in out and "77777" not in out, out
            assert "555" not in out and "9999" not in out, out
        # the only digits allowed are the config offer's own (+ the "15-minute" CTA)
        import re
        out = drafts.draft_reply("meridian", hostile)
        allowed = set(re.findall(r"\d+", CONFIG)) | {"15"}
        runs = re.findall(r"\d+", out)
        assert runs and all(r in allowed for r in runs), runs

        # unknown intent -> clarifying question, NO prices to misfire on
        u = drafts.draft_reply("detailpro", "hey saw your thing")
        assert "$" not in u and "?" in u, u

        # venture with no offer: b2b still sells the call, never invents a price
        n = drafts.draft_reply("bare", "how much?", "Alex")
        assert "$" not in n, n

        # unknown venture never crashes
        drafts.draft_reply("nope", "how much?")

    print("drafts gate: intents, determinism, verbatim offer, no-echo rail, no invented prices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
