"""Reply drafter — deterministic, stdlib, no LLM, no network. Speed-to-close is the
#1 revenue lever; this turns a pasted inbound message into a rails-correct draft
in one tap.

THE RAILS LIVE IN CONFIG, not in logic. Each venture can set:
  offer       — one sentence stating what you sell and your canon price/floor,
                written once, quoted verbatim in every priced draft
                ("Full details start at $249 — inside and out, I come to you.")
  draft_style — "service" (local/consumer service: book a day) or
                "b2b" (sell a call: 15 minutes, show the system). Default b2b.

Hard rules, enforced here:
  - The drafter NEVER interpolates digits from the inbound message — the only
    numbers a draft can contain are the ones you wrote into your config offer.
  - Unknown intent -> clarifying question, no offer, no prices to misfire on.
  - One CTA per draft. Same input -> same output, always.
"""
import re

from . import ventures

# intent tags via keyword rules — cheap, testable, deterministic
_RULES = {
    "price":    r"(?i)how much|price|pricing|quote|cost|charge|rate\b|estimate|budget",
    "schedule": r"(?i)\bwhen\b|available|availability|book|schedule|come out|appointment"
                r"|this week|tomorrow|today\b",
    "interest": r"(?i)interested|tell me more|sounds good|more info|learn more|curious",
    "call":     r"(?i)\bcall\b|phone|talk|chat|meet|zoom"
                r"|monday|tuesday|wednesday|thursday|friday",
}


def detect(message: str) -> set:
    """Keyword-rule intent tags for an inbound message."""
    msg = message or ""
    return {tag for tag, pat in _RULES.items() if re.search(pat, msg)}


def _greet(name: str) -> str:
    # names come from the operator; digits stripped so a draft can never echo a number
    clean = re.sub(r"[\d|<>]", "", (name or "")).strip().split(" ")[0]
    return f"Hi {clean}," if clean else "Hi,"


def _service(tags: set, name: str, offer: str) -> str:
    g = _greet(name)
    if not offer:
        return _clarify(g)
    if "price" in tags or "interest" in tags:
        return (f"{g} thanks for reaching out! Quick answer: {offer} "
                f"What day works for you this week?")
    if "schedule" in tags:
        return (f"{g} absolutely. {offer} "
                f"What day and rough address should I plan for?")
    if "call" in tags:
        return (f"{g} happy to talk it through. {offer} "
                f"What time works for a quick call?")
    return _clarify(g)


def _b2b(tags: set, name: str, offer: str) -> str:
    g = _greet(name)
    if "call" in tags or "schedule" in tags:
        return (f"{g} sounds good — let's talk. I'll keep it to 15 minutes: I'll walk "
                f"you through exactly what I'd do for you, and you can decide if it "
                f"fits. What time works for you?")
    if "price" in tags and offer:
        return (f"{g} fair question. {offer} Scoped up front, no surprises. "
                f"Want to do a quick 15-minute call so I can walk you through it?")
    if "interest" in tags:
        lead = f"{offer} " if offer else ""
        return (f"{g} glad it landed. {lead}"
                f"Want to do a quick 15-minute call this week?")
    return (f"{g} thanks for getting back to me. Happy to answer anything — the "
            f"fastest way is a quick 15-minute call where I walk you through it "
            f"live. What time works for you?")


def _clarify(g: str) -> str:
    # unknown intent (or no configured offer) -> clarifying question, no prices
    return (f"{g} thanks for the message! Happy to help — can you tell me a bit "
            f"more about what you're looking for? I'll give you an exact answer "
            f"right here.")


def draft_reply(venture: str, message: str, name: str = "") -> str:
    """Rails-correct draft for an inbound message. Deterministic; rails come from
    the venture's config (offer + draft_style)."""
    meta = ventures.VENTURES.get(venture) or {}
    tags = detect(message)
    offer = (meta.get("offer") or "").strip()
    if meta.get("draft_style") == "service":
        return _service(tags, name, offer)
    return _b2b(tags, name, offer)
