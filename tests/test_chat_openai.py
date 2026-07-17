#!/usr/bin/env python3
"""Chat export gate: the drop dir must ingest BOTH Anthropic and OpenAI conversation
exports, sniffed by shape, with correct actors and normalized timestamps. Exit 0 = green."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPENAI_EXPORT = [{
    "title": "Shopkit pricing strategy",
    "conversation_id": "oai-conv-1",
    "create_time": 1784268691.0,
    "mapping": {
        "root": {"message": None},
        "n1": {"message": {"id": "m1", "author": {"role": "user"},
                           "create_time": 1784268691.0,
                           "content": {"content_type": "text",
                                       "parts": ["Is $49/mo underpriced for shopkit?"]}}},
        "n2": {"message": {"id": "m2", "author": {"role": "assistant"},
                           "create_time": 1784268705.0,
                           "content": {"content_type": "text",
                                       "parts": ["Test a $79 pro tier first."]}}},
        "n3": {"message": {"id": "m3", "author": {"role": "system"},
                           "create_time": 1784268600.0,
                           "content": {"content_type": "text", "parts": ["system noise"]}}},
        "n4": {"message": {"id": "m4", "author": {"role": "assistant"},
                           "create_time": 1784268710.0,
                           "content": {"content_type": "code", "text": "not-a-parts-shape"}}},
    },
}]

ANTHROPIC_EXPORT = [{
    "uuid": "ant-conv-1", "name": "meridian proposal review",
    "created_at": "2026-07-15T10:00:00Z",
    "chat_messages": [
        {"sender": "human", "text": "review my meridian brightline proposal",
         "created_at": "2026-07-15T10:00:00Z"},
        {"sender": "assistant", "text": "The ROI section buries the lede…",
         "created_at": "2026-07-15T10:00:30Z"},
    ],
}]


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["OPSROOM_DATA_DIR"] = str(Path(td) / "data")
        os.environ["OPSROOM_CONFIG_DIR"] = str(Path(td) / "config")
        drop = Path(td) / "drop"
        drop.mkdir()
        (drop / "conversations_openai.json").write_text(json.dumps(OPENAI_EXPORT))
        (drop / "conversations_claude.json").write_text(json.dumps(ANTHROPIC_EXPORT))

        from opsroom import db
        from opsroom.collectors import chat
        chat.DROP_DIR = drop
        con = sqlite3.connect(":memory:")
        con.executescript(db.SCHEMA)
        con.row_factory = sqlite3.Row

        r = chat.collect(con)
        assert len(r["ingested"]) == 2, r
        assert r["dropped"] == 0, r

        oai = con.execute("SELECT * FROM events WHERE session_id LIKE 'chatgpt:%' ORDER BY ts").fetchall()
        assert len(oai) == 2, [dict(x) for x in oai]  # system + non-text filtered out
        assert oai[0]["actor"] == "you" and oai[0]["kind"] == "prompt", dict(oai[0])
        assert oai[1]["actor"] == "chatgpt" and oai[1]["kind"] == "response", dict(oai[1])
        assert oai[0]["ts"].endswith("Z") and oai[0]["ts"] < oai[1]["ts"], (oai[0]["ts"], oai[1]["ts"])

        ant = con.execute("SELECT * FROM events WHERE session_id LIKE 'chat:%' ORDER BY ts").fetchall()
        assert len(ant) == 2, [dict(x) for x in ant]
        assert ant[1]["actor"] == "assistant", dict(ant[1])

        # exports are consumed after ingest (blast-radius rule)
        assert list(drop.iterdir()) == [], list(drop.iterdir())

        # malformed conversation entries must not raise
        (drop / "conversations_bad.json").write_text(json.dumps(
            [{"mapping": {"x": {"message": {"author": None}}}}, {"unrelated": True}]))
        r2 = chat.collect(con)
        assert "conversations_bad.json" in r2["ingested"], r2
    print("chat gate: OpenAI + Anthropic sniff, actors, timestamps, cleanup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
