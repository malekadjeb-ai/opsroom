"""Resources-per-task: the link registry + reveal-target resolution.

Doctrine: every task row answers "what do I need to open to finish this" with
zero hunting. Resources come from config only — the global [links] table (any
key = any URL), each venture's `links` table, and filesystem reveal targets.
A resource that isn't configured, isn't http(s), or whose path doesn't exist
simply isn't offered: never a dead link, never a dead button.

Security: reveal clients send NAMES (config/data/daily/pipelines/note/venture
+ a venture key), never paths — every path is derived here from config, same
rule as the dispatch brief/log reveals in serve.py.
"""
from pathlib import Path

from . import config, ventures

# task kind -> the global [links] keys that kind needs. Venture links ride on
# any row scoped to that venture regardless of kind.
KIND_LINKS = {
    "send": ("mail_drafts",),
    "reply": ("mail_drafts",),
    "leads": ("leads",),
    "followup": ("calendar",),
    "call": (),
}


def _http(u) -> str:
    u = str(u or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


def global_links() -> dict:
    """Every configured [links] URL, http(s)-validated, insertion order."""
    out = {}
    for k, v in (config.load().get("links") or {}).items():
        u = _http(v)
        if u and isinstance(k, str) and k:
            out[k[:24]] = u
    return out


def venture_links(vkey: str) -> dict:
    """The venture's own links table from config ([[venture]] links = {...})."""
    v = ventures.VENTURES.get(vkey or "") or {}
    out = {}
    for k, u in (v.get("links") or {}).items():
        u = _http(u)
        if u and isinstance(k, str) and k:
            out[k[:24]] = u
    return out


def for_task(kind: str, vkey: str = "", limit: int = 4) -> list:
    """(label, url) externals this task needs: kind-mapped globals first, then
    the venture's own links. Deduped by URL, capped — chips, not a directory."""
    pairs = []
    g = global_links()
    for key in KIND_LINKS.get(kind, ()):
        if g.get(key):
            pairs.append((key, g[key]))
    for k, u in venture_links(vkey).items():
        pairs.append((k, u))
    seen, out = set(), []
    for k, u in pairs:
        if u in seen:
            continue
        seen.add(u)
        out.append((k, u))
    return out[:limit]


def venture_dir(vkey: str):
    """The venture's working folder: the first path_needle naming an existing
    directory directly under a scan root. Server-derived, never client input."""
    v = ventures.VENTURES.get(vkey or "")
    if not v:
        return None
    for root in ventures.SCAN_ROOTS:
        rp = Path(root)
        for needle in v.get("needles") or []:
            cand = rp / needle
            if cand.is_dir():
                return cand
    return None


def reveal_target(what: str, key: str = ""):
    """Filesystem target for a reveal NAME; None when it isn't offered.
    serve.py calls this for the whitelist, dashboard.py calls it to decide
    whether the 📂 chip renders at all — one resolver, no dead buttons."""
    paths = config.load()["paths"]
    if what == "config":
        t = config.config_dir() / "config.toml"
        return t if t.is_file() else None
    if what == "data":
        d = config.data_dir()
        return d if d.is_dir() else None
    if what == "daily":
        raw = paths.get("daily_dir") or ""
        d = Path(raw).expanduser()
        return d if raw and d.is_dir() else None
    if what == "pipelines":
        raw = paths.get("pipeline_dir") or ""
        d = Path(raw).expanduser()
        return d if raw and d.is_dir() else None
    if what == "note":
        raw = paths.get("dashboard_note") or ""
        f = Path(raw).expanduser()
        return f if raw and f.is_file() else None
    if what == "venture":
        return venture_dir(key)
    return None
