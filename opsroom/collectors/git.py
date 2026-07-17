"""Collector: git repos — commits (events), plus working-tree / branch state consumed by
loop detection. Read-only: only `git log/status/for-each-ref/rev-list/show` are invoked."""
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import ventures
from . import Emitter

SKIP_DIRS = {"node_modules", ".git", "Library", ".Trash", "venv", ".venv", "__pycache__"}
US = "\x1f"


def _git(repo: str, *args, timeout: int = 30) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ""


def discover_repos() -> list:
    # dedupe by realpath: symlink aliases (e.g. ~/Claude/_projects/*) must not double-count
    repos = []
    for root in ventures.SCAN_ROOTS:
        rootp = Path(root)
        if not rootp.is_dir():
            continue
        if (rootp / ".git").is_dir():
            repos.append(str(rootp))
        for dirpath, dirnames, _ in os.walk(rootp):
            depth = len(Path(dirpath).relative_to(rootp).parts)
            if depth >= 4:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for d in list(dirnames):
                if (Path(dirpath) / d / ".git").is_dir():
                    repos.append(str(Path(dirpath) / d))
                    dirnames.remove(d)
    seen, out = set(), []
    for r in sorted(repos):
        real = str(Path(r).resolve())
        if real not in seen:
            seen.add(real)
            out.append(real)
    return out


def _default_branch(repo: str) -> str:
    ref = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    if ref:
        return ref.split("/")[-1]
    for cand in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", cand):
            return cand
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() or "main"


def _collect_commits(em: Emitter, con, repo: str, venture: str, project: str, dry_run: bool) -> list:
    """Ingest commits newer than the per-repo watermark. Returns new shas (for TODO scan)."""
    wm_key = f"git:{repo}"
    row = con.execute("SELECT last_ref FROM watermarks WHERE source=?", (wm_key,)).fetchone()
    since = ["--since", row["last_ref"]] if row and row["last_ref"] else ["--since", "90 days ago"]
    out = _git(repo, "log", "--branches", f"--format=%H{US}%aI{US}%an{US}%s", "--numstat", *since)
    new_shas, latest_iso = [], None
    sha = iso = subj = None
    files = []

    def flush():
        if sha:
            em.emit(ts=iso, source="git", kind="commit", actor="you",
                    summary=f"commit {sha[:8]}: {subj}", detail="",
                    venture=venture, project=project, artifacts=files[:30] or None,
                    session_id=None, raw_ref=f"{repo}@{sha}")
            new_shas.append(sha)

    for line in out.splitlines():
        if US in line:
            flush()
            files = []
            sha, iso, _an, subj = line.split(US, 3)
            latest_iso = max(latest_iso or iso, iso)
        elif line.strip() and sha:
            parts = line.split("\t")
            if len(parts) == 3:
                files.append(parts[2])
    flush()
    if not dry_run and latest_iso:
        import db
        db.set_watermark(con, wm_key, "ok", last_ts=latest_iso, last_ref=latest_iso)
    return new_shas


def _scan_planted_todos(repo: str, shas: list, cap: int = 60) -> list:
    """TODO/FIXME/HACK lines ADDED by recent commits and still present in HEAD."""
    found = []
    for sha in shas[:cap]:
        out = _git(repo, "show", sha, "--unified=0", "--format=", timeout=20)
        for line in out.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                for marker in ("TODO", "FIXME", "HACK"):
                    if marker in line:
                        found.append({"sha": sha, "line": line[1:].strip()[:160], "marker": marker})
                        break
    # keep only ones still in HEAD
    still = []
    for f in found:
        probe = f["line"][:80]
        if probe and _git(repo, "grep", "-F", probe, "HEAD", "--", ".", timeout=20):
            still.append(f)
    return still[:20]


def repo_state(repo: str) -> dict:
    """Live working-tree + branch state for loop detection (not stored as events)."""
    state = {"repo": repo, "dirty": [], "stale_branches": []}
    now = time.time()
    for line in _git(repo, "status", "--porcelain").splitlines():
        path = line[3:].strip().strip('"')
        full = Path(repo) / path
        try:
            age_h = (now - full.stat().st_mtime) / 3600
        except OSError:
            age_h = 0
        state["dirty"].append({"path": path, "age_h": round(age_h, 1)})
    default = _default_branch(repo)
    refs = _git(repo, "for-each-ref", "refs/heads",
                "--format=%(refname:short)\t%(committerdate:iso8601-strict)\t%(objectname:short)")
    for line in refs.splitlines():
        try:
            name, iso, obj = line.split("\t")
        except ValueError:
            continue
        if name == default:
            continue
        try:
            age_d = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(iso)).days
        except ValueError:
            continue
        ahead = _git(repo, "rev-list", "--count", f"{default}..{name}").strip()
        if ahead and int(ahead) > 0 and age_d >= 7:
            state["stale_branches"].append({"branch": name, "ahead": int(ahead),
                                            "age_d": age_d, "sha": obj})
    return state


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    repos = discover_repos()
    states, todos = [], []
    for repo in repos:
        venture = ventures.attribute(repo)
        project = Path(repo).name
        try:
            shas = _collect_commits(em, con, repo, venture, project, dry_run)
            if shas:
                for t in _scan_planted_todos(repo, shas):
                    todos.append({**t, "repo": repo, "venture": venture, "project": project})
            states.append({**repo_state(repo), "venture": venture, "project": project})
        except subprocess.TimeoutExpired:
            print(f"  [git] timeout in {repo}, skipping")
    return {"repos": len(repos), "events_new": em.inserted, "events_seen": em.seen,
            "dropped": em.dropped, "repo_states": states, "planted_todos": todos}
