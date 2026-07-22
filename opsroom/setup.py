"""`opsroom init` — interactive setup. Detects your git repos, asks for a goal and
notes locations, writes ~/.config/opsroom/config.toml. Re-run any time; it shows the
existing file and writes a fresh one only on confirm.

Also home to the CONSOLE-NATIVE first-run setup (write_web_setup): a fresh install's
empty console offers a form instead of the 'go edit TOML' cliff. Terminal init and
web setup emit identical TOML through the same venture_blocks() builder. The web
path can NEVER create or rewrite an [agent] section — the template has no [agent]
slot, and write_web_setup refuses to touch any config that already has one."""
import re
import subprocess
import tomllib
from datetime import date
from pathlib import Path

from . import config


def _tq(s: str) -> str:
    """A string made safe inside TOML double quotes."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def venture_blocks(vs: list) -> str:
    """[[venture]] TOML blocks from a list of {key, label, trap, offer?, needles?}.
    The ONE builder both `opsroom init` and the web setup use — identical output."""
    blocks, tracks, ri = "", ["A", "B", "C", "D"], 0
    for v in vs:
        track = ""
        if not v.get("trap") and ri < 4:
            track = f'\ntrack = "{tracks[ri]}"'
            ri += 1
        needles = v.get("needles") or [v["key"]]
        needles_toml = ", ".join(f'"{_tq(n)}"' for n in needles)
        offer = (f'offer = "{_tq(v["offer"])}"\n' if v.get("offer") else
                 '# offer = "one sentence + your canon price — quoted verbatim by the reply drafter"\n')
        blocks += (f'\n[[venture]]\nkey = "{_tq(v["key"])}"\nlabel = "{_tq(v["label"])}"\n'
                   f'revenue = "{"$0 build" if v.get("trap") else "revenue"}"\n'
                   f'trap = {str(bool(v.get("trap"))).lower()}{track}\n'
                   f'path_needles = [{needles_toml}]\nkeywords = ["{_tq(v["key"])}"]\n'
                   f'{offer}'
                   f'# draft_style = "b2b"   # or "service" (book a day, not a call)\n')
    return blocks


def slug(name: str) -> str:
    """Server-side venture key from a display name: [a-z0-9-], max 40."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
    return s or "venture"


def write_web_setup(goal: dict, vs: list) -> None:
    """The console's first-run setup writes config.toml — ONLY when the config is
    truly empty. Refuses (raises ValueError) if the file already has a goal amount,
    any [[venture]], or an [agent] section: that guarantees the loopback page can
    never modify an existing config — and never touch [agent], which additionally
    has no slot in the template it writes from. Preserves [paths] values from any
    existing (settings-only) file."""
    cfg_path = config.config_dir() / "config.toml"
    raw = {}
    if cfg_path.is_file():
        try:
            raw = tomllib.loads(cfg_path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            raise ValueError("existing config.toml is unreadable — fix or remove it first")
        if (raw.get("goal", {}).get("amount") or raw.get("venture")
                or raw.get("ventures") or "agent" in raw):
            raise ValueError("config already set up — edit config.toml or rerun opsroom init")
    amount = int(goal.get("amount") or 0)
    deadline = str(goal.get("deadline") or "")
    if deadline:
        date.fromisoformat(deadline)  # ValueError -> 400 upstream
    paths = raw.get("paths", {})
    roots = paths.get("scan_roots") or config._default_scan_roots()
    notes = paths.get("notes_roots") or []
    config.write_template(
        cfg_path, owner="you", amount=amount, deadline=_tq(deadline),
        label=_tq(str(goal.get("label") or "")),
        scan_roots="[" + ", ".join(f'"{_tq(str(r))}"' for r in roots) + "]",
        notes_roots="[" + ", ".join(f'"{_tq(str(n))}"' for n in notes) + "]",
        dashboard_note=_tq(str(paths.get("dashboard_note") or "")),
        pipeline_dir=_tq(str(paths.get("pipeline_dir") or "")),
        ventures=venture_blocks(vs) or "# [[venture]] …")


def _detect_repos(roots, cap=40):
    repos = []
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        try:
            out = subprocess.run(
                ["find", str(root), "-maxdepth", "3", "-name", ".git", "-type", "d"],
                capture_output=True, text=True, timeout=20).stdout
        except (subprocess.SubprocessError, OSError):
            continue
        for line in out.splitlines():
            repos.append(str(Path(line).parent))
            if len(repos) >= cap:
                return repos
    return repos


def _ask(prompt, default=""):
    tail = f" [{default}]" if default else ""
    ans = input(f"{prompt}{tail}: ").strip()
    return ans or default


def run(yes=False):
    cfg_path = config.config_dir() / "config.toml"
    if cfg_path.is_file():
        print(f"config exists: {cfg_path}")
        if not yes and _ask("overwrite? (y/N)", "n").lower() != "y":
            return 0
    print("\nopsroom init — everything is optional; blank skips a feature.\n")
    roots = config._default_scan_roots()
    repos = _detect_repos(roots)
    print(f"found {len(repos)} git repos under {', '.join(roots)}")
    ventures = []
    if yes:
        for r in repos[:12]:
            name = Path(r).name.lower()
            ventures.append({"key": name, "label": Path(r).name, "trap": False})
    else:
        print("For each repo: is it a REVENUE venture (r), a $0 build/trap (t), or skip (s)?")
        for r in repos:
            a = _ask(f"  {r}  (r/t/s)", "s").lower()
            if a in ("r", "t"):
                name = Path(r).name.lower()
                ventures.append({"key": name, "label": Path(r).name, "trap": a == "t"})
    amount = "0" if yes else _ask("Cash goal amount (number, blank = none)", "")
    deadline = "" if yes else (_ask("Goal deadline (YYYY-MM-DD)", "") if amount else "")
    label = "" if not amount else _ask("Goal label", f"${int(amount or 0):,} sprint") if not yes else ""
    notes = "" if yes else _ask("Markdown notes root (Obsidian vault etc., blank = none)", "")
    dash_note = "" if not notes else _ask("Dashboard note with a '## Live state' table (path)", "")
    pipedir = "" if yes else _ask("Pipeline trackers folder (blank = none)", "")

    vblocks = venture_blocks(ventures)
    config.write_template(
        cfg_path, owner="you", amount=amount or 0, deadline=deadline,
        label=label or "", scan_roots=str(roots).replace("'", '"'),
        notes_roots=(f'["{notes}"]' if notes else "[]"),
        dashboard_note=dash_note, pipeline_dir=pipedir, ventures=vblocks or "# [[venture]] …")
    print(f"\nwrote {cfg_path}")
    # a commented [agent] stub so the AI hookup is discoverable — terminal init
    # ONLY. The web setup's template has no [agent] slot, and that wall stands.
    with open(cfg_path, "a") as f:
        f.write(AGENT_STUB)
    print("next: opsroom sync      (first ingest)")
    print("then: opsroom dash      (your console)")
    print("AI:   opsroom connect   (wire your agent CLI — one confirm)")
    return 0


AGENT_STUB = """
# ---- one-tap agent dispatch (terminal-only opt-in; run `opsroom connect`)
# [agent]
# enabled = true
# command = ["claude", "-p"]   # any agent CLI: the brief is appended as ONE argument
# advise = "daily"             # autonomous briefings: "off" | "daily" | hours (2..168)
"""

_AGENT_CANDIDATES = (("Claude Code", ["claude", "-p"]),
                     ("Codex", ["codex", "exec"]),
                     ("Gemini CLI", ["gemini", "-p"]))


def connect(yes=False) -> int:
    """`opsroom connect` — wire your agent CLI into [agent] with explicit consent.
    Terminal-only on purpose: the browser-facing setup can never grant the console
    the power to launch a CLI. Appends [agent]; refuses if one already exists."""
    from . import dispatch
    cfg_path = config.config_dir() / "config.toml"
    if not cfg_path.is_file():
        print("no config yet — run `opsroom init` first")
        return 1
    if "[agent]" in cfg_path.read_text():
        print(f"an [agent] section already exists in {cfg_path} — edit it by hand.")
        print("(connect never rewrites an existing [agent]: your command is yours.)")
        return 1
    found = []
    for label, cmd in _AGENT_CANDIDATES:
        resolved = dispatch._resolve_exe(cmd[0])
        if Path(resolved).is_absolute():
            found.append((label, cmd, resolved))
    if not found:
        print("no agent CLI found on PATH (looked for: "
              + ", ".join(c[1][0] for c in _AGENT_CANDIDATES) + ")")
        print("install one, or add [agent] to config.toml yourself with an absolute path.")
        return 1
    label, cmd, resolved = found[0]
    print(f"found {label}: {resolved}")
    if len(found) > 1:
        print("also found: " + ", ".join(f"{l} ({r})" for l, _, r in found[1:])
              + " — edit config.toml to switch.")
    if not yes and _ask(f"enable one-tap dispatch via {label}? (y/N)", "n").lower() != "y":
        print("nothing written.")
        return 0
    advise = False
    if yes or _ask("also let it think for you — an autonomous daily briefing? (y/N)",
                   "n").lower() == "y":
        advise = True
    cmd_toml = ", ".join(f'"{_tq(c)}"' for c in cmd)
    block = ("\n[agent]\nenabled = true\n"
             f"command = [{cmd_toml}]\n"
             f'advise = "{"daily" if advise else "off"}"\n')
    with open(cfg_path, "a") as f:
        f.write(block)
    cfg_path.chmod(0o600)
    config.load(force=True)
    print(f"wrote [agent] to {cfg_path} (600)")
    print("every dispatch stays gated: agents PROPOSE, you approve — nothing "
          "applies without your tap.")
    if advise:
        print("the advisor will produce its first briefing on the next console tick "
              "after 06:00 local (never while other work runs).")
    print("check the wiring any time: opsroom doctor")
    return 0
