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
from pathlib import Path

from . import config, contextpack, db, dispatch, enrich, inbox, ops, promises, \
    proposals, sessions, state, ventures, views

PORT = 7337
SYNC_EVERY = 900  # seconds between background source syncs
TOKEN = secrets.token_urlsafe(32)  # per-boot CSRF token; embedded in every form
_REV = [1]
_LOCK = threading.Lock()

CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def _bump():
    with _LOCK:
        _REV[0] += 1


def _money(v):
    """Operator-typed amounts: '$4k' -> 4000, '1.5m' -> 1500000, '2,400' -> 2400,
    '-100' -> -100 (refund). None when there's no number."""
    import re
    m = re.search(r"(-?)\s*\$?\s*([\d,]*\.?\d+)\s*([kKmM]?)\b", (v or "").strip())
    if not m:
        return None
    val = float(m.group(2).replace(",", "") or 0)
    val *= {"k": 1_000, "m": 1_000_000}.get(m.group(3).lower(), 1)
    return -val if m.group(1) else val


def _page(search_q=None) -> bytes:
    from . import dashboard, views
    con = db.connect()
    ocon = ops.connect()
    try:
        try:
            # pick up proposals from runs reaped while the console was down
            proposals.harvest_finished(ocon)
        except Exception:
            pass
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
            "roi": ops.roi_rows(ocon), "sessions": sessions.summary(),
            "dispatches": dispatch.running(),
            "proposals": proposals.pending(ocon),
            "queued": proposals.queued(ocon),
            "setup_needed": config.setup_needed(),
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
        self.send_header("X-Frame-Options", "DENY")  # a framed console = clickjackable writes
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
        elif url.path == "/leads":
            from . import dashboard
            qs = urllib.parse.parse_qs(url.query)
            q = (qs.get("q") or [""])[0].strip()[:120]
            status = (qs.get("status") or [""])[0]
            status = status if status in ("open", "quoted", "won", "lost") else ""
            sort = (qs.get("sort") or ["newest"])[0]
            sort = sort if sort in ("newest", "aged", "quoted") else "newest"
            ocon = ops.connect()
            try:
                rows = ops.leads_all(ocon, q, status, sort)
                counts = ops.leads_counts(ocon)
                self._send(200, dashboard.leads_page(
                    TOKEN, rows, counts, q, status, sort).encode())
            except Exception as e:
                self._send(500, f"leads failed:\n{type(e).__name__}: {e}".encode(),
                           "text/plain; charset=utf-8")
            finally:
                ocon.close()
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
            launched = (qs.get("launched") or [""])[0][:40]
            if launched and not dispatch.TS_RE.match(launched):
                launched = ""
            try:
                lead = int((qs.get("lead") or ["0"])[0])
            except ValueError:
                lead = 0
            try:
                brief = dispatch.build_brief(task, venture, lead_id=lead) if task else ""
                self._send(200, dashboard.do_page(
                    TOKEN, task, venture, brief, dispatch.agent_ready(),
                    history=dispatch.recent(), launched_ts=launched, lead=lead).encode())
            except Exception as e:
                self._send(500, f"brief failed:\n{type(e).__name__}: {e}".encode(), "text/plain; charset=utf-8")
        elif url.path == "/context":
            from . import redact
            con = db.connect()
            ocon = ops.connect()
            try:
                # same fail-closed scrub as the dispatch brief: the browser-served
                # copy must never leak a secret the disk copy would have redacted
                txt = redact.scrub(contextpack.build(con, ocon, state.build_state(con)))
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
                kind = form.get("kind", "called")[:20]
                amt = _money(form.get("amount"))
                if kind in ("collected", "quoted") and not (amt and amt > 0):
                    # silently logging a $0 "collected" is how money vanishes from the goal bar
                    self._send(400, b"type the $ amount first, then mark it "
                                    b"collected/quoted \xe2\x80\x94 go back and retry")
                    return
                ops.touch_lead(ocon, int(form["id"]), kind, amt,
                               form.get("note", "")[:300])
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
                task = form.get("task", "").strip()[:300]
                venture = form.get("venture", "")[:40]
                if not task:
                    self._send(400, b"no task")
                    return
                try:
                    lead = int(form.get("lead") or 0)
                except ValueError:
                    lead = 0
                # the reaper bumps /version when the agent exits, so every open
                # console refreshes itself the moment the work finishes
                result = dispatch.dispatch(task, venture, on_exit=_bump, lead_id=lead)
                _bump()
                # PRG: redirect so the /do page can live-refresh without re-POSTing
                loc = "/do?" + urllib.parse.urlencode(
                    {"task": task, "venture": venture, "launched": result["ts"],
                     **({"lead": str(lead)} if lead else {})})
                self._send(303, b"", extra={"Location": loc})
                return
            elif do == "proposal_apply":
                import json as _json
                pid = int(form["pid"])
                # claim WITHOUT committing: the ops write below commits, landing
                # claim + ledger write in one transaction. rowcount 0 = double-tap.
                row = proposals.claim(ocon, pid, "applied")
                if row is not None:
                    payload = _json.loads(row["payload"])
                    try:
                        if payload["verb"] == "dispatch":
                            ocon.commit()  # persist the claim before launching
                            if dispatch.running():
                                # an agent is already working: queue it to auto-fire
                                # when the runway clears (F1 meets the work queue)
                                proposals.enqueue(ocon, payload["task"],
                                                  payload.get("venture", ""),
                                                  lead=payload.get("lead", 0),
                                                  source=row["dispatch_ts"] or "operator")
                            else:
                                dispatch.dispatch(payload["task"], payload["venture"],
                                                  on_exit=_bump)
                        else:
                            proposals.apply_payload(ocon, payload)
                    except Exception:
                        proposals.unclaim(ocon, pid)  # retryable, nothing lost
                        raise
            elif do == "proposal_dismiss":
                proposals.dismiss(ocon, int(form["pid"]))
            elif do == "dispatch_queue":
                task = form.get("task", "").strip()[:300]
                venture = form.get("venture", "")[:40]
                if not task:
                    self._send(400, b"no task")
                    return
                try:
                    lead = int(form.get("lead") or 0)
                except ValueError:
                    lead = 0
                proposals.enqueue(ocon, task, venture, lead=lead)
                if not dispatch.running():  # runway already clear: fire immediately
                    dispatch.fire_next(on_exit=_bump)
            elif do == "setup_save":
                from . import setup
                if not config.setup_needed(config.load(force=True)):
                    self._send(409, b"config already has a goal or ventures - "
                                    b"edit config.toml or rerun opsroom init")
                    return
                amt = _money(form.get("goal_amount"))
                if not (amt and amt > 0):
                    self._send(400, b"goal amount must be a positive number")
                    return
                goal = {"amount": int(amt),
                        "deadline": form.get("goal_deadline", "").strip()[:10],
                        "label": form.get("goal_label", "").strip()[:80]}
                vs, seen = [], set()
                for i in (1, 2, 3):
                    name = form.get(f"v{i}_name", "").strip()[:80]
                    if not name:
                        continue
                    key = setup.slug(name)
                    if key in seen:
                        continue
                    seen.add(key)
                    needles = [key]
                    path = form.get(f"v{i}_path", "").strip()[:120]
                    base = Path(path).name.lower() if path else ""
                    if base and base != key:
                        needles.append(base)  # folder name only — stored, never executed
                    vs.append({"key": key, "label": name, "trap": False,
                               "offer": form.get(f"v{i}_offer", "").strip()[:200],
                               "needles": needles})
                try:
                    setup.write_web_setup(goal, vs)
                except ValueError as ve:
                    # e.g. a settings-only config that already has [agent]:
                    # the page must never rewrite it
                    self._send(409, str(ve).encode(), "text/plain; charset=utf-8")
                    return
                config.load(force=True)
                ventures.refresh()  # the console re-renders configured, no restart
            else:
                self._send(400, b"unknown action")
                return
            _bump()
            self._send(303, b"", extra={"Location": "/"})
        except (KeyError, ValueError):
            self._send(400, b"bad request")
        except Exception as e:
            # text/plain, not HTML: the exception message can carry ingested text
            self._send(500, f"write failed: {type(e).__name__}: {e}\n"
                            f"Nothing was lost — go back and retry.".encode(),
                       "text/plain; charset=utf-8")
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
            try:
                for name, mod in (("cli", c_cli), ("codex", c_codex), ("git", c_git),
                                  ("fs", c_fs), ("notes", c_notes), ("chat", c_chat)):
                    try:
                        r = mod.collect(con)
                        new += (r.get("events_new", 0) if isinstance(r, dict) else 0)
                        if name == "git":
                            git_r = r
                        if name == "notes":
                            notes_r = r
                        # advance the watermark and commit per collector, exactly like
                        # `opsroom sync` — otherwise fs re-emits its whole window every
                        # tick (event bloat + a page reload that wipes typed input),
                        # and one bad collector rolls back every good one's events
                        db.set_watermark(con, name, "ok", last_ts=r.get("watermark")
                                         if isinstance(r, dict) else None)
                        con.commit()
                    except Exception:
                        db.set_watermark(con, name, "failed")
                        con.commit()
                        continue  # a degraded source never kills the loop
                enrich.build_sessions(con)
                enrich.detect_loops(con, git_r, notes_r)
                con.commit()
                db.enforce_perms()
            finally:
                con.close()
            oc = ops.connect()
            try:
                promises.scan(oc)
                ingested = inbox.watch_tick(oc)  # re-import lead/reply drops on file change
            finally:
                oc.close()
            try:
                # rescue queued dispatches stranded by a console restart
                if dispatch.fire_next(on_exit=_bump):
                    _bump()
            except Exception:
                pass
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
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"  # actual port (port=0 = ephemeral)
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
