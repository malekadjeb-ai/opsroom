"""Collector: markdown notes roots (Obsidian vault, notes folders). Degrades gracefully
when macOS TCC blocks a root (grant your terminal Full Disk Access). Read-only."""
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import ventures
from . import Emitter, file_changed, record_file

FM = re.compile(r"\A---\n(.*?)\n---", re.S)
FM_FIELD = re.compile(r"^(status|updated|venture|project)\s*:\s*(.+)$", re.M)


def _frontmatter(text: str) -> dict:
    m = FM.match(text)
    if not m:
        return {}
    return {k.lower(): v.strip().strip("'\"") for k, v in FM_FIELD.findall(m.group(1))}


def collect(con, dry_run: bool = False) -> dict:
    em = Emitter(con, dry_run)
    stats = {"notes": 0, "stale_notes": [], "degraded": []}
    import os
    for root, label in ventures.NOTES_ROOTS:
        rootp = Path(root)
        try:
            os.scandir(root).close()  # rglob swallows PermissionError; probe explicitly (macOS TCC)
        except PermissionError:
            stats["degraded"].append(f"{root}: PermissionError (grant Full Disk Access to the terminal)")
            continue
        except (FileNotFoundError, NotADirectoryError, OSError):
            stats["degraded"].append(f"{root}: missing")
            continue
        entries = list(rootp.rglob("*.md"))
        for f in entries:
            if "/opsroom/" in str(f):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            changed, _ = file_changed(con, str(f), st.st_mtime, st.st_size)
            if not changed and not dry_run:
                # still check staleness for loop detection
                pass
            try:
                text = f.read_text(errors="replace")
            except (PermissionError, OSError):
                continue
            fm = _frontmatter(text)
            ts = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
            venture = ventures.attribute(str(f))
            if venture == "unknown":
                venture = ventures.attribute_text(fm.get("venture", "") or f.name)
            if changed:
                stats["notes"] += 1
                first = next((ln.strip() for ln in text.splitlines()
                              if ln.strip() and not ln.startswith("---")), f.name)
                em.emit(ts=ts, source="notes", kind="note", actor="you",
                        summary=f"{f.name}: {first[:120]}", detail=text[:2000],
                        venture=venture, project=label, raw_ref=str(f))
                if not dry_run:
                    record_file(con, str(f), st.st_mtime, st.st_size, 1)
            if fm.get("status", "").lower() in ("in-progress", "in progress", "wip", "open"):
                age_d = (datetime.now(timezone.utc)
                         - datetime.fromtimestamp(st.st_mtime, timezone.utc)).days
                if age_d >= 14:
                    stats["stale_notes"].append({"path": str(f), "age_d": age_d,
                                                 "venture": venture, "name": f.name})
    stats.update({"events_new": em.inserted, "events_seen": em.seen, "dropped": em.dropped})
    return stats
