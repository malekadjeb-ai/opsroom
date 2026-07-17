"""Venture attribution, driven entirely by config.toml. Call refresh() after changing
config at runtime (demo/tests); normal CLI runs load once at import."""
from pathlib import Path

from . import config

VENTURES = {}
PATH_MAP = []
TEXT_KEYWORDS = []
SCAN_ROOTS = []
NOTES_ROOTS = []
CHAT_DROP_DIR = ""
DEADLINE = None
GOAL_USD = 0
GOAL_LABEL = ""


def refresh(force: bool = True):
    """(Re)build module state from config."""
    global VENTURES, PATH_MAP, TEXT_KEYWORDS, SCAN_ROOTS, NOTES_ROOTS
    global CHAT_DROP_DIR, DEADLINE, GOAL_USD, GOAL_LABEL
    cfg = config.load(force=force)
    VENTURES, PATH_MAP, TEXT_KEYWORDS = {}, [], []
    for v in cfg["ventures"]:
        key = v.get("key")
        if not key:
            continue
        VENTURES[key] = {
            "label": v.get("label", key),
            "revenue": v.get("revenue", ""),
            "trap": bool(v.get("trap", False)),
            "track": v.get("track"),
            "files": list(v.get("files", [])),
            "target_table": v.get("target_table", ""),
            "playbook": list(v.get("playbook", [])),
            "live_prefix": v.get("live_prefix", ""),
        }
        for needle in v.get("path_needles", [key]):
            PATH_MAP.append((needle.lower(), key))
        for kw in v.get("keywords", [key]):
            TEXT_KEYWORDS.append((kw.lower(), key))
    VENTURES["unknown"] = {"label": "Unattributed", "revenue": "?", "trap": False,
                           "track": None, "files": [], "target_table": "",
                           "playbook": [], "live_prefix": ""}
    SCAN_ROOTS = [str(Path(p).expanduser()) for p in cfg["paths"]["scan_roots"]]
    NOTES_ROOTS = [(str(Path(p).expanduser()), Path(p).expanduser().name)
                   for p in cfg["paths"]["notes_roots"]]
    CHAT_DROP_DIR = str(Path(cfg["paths"]["chat_drop_dir"]).expanduser())
    DEADLINE = config.goal_deadline(cfg)
    GOAL_USD = config.goal_amount(cfg)
    GOAL_LABEL = config.goal_label(cfg)


def attribute(path: str) -> str:
    """Map a filesystem path (cwd, repo, file) to a venture key."""
    if not path:
        return "unknown"
    p = path.lower()
    for needle, venture in PATH_MAP:
        if needle in p:
            return venture
    return "unknown"


def attribute_text(text: str) -> str:
    """Weak keyword attribution for sources without paths (chat export)."""
    if not text:
        return "unknown"
    t = text.lower()
    for kw, venture in TEXT_KEYWORDS:
        if kw in t:
            return venture
    return "unknown"


def attribute_text_all(text: str) -> set:
    """All ventures a text mentions (a decisions-log entry can touch several)."""
    t = (text or "").lower()
    return {v for kw, v in TEXT_KEYWORDS if kw in t}


refresh(force=False)
