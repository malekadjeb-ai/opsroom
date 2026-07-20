"""User configuration. Everything personal lives in ~/.config/opsroom/config.toml —
nothing in code. Zero-config works too: opsroom auto-detects common code roots and
runs with generic defaults (no goal, no notes vault) until you run `opsroom init`.

Env overrides (used by `opsroom demo` and the test suite):
  OPSROOM_CONFIG_DIR — where config.toml lives
  OPSROOM_DATA_DIR   — where the SQLite ledger + caches live
"""
import os
import tomllib
from datetime import date
from pathlib import Path

_cache = {"path": None, "cfg": None}


def config_dir() -> Path:
    return Path(os.environ.get("OPSROOM_CONFIG_DIR",
                               Path.home() / ".config" / "opsroom")).expanduser()


def data_dir() -> Path:
    return Path(os.environ.get("OPSROOM_DATA_DIR",
                               Path.home() / ".local" / "share" / "opsroom")).expanduser()


def _default_scan_roots():
    home = Path.home()
    roots = [home / d for d in ("code", "dev", "projects", "src", "repos", "Developer", "work")]
    found = [str(r) for r in roots if r.is_dir()]
    return found or [str(home)]


DEFAULTS = {
    "goal": {},          # {"amount": 100000, "deadline": "2026-08-04", "label": "$100K sprint"}
    "paths": {
        "scan_roots": None,          # None -> auto-detect
        "notes_roots": [],           # markdown roots (Obsidian vault, notes dir) — optional
        "dashboard_note": "",        # the one note with a "## Live state" table — optional
        "pipeline_dir": "",          # markdown trackers with Totals / TOUCH LOG tables — optional
        "daily_dir": "",             # where `sitrep --write` appends; default <data>/daily
        "chat_drop_dir": "",         # manual chat-export drop dir
        "leads_drop": "",            # leads JSON drop file (default <data>/inbox/leads.json)
        "replies_drop": "",          # replies JSON drop file (default <data>/inbox/replies.json)
    },
    "links": {
        "mail_drafts": "",           # e.g. https://mail.google.com/mail/u/0/#drafts
        "leads": "",                 # e.g. your leads dashboard URL
    },
    "agent": {
        "enabled": False,            # opt-in: let the console launch your agent CLI
        "command": ["claude", "-p"],  # argv prefix; the brief is appended as ONE argument
        # the autonomous advisor — the ONLY unattended agent launch in opsroom, and a
        # SEPARATE opt-in beyond enabled: "off" | "daily" (one briefing after 6am
        # local) | int hours between briefings (2..168)
        "advise": "off",
    },
    "ventures": [],                  # list of tables: key,label,revenue,track,trap,
                                     #   path_needles,keywords,files,target_table,playbook
}


def load(force: bool = False) -> dict:
    """Read config.toml (cached until the path changes or force=True)."""
    path = config_dir() / "config.toml"
    if not force and _cache["cfg"] is not None and _cache["path"] == path:
        return _cache["cfg"]
    cfg = {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in DEFAULTS.items()}
    if path.is_file():
        try:
            raw = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as e:
            print(f"opsroom: bad config at {path}: {e} — using defaults")
            raw = {}
        for k in ("goal", "paths", "links", "agent"):
            cfg[k].update(raw.get(k, {}))
        cfg["ventures"] = raw.get("venture", raw.get("ventures", []))
    if not cfg["paths"]["scan_roots"]:
        cfg["paths"]["scan_roots"] = _default_scan_roots()
    if not cfg["paths"]["daily_dir"]:
        cfg["paths"]["daily_dir"] = str(data_dir() / "daily")
    if not cfg["paths"]["chat_drop_dir"]:
        cfg["paths"]["chat_drop_dir"] = str(data_dir() / "chat-drops")
    _cache.update(path=path, cfg=cfg)
    return cfg


def setup_needed(cfg=None) -> bool:
    """A truly fresh install: no goal AND no ventures. This is the one state where
    the console offers on-page setup instead of the 'go edit TOML' cliff."""
    cfg = cfg or load()
    return not goal_amount(cfg) and not cfg["ventures"]


def goal_deadline(cfg=None):
    g = (cfg or load())["goal"]
    try:
        return date.fromisoformat(str(g["deadline"])) if g.get("deadline") else None
    except ValueError:
        return None


def goal_amount(cfg=None) -> int:
    g = (cfg or load())["goal"]
    try:
        return int(g.get("amount") or 0)
    except (TypeError, ValueError):
        return 0


def goal_label(cfg=None) -> str:
    g = (cfg or load())["goal"]
    return g.get("label") or (f"${goal_amount(cfg):,}" if goal_amount(cfg) else "no goal set")


TEMPLATE = '''# opsroom config — https://github.com/{owner}/opsroom
# Everything here is optional. Delete what you don't use.

[goal]
amount = {amount}
deadline = "{deadline}"
label = "{label}"

[paths]
# Where your git repos live (auto-detected if omitted)
scan_roots = {scan_roots}
# Markdown roots to ingest (Obsidian vault, notes folder). Read-only, always.
notes_roots = {notes_roots}
# The one note holding a "## Live state" markdown table (see README for the format)
dashboard_note = "{dashboard_note}"
# Folder of markdown pipeline trackers (Totals / TOUCH LOG tables)
pipeline_dir = "{pipeline_dir}"

[links]
# One-tap buttons on the console. Leave empty to hide.
mail_drafts = ""
leads = ""

# One block per venture/project. track: A/B/C/D = revenue lanes shown first.
# trap = true marks $0-revenue build work (the "engineer's trap" — visible, not shameful).
{ventures}
'''


def write_template(path: Path, **kw) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(**kw))
    path.chmod(0o600)
