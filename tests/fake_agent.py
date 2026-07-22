#!/usr/bin/env python3
"""A stand-in agent CLI for tests and live demos of the operator loop. Point
[agent] command at it:

    [agent]
    enabled = true
    command = ["python3", "tests/fake_agent.py"]

It receives the dispatch brief as argv[1] like a real agent (or on stdin under
OPSROOM_FAKE_STDIN=1), pretends to work, then prints proposal blocks. Venture
key comes from OPSROOM_FAKE_VENTURE (default "meridian" — the demo venture).
Failure modes for the runs-ledger gates: OPSROOM_FAKE_SLEEP=<sec> (hang, for
the watchdog), OPSROOM_FAKE_SILENT=1 (die with zero output, for the dead-run
retry), OPSROOM_FAKE_EXIT=<n> (nonzero exit after output). Fictional data only."""
import os
import sys
import time

venture = os.environ.get("OPSROOM_FAKE_VENTURE", "meridian")
if os.environ.get("OPSROOM_FAKE_STDIN"):
    brief = sys.stdin.read()
else:
    brief = sys.argv[1] if len(sys.argv) > 1 else ""

if os.environ.get("OPSROOM_FAKE_SLEEP"):
    time.sleep(float(os.environ["OPSROOM_FAKE_SLEEP"]))

if os.environ.get("OPSROOM_FAKE_SILENT"):
    sys.exit(1)  # the silent-night signature: 0 bytes of output, gone
print(f"read the brief ({len(brief)} chars). Working the task…")
print("called the two newest leads, drafted the follow-up, confirmed one payment.")
print("Proposing results:")
print(f'''```opsroom
{{"propose": "cash", "amount": 380, "venture": "{venture}", "what": "collected — confirmed by owner"}}
```
```opsroom
{{"propose": "followup", "target": "Kestrel Detailing", "due": "+2d", "venture": "{venture}", "note": "they asked for the written quote"}}
```
```opsroom
{{"propose": "touch", "target": "Harbor & Co", "kind": "called", "venture": "{venture}", "note": "left voicemail re: sprint"}}
```''')

if os.environ.get("OPSROOM_FAKE_COUNSEL"):
    # counsel mode: an answer (with hostile markup + a fake secret assembled from
    # parts, to prove render-escaping and store-scrubbing) plus a plan block
    fake_secret = "api_key=" + "sk-ant-" + "api03-" + "Zz1234567890abcdefghij"
    print(f'''```counsel
## Verdict
The board is **healthy on cash** but the aged quotes are the leak. <script>alert(1)</script>
Also found in a note: {fake_secret}

1. Call the two aged quotes before noon.
2. Send the Kestrel written quote today.
```
```counsel-plan
{{"steps": [
  {{"task": "Call the two aged interior quotes before noon", "venture": "{venture}", "why": "quotes decay after day 7"}},
  {{"task": "Send Kestrel Detailing the written quote", "venture": "{venture}", "why": "they asked twice"}},
  {{"task": "Draft the Saturday-slot text blast", "venture": "not-a-venture", "why": "tests venture coercion"}}
]}}
```''')

if os.environ.get("OPSROOM_FAKE_EXIT"):
    sys.exit(int(os.environ["OPSROOM_FAKE_EXIT"]))
