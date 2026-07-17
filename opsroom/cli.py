#!/usr/bin/env python3
"""opsroom — a local-first operator console. Read-only on all sources.
Commands: serve · init · sync · sitrep · dash · today · week · loops · drift · venture ·
search · daily · demo · purge · status"""
import argparse
import sys
import time

from . import config, db, enrich, views


def cmd_sync(args):
    con = db.connect()
    sources = args.source.split(",") if args.source else ["cli", "codex", "git", "fs", "notes", "chat"]
    t0 = time.time()
    results, degraded = {}, []
    git_result, notes_result = {}, {}
    from .collectors import (cli as c_cli, codex as c_codex, git as c_git, fs as c_fs,
                             notes as c_notes, chat as c_chat)
    registry = {"cli": c_cli, "codex": c_codex, "git": c_git, "fs": c_fs,
                "notes": c_notes, "chat": c_chat}
    for name in sources:
        mod = registry.get(name)
        if not mod:
            print(f"unknown source: {name}")
            continue
        try:
            r = mod.collect(con, dry_run=args.dry_run)
            results[name] = r
            if name == "git":
                git_result = r
            if name == "notes":
                notes_result = r
                if r.get("degraded"):
                    degraded.append(f"notes: {r['degraded']}")
            if not args.dry_run:
                db.set_watermark(con, name, "degraded" if (name == "notes" and r.get("degraded")) else "ok",
                                 last_ts=r.get("watermark"))
        except Exception as e:
            degraded.append(f"{name}: {type(e).__name__}: {e}")
            if not args.dry_run:
                db.set_watermark(con, name, "failed")
            print(f"  [{name}] DEGRADED: {e}", file=sys.stderr)
    if not args.dry_run:
        n_sessions = enrich.build_sessions(con)
        loop_stats = enrich.detect_loops(con, git_result, notes_result)
        con.commit()
        db.enforce_perms()
        try:
            from . import ops, promises
            oc = ops.connect()
            promises.scan(oc)
            oc.close()
        except Exception as e:
            print(f"  [promises] skipped: {type(e).__name__}: {e}", file=sys.stderr)
    else:
        n_sessions, loop_stats = "-", {"open": "-"}
    dt = time.time() - t0
    print(f"\nopsroom sync {'(dry-run) ' if args.dry_run else ''}done in {dt:.1f}s")
    for name, r in results.items():
        print(f"  {name:<6} new={r.get('events_new', 0):<6} seen={r.get('events_seen', 0):<7} "
              f"dropped={r.get('dropped', 0)}")
    print(f"  sessions built: {n_sessions} · open loops: {loop_stats['open']}")
    if degraded:
        print(f"  DEGRADED SOURCES: {degraded}")
    if not args.dry_run:
        row = con.execute("SELECT COUNT(*) c FROM events").fetchone()
        print(f"  events total: {row['c']}")
    con.close()
    return 0


def cmd_purge(args):
    con = db.connect()
    if args.source:
        for t in ("events", "sessions"):
            con.execute(f"DELETE FROM {t} WHERE source=?", (args.source,))
        con.execute("DELETE FROM loops WHERE signal LIKE ?", (f"%{args.source}%",))
        con.execute("DELETE FROM watermarks WHERE source=? OR source LIKE ?",
                    (args.source, f"{args.source}:%"))
        if args.source == "cli":
            con.execute("DELETE FROM file_state WHERE path LIKE '%/.claude/%'")
        if args.source == "codex":
            con.execute("DELETE FROM file_state WHERE path LIKE '%/.codex/%'")
        print(f"purged source={args.source}")
    if args.before:
        con.execute("DELETE FROM events WHERE ts < ?", (args.before,))
        con.execute("DELETE FROM sessions WHERE ended_at < ?", (args.before,))
        print(f"purged events before {args.before}")
    con.commit()
    con.execute("VACUUM")
    db.enforce_perms()
    con.close()
    return 0


def cmd_status(args):
    con = db.connect()
    print(f"\nconfig: {config.config_dir() / 'config.toml'}"
          f"{'' if (config.config_dir() / 'config.toml').is_file() else ' (not found — opsroom init)'}")
    print(f"data:   {config.data_dir()}\n\nSOURCE STATUS")
    for r in con.execute("SELECT * FROM watermarks WHERE source NOT LIKE 'git:%' ORDER BY source"):
        print(f"  {r['source']:<8} {r['status']:<10} last run {r['last_run'] or '-'}")
    for r in con.execute("SELECT source, COUNT(*) c FROM events GROUP BY source"):
        print(f"  {r['source']:<8} {r['c']} events")
    con.close()
    return 0


def main():
    p = argparse.ArgumentParser(prog="opsroom", description=__doc__)
    sub = p.add_subparsers(dest="cmd")  # no subcommand → `opsroom serve` (the app)
    ip = sub.add_parser("init", help="interactive setup: ventures, goal, notes, trackers")
    ip.add_argument("--yes", action="store_true", help="accept detected defaults, no prompts")
    sp = sub.add_parser("sync", help="ingest all sources (read-only on sources)")
    sp.add_argument("--source", help="comma-separated subset: cli,codex,git,fs,notes,chat")
    sp.add_argument("--dry-run", action="store_true", help="parse + count, write nothing")
    st = sub.add_parser("sitrep", help="operator SITREP: goal clock, cash, leads, pipeline, leak, one move")
    st.add_argument("--write", action="store_true", help="append to the daily note (default: print only)")
    sub.add_parser("dash", help="operator console (single local HTML file)").add_argument(
        "--no-open", action="store_true")
    vp2 = sub.add_parser("serve", help="the console as a live local app: buttons write back "
                                       "(touches, follow-ups, cash, leads). Loopback only.")
    vp2.add_argument("--port", type=int, default=7337)
    vp2.add_argument("--no-open", action="store_true")
    vp2.add_argument("--always-on", action="store_true",
                     help="macOS: install a launchd agent so the console survives reboots")
    sub.add_parser("today", help="what did I actually do today").add_argument(
        "--offset", type=int, default=0, help="days back")
    sub.add_parser("week", help="7-day activity + drift")
    lp = sub.add_parser("loops", help="open loops with evidence")
    lp.add_argument("--all", action="store_true")
    lp.add_argument("--dismiss", metavar="ID_PREFIX")
    dp = sub.add_parser("drift", help="effort vs revenue for the week")
    dp.add_argument("--weeks-ago", type=int, default=0)
    sub.add_parser("venture", help="one venture's ledger").add_argument("name")
    sub.add_parser("search", help="full-text search the ledger").add_argument("query", nargs="+")
    vp = sub.add_parser("daily", help="append-only activity ledger into the daily note")
    vp.add_argument("--write", action="store_true")
    sub.add_parser("demo", help="spin up a fictional portfolio and open the console")
    pp = sub.add_parser("purge", help="shrink the blast radius")
    pp.add_argument("--source")
    pp.add_argument("--before", metavar="ISO_DATE")
    sub.add_parser("status", help="config + watermarks + row counts per source")
    args = p.parse_args()

    if args.cmd is None:  # bare `opsroom` = the live console
        from . import serve as _serve
        return _serve.serve() or 0
    if args.cmd == "init":
        from . import setup
        return setup.run(yes=args.yes)
    if args.cmd == "demo":
        from . import demo
        return demo.run()
    if args.cmd == "serve":
        from . import serve as _serve
        if args.always_on:
            return 0 if _serve.install_always_on(port=args.port) else 1
        return _serve.serve(port=args.port, open_browser=not args.no_open) or 0
    if args.cmd == "sync":
        return cmd_sync(args)
    if args.cmd == "purge":
        if not (args.source or args.before):
            p.error("purge needs --source or --before")
        return cmd_purge(args)
    if args.cmd == "status":
        return cmd_status(args)

    con = db.connect()
    try:
        if args.cmd == "today":
            views.today(con, args.offset)
        elif args.cmd == "week":
            views.week(con)
        elif args.cmd == "loops":
            if args.dismiss:
                views.dismiss_loop(con, args.dismiss)
                con.commit()
            else:
                views.loops(con, args.all)
        elif args.cmd == "drift":
            views.drift(con, args.weeks_ago)
        elif args.cmd == "venture":
            views.venture_view(con, args.name)
        elif args.cmd == "search":
            views.search(con, " ".join(args.query))
        elif args.cmd == "dash":
            path = views.dash(con)
            if not args.no_open:
                import subprocess
                import sys as _s
                opener = {"darwin": "open", "linux": "xdg-open"}.get(_s.platform)
                if opener:
                    subprocess.run([opener, path], check=False)
        elif args.cmd == "sitrep":
            views.sitrep(con, write=args.write)
        elif args.cmd == "daily":
            views.daily_writeback(con, dry_run=not args.write)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
