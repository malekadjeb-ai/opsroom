"""Collector: Desktop/web chat via the vendor data-export flow (manual drop).
Drop conversations.json (or the export .zip) into the configured chat_drop_dir —
Anthropic (Claude) and OpenAI (ChatGPT) exports are both recognized by shape.
The zip is deleted after successful ingest (spec P0 #7); extracted JSON is kept out of
sync roots and removed too."""
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .. import ventures
from . import Emitter

DROP_DIR = Path(ventures.CHAT_DROP_DIR)


def _ingest_conversations(em: Emitter, data: list, ref: str) -> int:
    n = 0
    for conv in data:
        cid = conv.get("uuid") or conv.get("id") or "?"
        name = conv.get("name") or "(untitled chat)"
        venture = ventures.attribute_text(name)
        for i, m in enumerate(conv.get("chat_messages", [])):
            text = m.get("text")
            if not text and isinstance(m.get("content"), list):
                text = "\n".join(c.get("text", "") for c in m["content"]
                                 if isinstance(c, dict) and c.get("type") == "text")
            text = (text or "").strip()
            if not text:
                continue
            sender = m.get("sender", "?")
            ts = m.get("created_at") or conv.get("created_at") or datetime.now(timezone.utc).isoformat()
            v = venture if venture != "unknown" else ventures.attribute_text(text[:500])
            em.emit(ts=ts, source="chat", kind="prompt" if sender == "human" else "response",
                    actor="you" if sender == "human" else "assistant",
                    session_id=f"chat:{cid}", venture=v, project=name[:60],
                    summary=text.strip().split("\n")[0][:180], detail=text,
                    raw_ref=f"{ref}#conv={cid}&msg={i}")
            n += 1
    return n


def _openai_text(msg: dict) -> str:
    content = msg.get("content") or {}
    if content.get("content_type") not in (None, "text", "multimodal_text"):
        return ""
    parts = content.get("parts") or []
    return "\n".join(p for p in parts if isinstance(p, str)).strip()


def _ingest_openai(em: Emitter, data: list, ref: str) -> int:
    """OpenAI ChatGPT export: each conversation is a mapping-tree of nodes."""
    n = 0
    for conv in data:
        cid = conv.get("conversation_id") or conv.get("id") or "?"
        name = conv.get("title") or "(untitled chat)"
        venture = ventures.attribute_text(name)
        nodes = conv.get("mapping") or {}
        msgs = []
        for node in nodes.values():
            m = (node or {}).get("message")
            if not isinstance(m, dict):
                continue
            role = ((m.get("author") or {}).get("role"))
            if role not in ("user", "assistant"):
                continue
            text = _openai_text(m)
            if not text:
                continue
            msgs.append((m.get("create_time") or conv.get("create_time") or 0, role, text, m.get("id", "?")))
        for ct, role, text, mid in sorted(msgs):
            ts = datetime.fromtimestamp(ct, timezone.utc).isoformat() if ct else \
                datetime.now(timezone.utc).isoformat()
            v = venture if venture != "unknown" else ventures.attribute_text(text[:500])
            em.emit(ts=ts, source="chat", kind="prompt" if role == "user" else "response",
                    actor="you" if role == "user" else "chatgpt",
                    session_id=f"chatgpt:{cid}", venture=v, project=name[:60],
                    summary=text.split("\n")[0][:180], detail=text,
                    raw_ref=f"{ref}#conv={cid}&msg={mid}")
            n += 1
    return n


def _ingest_any(em: Emitter, data, ref: str) -> int:
    """Sniff export format: Anthropic conversations carry chat_messages, OpenAI carry mapping."""
    if not isinstance(data, list):
        return 0
    if any(isinstance(c, dict) and "mapping" in c for c in data):
        return _ingest_openai(em, data, ref)
    return _ingest_conversations(em, data, ref)


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    if not DROP_DIR.is_dir():
        return {"status": "no drop dir", "events_new": 0, "events_seen": 0, "dropped": 0}
    ingested, cleanup = [], []
    for f in sorted(DROP_DIR.iterdir()):
        try:
            if f.suffix == ".json" and "conversation" in f.name.lower():
                data = json.loads(f.read_text(errors="replace"))
                _ingest_any(em, data, str(f))
                ingested.append(f.name)
                cleanup.append(f)
            elif f.suffix == ".zip":
                with zipfile.ZipFile(f) as z:
                    for member in z.namelist():
                        if member.endswith("conversations.json"):
                            data = json.loads(z.read(member).decode(errors="replace"))
                            _ingest_any(em, data, f"{f}!{member}")
                            ingested.append(f"{f.name}!{member}")
                cleanup.append(f)
        except Exception as e:
            print(f"  [chat] failed on {f.name}: {e}")
    if not dry_run:
        for f in cleanup:
            try:
                f.unlink()  # spec: delete export after ingest to shrink blast radius
            except OSError:
                pass
    return {"ingested": ingested, "events_new": em.inserted, "events_seen": em.seen,
            "dropped": em.dropped}
