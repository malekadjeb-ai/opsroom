"""`opsroom serve` — the console as a local app. Loopback only, zero dependencies.

GET  /          live console, rebuilt from sources + ledgers per request
GET  /version   change counter (page polls this and reloads itself after any write)
GET  /search    one query across activity (FTS) + leads/touches/inbox ledgers
GET  /draft     reply drafter: inbound message -> rails-correct draft from config
GET  /do        the do-it brief for an action (task + rails + live context)
POST /act       every button: touch / followup / cash / lead_add / lead_touch / loop

Security posture (this thing accepts writes, so it's built paranoid):
- binds 127.0.0.1 only, never 0.0.0.0
- every POST requires a per-boot CSRF token embedded in the served forms, so a
  hostile webpage can't drive-by-write to your ledger from your own browser
- Origin/Referer, when present, must be this host
- strict Content-Security-Policy on every response; the page loads zero external
  resources (same no-egress rule as the static console)
- writes go through ops.py only; notes and trackers stay read-only
"""
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import contextpack, db, enrich, inbox, ops, promises, state, ventures, views

PORT = 7337
SYNC_EVERY = 900  # seconds between background source syncs
TOKEN = secrets.token_urlsafe(32)  # per-boot CSRF token; embedded in every form
_REV = [1]
_LOCK = threading.Lock()

CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"


def _bump():
    with _LOCK:
        _REV[0] += 1


def _money(v):
    import re
    m = re.search(r"([\d,]+(?:\.\d+)?)", v or "")
    return float(m.group(1).replace(",", "")) if m else None


def _page(search_q=None) -> bytes:
    from . import dashboard, views
    con = db.connect()
    ocon = ops.connect()
    try:
        st = state.build_state(con)
        d = enrich.drift(con)
        lps = con.execute("""SELECT * FROM loops WHERE status='open'
                             ORDER BY confidence*age_days DESC LIMIT 30""").fetchall()
        sess = con.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 25").fetchall()
        agents = enrich.by_agent(con)
        serve_ctx = {
            "token": TOKEN, "rev": _REV[0],
            "due": ops.followups_due(ocon), "upcoming": ops.followups_upcoming(ocon),
            "cash_total": ops.cash_total(ocon), "cash_entries": ops.cash_entries(ocon),
            "leads": ops.leads_open(ocon), "tape": ops.today_tape(ocon),
            "touches": ops.touches_recent(ocon, 12),
            "promises": promises.open_promises(ocon), "captures": ops.captures_open(ocon),
            "replies": inbox.open_replies(ocon),
            "missed_calls": int(ops.kv_get(ocon, "missed_calls", "0") or 0),
            "spend_total": ops.spend_total(ocon), "spend_entries": ops.spend_entries(ocon),
            "roi": ops.roi_rows(ocon),
        }
        search_ctx = None
        if search_q is not None:
            q = search_q.strip()[:120]
            search_ctx = {"q": q, "events": views.search_events(con, q) if q else [],
                          **(ops.search_ops(ocon, q) if q
                             else {"leads": [], "touches": [], "captures": []})}
        return dashboard.render(st, d, lps, sess, agents, serve_ctx=serve_ctx,
                                search_ctx=search_ctx).encode()
    finally:
        con.close()
        ocon.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "opsroom"

    def log_message(self, fmt, *args):  # no per-request stdout noise
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _host_ok(self) -> bool:
        """Reject DNS-rebinding: the Host header must name this loopback server,
        otherwise a hostile page that rebound its domain to 127.0.0.1 could read
        the console (and the CSRF token inside it)."""
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost")

    def _same_origin(self) -> bool:
        """Origin/Referer, when a browser sends one, must be this server."""
        for h in ("Origin", "Referer"):
            val = self.headers.get(h)
            if val:
                host = urllib.parse.urlparse(val).netloc.split(":")[0].lower()
                return host in ("127.0.0.1", "localhost")
        return True  # header-less client (curl); the token check still gates the write

    def do_GET(self):
        if not self._host_ok():
            self._send(403, b"bad host")
            return
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            try:
                self._send(200, _page())
            except Exception as e:  # never a white page: show the error, keep serving
                self._send(500, f"render failed:\n{type(e).__name__}: {e}".encode(), "text/plain; charset=utf-8")
        elif url.path == "/version":
            self._send(200, str(_REV[0]).encode(), "text/plain")
        elif url.path == "/search":
            q = (urllib.parse.parse_qs(url.query).get("q") or [""])[0]
            try:
                self._send(200, _page(search_q=q))
            except Exception as e:
                self._send(500, f"search failed:\n{type(e).__name__}: {e}".encode(), "text/plain; charset=utf-8")
        elif url.path == "/draft":
            from . import dashboard, drafts
            qs = urllib.parse.parse_qs(url.query)
            venture = (qs.get("venture") or [""])[0][:40]
            msg = (qs.get("msg") or [""])[0][:1500]
            name = (qs.get("name") or [""])[0][:80]
            try:
                draft = drafts.draft_reply(venture, msg, name) if msg else None
                self._send(200, dashboard.draft_page(TOKEN, venture, msg, name, draft).encode())
            except Exception as e:
                self._send(500, f"draft failed:\n{type(e).__name__}: {e}".encode(), "text/plain; charset=utf-8")
        elif url.path == "/do":
            from . import dashboard, dispatch
            qs = urllib.parse.parse_qs(url.query)
            task = (qs.get("task") or [""])[0][:300]
            venture = (qs.get("venture") or [""])[0][:40]
            try:
                brief = dispatch.build_brief(task, venture) if task else ""
                self._send(200, dashboard.do_page(
                    TOKEN, task, venture, brief, dispatch.agent_ready(),
                    history=dispatch.recent()).encode())
            except Exception as e:
                self._send(500, f"brief failed:\n{type(e).__name__}: {e}".encode(), "text/plain; charset=utf-8")
        elif url.path == "/context":
            con = db.connect()
            ocon = ops.connect()
            try:
                txt = contextpack.build(con, ocon, state.build_state(con))
                self._send(200, txt.encode(), "text/plain; charset=utf-8")
            except Exception as e:
                self._send(500, f"context pack failed: {type(e).__name__}: {e}".encode(),
                           "text/plain")
            finally:
                con.close()
                ocon.close()
        else:
            self._send(404, b"not found")

    def do_POST(self):
        if not self._host_ok():
            self._send(403, b"bad host")
            return
        if self.path != "/act":
            self._send(404, b"not found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 100_000:
            self._send(413, b"too large")
            return
        form = {k: v[0] for k, v in
                urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
        if not self._same_origin() or not secrets.compare_digest(
                form.get("token", ""), TOKEN):
            self._send(403, b"bad token - reload the page")
            return
        ocon = ops.connect()
        try:
            do = form.get("do")
            if do == "touch":
                target = form.get("target", "").strip()[:120]
                if target:
                    ops.log_touch(ocon, form.get("venture", "")[:40], target,
                                  form.get("kind", "touch")[:20], form.get("note", "")[:300])
            elif do == "followup":
                ops.followup_set(ocon, int(form["fid"]), form.get("op", "done"))
            elif do == "cash":
                amt = _money(form.get("amount"))
                if amt:
                    ops.log_cash(ocon, amt, form.get("venture", "other")[:40],
                                 form.get("what", "")[:200])
            elif do == "spend":
                amt = _money(form.get("amount"))
                if amt:
                    ops.log_spend(ocon, amt, form.get("venture", "other")[:40],
                                  form.get("what", "")[:200])
            elif do == "lead_add":
                name = form.get("name", "").strip()[:80]
                if name:
                    ops.add_lead(ocon, name, form.get("phone", "")[:30],
                                 form.get("service", "")[:80], form.get("note", "")[:300],
                                 venture=form.get("venture", "")[:40])
            elif do == "lead_touch":
                ops.touch_lead(ocon, int(form["id"]), form.get("kind", "called")[:20],
                               _money(form.get("amount")), form.get("note", "")[:300])
            elif do == "loop":
                con = db.connect()
                try:
                    con.execute("UPDATE loops SET status='dismissed' WHERE id=? AND status='open'",
                                (form.get("lid", "")[:64],))
                    con.commit()
                finally:
                    con.close()
            elif do == "capture":
                text = form.get("text", "").strip()
                if text:
                    ops.capture(ocon, text)
            elif do == "capture_set":
                ops.capture_set(ocon, int(form["cid"]), form.get("op", "file"))
            elif do == "promise":
                promises.promise_set(ocon, form.get("pid", "")[:24], form.get("op", "done"))
            elif do == "reply":
                inbox.reply_set(ocon, form.get("rid", "")[:24], form.get("op", "handled"))
            elif do == "missed_clear":
                ops.kv_set(ocon, "missed_calls", "0")
            elif do == "dispatch":
                from . import dashboard, dispatch
                task = form.get("task", "").strip()[:300]
                venture = form.get("venture", "")[:40]
                if not task:
                    self._send(400, b"no task")
                    return
                result = dispatch.dispatch(task, venture)
                _bump()
                self._send(200, dashboard.do_page(
                    TOKEN, task, venture, dispatch.build_brief(task, venture),
                    dispatch.agent_ready(), result=result,
                    history=dispatch.recent()).encode())
                return
            else:
                self._send(400, b"unknown action")
                return
            _bump()
            self._send(303, b"", extra={"Location": "/"})
        except (KeyError, ValueError):
            self._send(400, b"bad request")
        except Exception as e:
            self._send(500, f"<pre>write failed: {type(e).__name__}: {e}\n"
                            f"Nothing was lost — go back and retry.</pre>".encode())
        finally:
            ocon.close()


def _sync_loop():
    """Background source sync so the page is always fresh. In-process, low ceremony."""
    while True:
        time.sleep(SYNC_EVERY)
        try:
            ventures.refresh()  # pick up config edits (offer, goal, ventures) without a restart
            con = db.connect()
            from .collectors import cli as c_cli, codex as c_codex, git as c_git, \
                fs as c_fs, notes as c_notes, chat as c_chat
            git_r, notes_r = {}, {}
            new = 0
            for name, mod in (("cli", c_cli), ("codex", c_codex), ("git", c_git),
                              ("fs", c_fs), ("notes", c_notes), ("chat", c_chat)):
                try:
                    r = mod.collect(con)
                    new += (r.get("events_new", 0) if isinstance(r, dict) else 0)
                    if name == "git":
                        git_r = r
                    if name == "notes":
                        notes_r = r
                except Exception:
                    continue  # a degraded source never kills the loop
            enrich.build_sessions(con)
            enrich.detect_loops(con, git_r, notes_r)
            con.commit()
            db.enforce_perms()
            con.close()
            oc = ops.connect()
            promises.scan(oc)
            ingested = inbox.watch_tick(oc)  # re-import lead/reply drops on file change
            oc.close()
            # only trigger a client reload when something actually changed, so the
            # /version poller can't wipe half-typed input on an idle 15-minute tick.
            if new or ingested:
                _bump()
        except Exception:
            pass  # next tick retries; the console keeps serving current state


PLIST_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.opsroom.console</string>
  <key>ProgramArguments</key><array>
    <string>{exe}</string><string>serve</string><string>--no-open</string>
    <string>--port</string><string>{port}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
"""


def install_always_on(port=PORT) -> bool:
    """macOS launchd agent so the console survives reboots. Reversible:
    launchctl unload <plist> && rm <plist>."""
    import shutil
    import subprocess
    from pathlib import Path
    exe = shutil.which("opsroom")
    if not exe:
        print("opsroom is not on PATH — install it first (pipx/uv tool), then retry")
        return False
    plist = Path.home() / "Library" / "LaunchAgents" / "com.opsroom.console.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(PLIST_BODY.format(exe=exe, port=port))
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    r = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"always-on {'installed' if ok else 'FAILED'}: {plist}" + ("" if ok else f"\n{r.stderr}"))
    return ok


def serve(port=PORT, open_browser=True):
    threading.Thread(target=_sync_loop, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"opsroom console: {url}  (Ctrl-C stops it)")
    if open_browser:
        import subprocess
        import sys
        opener = {"darwin": "open", "linux": "xdg-open"}.get(sys.platform)
        if opener:
            subprocess.Popen([opener, url])
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nconsole closed")
