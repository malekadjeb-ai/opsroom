#!/usr/bin/env python3
"""Redaction gate (Phase 3, non-negotiable). Plants fake secrets, ingests through the
real Emitter into an isolated DB, asserts zero leakage. Exit 0 = gate green."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from opsroom import db

PLANTED = [
    ("anthropic key", "here is sk-ant-api03-FAKEFAKEFAKEFAKEFAKE1234 in a transcript"),
    ("aws key", "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"),
    ("db uri", "connect to postgres://admin:hunter2secret@db.internal:5432/prod"),
    ("private key", "-----BEGIN RSA PRIVATE KEY-----\nMIIFAKEFAKEFAKEFAKE\nqqqq\n-----END RSA PRIVATE KEY-----"),
    ("stripe live", "charge with sk_live_FAKEFAKEFAKEFAKEFAKE99"),
    ("github pat", "auth: ghp_FAKEFAKEFAKEFAKEFAKEFAKE12345678"),
    ("jwt", "bearer eyJhbGciOiJIUzI1NiJ9FAKE.eyJzdWIiOiIxMjM0NTY3ODkwIn0FAKE.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVFAKE"),
    ("slack", "hook xoxb-FAKE1234-FAKE5678-FAKEFAKEFAKE"),
    ("google", "key=AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE123"),
    ("env line", "STRIPE_WEBHOOK_SECRET=whsec_9kQz7XvB2mNpL4RtYcE8FAKE"),
    ("lowercase env", "api_key=sk_FAKElowercaseKEY0987654321"),
    ("password env", "password=P@ssw0rdHunterSeven!!"),
    ("bearer", "Authorization: Bearer FAKEbearerTOKEN0987654321abcd"),
    ("sendgrid", "SG.FAKEsendgridAAAAAAAAAA.BBBBBBBBBBsendgridFAKE"),
    # F1 regression: secret straddling the 4096 detail-truncation boundary
    ("boundary db uri", "x" * 4066 + "postgres://admin:SuperSecretHunterX@db.internal:5432/prod"),
]
MARKERS = ["FAKEFAKE", "AKIAIOSFODNN7EXAMPLE", "hunter2secret", "whsec_9kQz7XvB2mNpL4RtYcE8",
           "sk_FAKElowercaseKEY", "P@ssw0rdHunterSeven", "FAKEbearerTOKEN",
           "sendgridAAAA", "SuperSecretHunterX"]


def main():
    with tempfile.TemporaryDirectory() as td:
        db.DB_DIR = Path(td)
        db.DB_PATH = Path(td) / "activity.db"
        con = db.connect()
        from opsroom.collectors import Emitter
        em = Emitter(con)
        for i, (name, payload) in enumerate(PLANTED):
            em.emit(ts="2026-07-16T00:00:00.000Z", source="cli", kind="tool_result",
                    actor="claude", summary=f"fixture {name}: {payload[:80]}",
                    detail=payload, session_id="fixture", raw_ref=f"fixture:{i}")
        con.commit()
        failures = []
        for m in MARKERS:
            n = con.execute("SELECT COUNT(*) c FROM events WHERE detail LIKE ? OR summary LIKE ?",
                            (f"%{m}%", f"%{m}%")).fetchone()["c"]
            if n:
                failures.append(f"LEAK: marker '{m}' present in {n} rows")
        red = con.execute("SELECT COUNT(*) c FROM events WHERE redacted=1").fetchone()["c"]
        if red == 0:
            failures.append("no rows flagged redacted=1")
        total = con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        print(f"planted={len(PLANTED)} ingested={total} redacted_rows={red}")
        for r in con.execute("SELECT summary FROM events"):
            print("  ", r["summary"][:110])
        if failures:
            print("\n".join(failures))
            return 1
        print("REDACTION GATE: PASS (zero planted secrets in DB)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
