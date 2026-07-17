"""`opsroom init` — interactive setup. Detects your git repos, asks for a goal and
notes locations, writes ~/.config/opsroom/config.toml. Re-run any time; it shows the
existing file and writes a fresh one only on confirm."""
import subprocess
from pathlib import Path

from . import config


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

    vblocks = ""
    tracks = ["A", "B", "C", "D"]
    ri = 0
    for v in ventures:
        track = ""
        if not v["trap"] and ri < 4:
            track = f'\ntrack = "{tracks[ri]}"'
            ri += 1
        vblocks += (f'\n[[venture]]\nkey = "{v["key"]}"\nlabel = "{v["label"]}"\n'
                    f'revenue = "{"$0 build" if v["trap"] else "revenue"}"\n'
                    f'trap = {str(v["trap"]).lower()}{track}\n'
                    f'path_needles = ["{v["key"]}"]\nkeywords = ["{v["key"]}"]\n')
    config.write_template(
        cfg_path, owner="you", amount=amount or 0, deadline=deadline,
        label=label or "", scan_roots=str(roots).replace("'", '"'),
        notes_roots=(f'["{notes}"]' if notes else "[]"),
        dashboard_note=dash_note, pipeline_dir=pipedir, ventures=vblocks or "# [[venture]] …")
    print(f"\nwrote {cfg_path}")
    print("next: opsroom sync   (first ingest)")
    print("then: opsroom dash   (your console)")
    return 0
