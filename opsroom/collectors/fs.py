"""Collector: mtime scan of non-git project dirs (catches work git can't see).
Emits one aggregate event per (project, sync-run) to avoid noise."""
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import ventures
from . import Emitter

SKIP = {"node_modules", ".git", ".next", "dist", "build", "__pycache__", ".venv", "venv",
        ".Trash", "Library", ".cache"}
EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".swift", ".json", ".css", ".html",
        ".astro", ".sql", ".sh", ".yaml", ".yml", ".toml"}


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    row = con.execute("SELECT last_ts FROM watermarks WHERE source='fs'").fetchone()
    since = (datetime.fromisoformat(row["last_ts"]).timestamp()
             if row and row["last_ts"] else time.time() - 30 * 86400)
    now_iso = datetime.now(timezone.utc).isoformat()
    changed_by_project = {}
    for root in ventures.SCAN_ROOTS:
        rootp = Path(root)
        if not rootp.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(rootp):
            dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
            p = Path(dirpath)
            if (p / ".git").is_dir() and p != rootp:
                dirnames[:] = []  # git collector owns repos
                continue
            if (p / ".git").is_dir():
                continue
            for fn in filenames:
                if Path(fn).suffix not in EXTS:
                    continue
                f = p / fn
                try:
                    if f.stat().st_mtime <= since:
                        continue
                except OSError:
                    continue
                rel = f.relative_to(rootp)
                key = str(rootp / rel.parts[0]) if len(rel.parts) > 1 else str(rootp)
                changed_by_project.setdefault(key, []).append(str(f))
    for proj_path, files in changed_by_project.items():
        em.emit(ts=now_iso, source="fs", kind="artifact", actor="you",
                summary=f"{len(files)} files modified in {Path(proj_path).name} (non-git)",
                detail="\n".join(files[:40]), venture=ventures.attribute(proj_path),
                project=Path(proj_path).name, artifacts=files[:40], raw_ref=proj_path)
    return {"projects_changed": len(changed_by_project), "events_new": em.inserted,
            "events_seen": em.seen, "dropped": em.dropped, "watermark": now_iso}
