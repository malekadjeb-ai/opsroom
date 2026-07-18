"""Live agent sessions — what's running RIGHT NOW, by mode. Read-only, stdlib.

Every Claude Code session (interactive, cowork, background, web) writes a small
registry file under ~/.claude/sessions/*.json while it's alive, carrying its name,
cwd, kind, and status. The activity collectors already count these sessions once
they've logged work; this surfaces them LIVE — so a cowork/background agent grinding
on a venture shows up as it happens, attributed and labelled by mode, instead of only
appearing after the fact in the 7-day rollup.

Nothing here touches the network or writes anything; a missing/foreign registry just
yields an empty list.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import ventures

REGISTRY = Path.home() / ".claude" / "sessions"
FRESH_SECONDS = 90 * 60  # a registry file older than this is a stale/leftover session

# how each kind reads to an operator — cowork/background is the "agent working for me"
# signal the console exists to surface.
_KIND_LABEL = {
    "interactive": "interactive",
    "cowork": "cowork",
    "background": "background",
    "print": "one-shot",
}


def _age_seconds(ms) -> float:
    try:
        then = datetime.fromtimestamp(int(ms) / 1000, timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds()
    except (TypeError, ValueError, OverflowError, OSError):
        return 1e9


def live(registry: Path = None, now_fresh=FRESH_SECONDS) -> list:
    """Sessions updated within the freshness window, newest first. Each row:
    {name, venture, kind, status, cwd, age_min}. Empty on any read problem."""
    reg = registry or REGISTRY
    if not reg.is_dir():
        return []
    out = []
    try:
        files = sorted(reg.glob("*.json"))
    except OSError:
        return []
    for f in files:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        age = _age_seconds(d.get("updatedAt") or d.get("statusUpdatedAt"))
        if age > now_fresh:
            continue
        cwd = d.get("cwd") or ""
        kind = d.get("kind") or "?"
        out.append({
            "name": (d.get("name") or Path(cwd).name or "session")[:60],
            "venture": ventures.attribute(cwd),
            "kind": _KIND_LABEL.get(kind, kind),
            "is_cowork": kind in ("cowork", "background"),
            "status": (d.get("status") or "")[:20],
            "cwd": cwd,
            "age_min": int(age // 60),
        })
    out.sort(key=lambda s: s["age_min"])
    return out


def summary(registry: Path = None) -> dict:
    """Counts for the console strip: total live, and how many are cowork/background."""
    rows = live(registry)
    return {"live": len(rows), "cowork": sum(1 for r in rows if r["is_cowork"]),
            "rows": rows}
