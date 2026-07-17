"""Operator console HTML. Single file, dark, hash-routed (#now / #ventures / #money /
#activity / #v-<venture>), no external resources loaded at page load. User-initiated
deep links (tel:, your mail drafts, your leads dashboard, target websites) are
deliberate — they turn data into one-tap actions. All notes/pipeline-derived text is
html-escaped."""
import html
import re
from datetime import datetime, timezone

from . import config, ventures

PHONE = re.compile(r"\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}")
DOMAIN = re.compile(r"\b([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+(?:/[^\s,;)|<]*)?)", re.I)

esc = html.escape


def _hm(minutes):
    h, m = divmod(int(minutes or 0), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _rel(ts, today):
    if not ts:
        return "never"
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return ts[:10]
    n = (today - d).days
    return "today" if n <= 0 else ("yesterday" if n == 1 else f"{n}d ago")


def _linkify(escaped: str) -> str:
    """tel: links for phone numbers, https links for bare domains, on ALREADY-ESCAPED text."""
    def tel(m):
        return (f"<a class='tel' href='tel:{re.sub(r'[^0-9]', '', m.group(0))}'>"
                f"{m.group(0)}</a>")
    out = PHONE.sub(tel, escaped)

    def site(m):
        d = m.group(1)
        if d.count(".") >= 1 and not d[0].isdigit() and "tel:" not in d and ".md" not in d:
            return f"<a href='https://{d}' target='_blank'>{d}</a>"
        return d
    return DOMAIN.sub(site, out)


def _touch_status(company: str, touch_rows):
    """Fuzzy-match a researched company to its TOUCH LOG row (word-level, len>=4)."""
    cwords = set(w.lower().strip(".,()") for w in company.split())
    for r in touch_rows:
        words = [w.lower().strip(".,()") for w in r["target"].split() if len(w) >= 4]
        if words and any(w in cwords for w in words):
            return r
    return None


def _venture_trackers(key, st):
    meta = ventures.VENTURES.get(key, {})
    mine = [p for p in st["pipelines"] if p["name"].startswith(key)]
    tt = meta.get("target_table")
    if tt:
        mine += [p for p in st["pipelines"] if p["name"] == tt and p not in mine]
    return mine


def _targets_block(key, st):
    """Searchable drill-down list of every researched target for a venture."""
    table, touch = None, []
    for p in _venture_trackers(key, st):
        touch += p["rows"]
        for t in p["tables"]:
            if len(t["rows"]) > (len(table["rows"]) if table else 0):
                table = t
    if not table:
        return ""
    name_col = next((h for h in table["headers"] if h.lower() in ("company", "business", "name", "target")),
                    table["headers"][1] if len(table["headers"]) > 1 else table["headers"][0])
    items = ""
    for row in table["rows"]:
        name = row.get(name_col, "?")
        t = _touch_status(name, touch) if touch else None
        pill = ""
        if t:
            cls = "ok" if any(s in t["status"] for s in ("DRAFTED", "SENT", "REPLIED")) else "warn"
            pill = f"<span class='pill {cls}'>{esc(t['status'])}</span>"
        num = row.get("#", "")
        body = "".join(
            f"<div class='kv'><span>{esc(h)}</span><div>{_linkify(esc(v))}</div></div>"
            for h, v in row.items() if h not in ("#",) and v)
        if t and t.get("next"):
            body += (f"<div class='kv next'><span>NEXT STEP</span>"
                     f"<div>{_linkify(esc(t['next']))}</div></div>")
        items += (f"<details><summary><b>{esc(num)}{'. ' if num else ''}{esc(name)}</b> {pill}</summary>"
                  f"<div class='kvs'>{body}</div></details>")
    lid = f"tl-{key}"
    return f"""<div class="card">
<div class="cardhead"><h3>🎯 {len(table['rows'])} researched targets — click any to open the full brief</h3></div>
<input class="search" placeholder="filter by name, city, type, status…" oninput="filt(this,'{lid}')">
<div id="{lid}">{items}</div></div>"""


def _venture_detail(v, st, today):
    key = v["key"]
    meta = ventures.VENTURES.get(key, {})
    nxt = st["next"].get(key, [])
    next_items = "".join(
        f"<li class='{'first' if i == 0 else ''}'>{_linkify(esc(a))}</li>"
        for i, a in enumerate(nxt))
    hist = st["history"].get(key, [])[:6]
    done_items = "".join(
        f"<div class='hitem'><b>{esc(h['date'])}</b><p>{esc(h['text'][:420])}"
        f"{'…' if len(h['text']) > 420 else ''}</p></div>" for h in hist)
    commits = "".join(
        f"<div class='hitem'><b>{esc(c['ts'][:10])}</b><p>commit: {esc(c['summary'][:120])}</p></div>"
        for c in v["commits"])
    loop_chip = ""
    if v["top_loop"]:
        loop_chip = (f"<div class='banner bad'>OPEN LOOP ({v['top_loop']['age_days']}d): "
                     f"{esc(v['top_loop']['description'][:160])}</div>")
    numbers = ""
    live_row = st["venture_live"].get(key, {})
    if live_row.get("raw"):
        numbers = (f"<div class='card'><h3>📊 Live state (as of "
                   f"{esc(live_row.get('as_of') or '?')})</h3>"
                   f"<p>{_linkify(esc(live_row['raw']))}</p></div>")
    for p in _venture_trackers(key, st):
        if p["totals"]:
            tot = " · ".join(f"{k}: {vv}" for k, vv in list(p["totals"].items())[:6])
            numbers += f"<div class='card'><h3>📊 {esc(p['name'])} totals</h3><p>{esc(tot)}</p></div>"
    files = "".join(f"<li><code>{esc(f)}</code></li>" for f in meta.get("files", []))
    files += "".join(f"<li><code>{esc(p['path'])}</code></li>" for p in _venture_trackers(key, st))
    files_html = f"<div class='card'><h3>📁 Working files</h3><ul class='files'>{files}</ul></div>" if files else ""
    nl = v['open_loops']
    m = (f"this week {_hm(v['week_min'])} · last touch {_rel(v['last_activity'], today)}"
         + (f" · {nl} open loop{'s' if nl != 1 else ''}" if nl else ""))
    return f"""<div class="panel" id="v-{esc(key)}">
<a class="back" href="#ventures">← all ventures</a>
<div class="vhead"><h2>{f"<span class='track'>TRACK {esc(v['track'])}</span> " if v['track'] else ''}{esc(v['label'])}</h2>
<p class="role">{esc(v['revenue'])} · {m}</p></div>
{loop_chip}
<div class="card action"><h3>▶ DO NEXT — in order</h3><ol class="next">{next_items or '<li>nothing queued</li>'}</ol></div>
{numbers}
{_targets_block(key, st)}
<div class="card"><h3>✅ DONE — from your decisions log</h3>
{done_items or "<p class='hint'>no logged decisions mention this venture yet</p>"}
{f"<h3 style='margin-top:10px'>recent commits</h3>{commits}" if commits else ''}</div>
{files_html}
</div>"""


def _queues(st):
    """Send/call queues across ALL trackers' TOUCH LOG rows."""
    send, call = [], []
    for p in st["pipelines"]:
        for r in p["rows"]:
            if any(s in r["status"] for s in ("DRAFTED", "SENT", "REPLIED")):
                send.append(r)
            elif "call" in r["status"].lower():
                call.append(r)
    return send, call


def _f(token, fields: dict, label: str, cls: str = "btn small", confirm: str = "") -> str:
    """One inline POST /act form. All values are server-generated or numeric ids."""
    hidden = "".join(f"<input type='hidden' name='{esc(str(k))}' value='{esc(str(v))}'>"
                     for k, v in fields.items())
    onsub = f" onsubmit=\"return confirm('{esc(confirm)}')\"" if confirm else ""
    return (f"<form class='inline' method='post' action='/act'{onsub}>"
            f"<input type='hidden' name='token' value='{esc(token)}'>{hidden}"
            f"<button class='{cls}'>{esc(label)}</button></form>")


def _serve_now_block(sx) -> str:
    """Promises (anti-leak) + DUE follow-ups + today's tape + quick log + capture + leads."""
    tok = sx["token"]
    tape = sx["tape"]
    tape_html = (f"<div class='tape'><b>{tape['touches']}</b> touches · "
                 f"<b>{tape['calls']}</b> calls · <b>{tape['sends']}</b> sends · "
                 f"<b>${int(tape['cash']):,}</b> collected today</div>")
    # PROMISES — what an agent staged and is still waiting on you
    prom_rows = "".join(
        f"<tr><td><b>{esc(p['venture'] or '?')}</b> "
        f"<span class='loop-meta'>{esc((p['ts'] or '')[:10])}</span>"
        f"<div>{esc(p['text'])}</div></td><td class='acts'>"
        + _f(tok, {"do": "promise", "pid": p["id"], "op": "done"}, "✓ done")
        + _f(tok, {"do": "promise", "pid": p["id"], "op": "dismiss"}, "dismiss", "btn small gray")
        + "</td></tr>" for p in sx["promises"])
    prom_html = (f"<div class='card'><div class='cardhead'>"
                 f"<h3>🔒 PROMISES — {len(sx['promises'])} staged, waiting on you</h3></div>"
                 f"<p class='hint'>Lines an agent staged and parked on your go — money dies in "
                 f"scrollback. Cleared when you act.</p><table>{prom_rows}</table></div>"
                 if sx["promises"] else "")
    due_rows = "".join(
        f"<tr><td><b>{esc(r['target'])}</b><br><small>{esc(r['venture'] or '')} · "
        f"{esc(r['note'] or '')} · due {esc(r['due'])}</small></td><td class='acts'>"
        + _f(tok, {"do": "followup", "fid": r["id"], "op": "done"}, "✓ done")
        + _f(tok, {"do": "followup", "fid": r["id"], "op": "snooze"}, "+1d", "btn small gray")
        + _f(tok, {"do": "followup", "fid": r["id"], "op": "drop"}, "drop", "btn small gray")
        + "</td></tr>" for r in sx["due"])
    due_html = (f"<div class='card action'><div class='cardhead'>"
                f"<h3>⏰ DUE — {len(sx['due'])} follow-ups</h3></div><table>{due_rows}</table></div>"
                if sx["due"] else "")
    vopts = "".join(f"<option value='{esc(k)}'>{esc(v['label'])}</option>"
                    for k, v in ventures.VENTURES.items() if k != "unknown")
    quick = f"""<div class="card"><div class="cardhead"><h3>✍️ LOG IT — every touch schedules its day-3 follow-up</h3></div>
<form class="row" method="post" action="/act">
<input type="hidden" name="token" value="{esc(tok)}"><input type="hidden" name="do" value="touch">
<select name="venture">{vopts}</select>
<input name="target" placeholder="who (company / person)" required>
<select name="kind"><option>call</option><option>email</option><option>text</option><option>dm</option><option>meeting</option></select>
<input name="note" placeholder="note (optional)">
<button class="btn small">log touch</button></form>
<form class="row" method="post" action="/act">
<input type="hidden" name="token" value="{esc(tok)}"><input type="hidden" name="do" value="cash">
<input name="amount" placeholder="$ collected" required inputmode="decimal">
<select name="venture">{vopts}</select>
<input name="what" placeholder="for what">
<button class="btn small">💰 record cash</button></form>
<form class="row" method="post" action="/act">
<input type="hidden" name="token" value="{esc(tok)}"><input type="hidden" name="do" value="lead_add">
<input name="name" placeholder="new lead — name" required>
<input name="phone" placeholder="phone">
<input name="service" placeholder="service">
<button class="btn small">+ lead</button></form>
<form class="row" method="post" action="/act">
<input type="hidden" name="token" value="{esc(tok)}"><input type="hidden" name="do" value="capture">
<input name="text" placeholder="capture a thought → inbox (file it later)" required>
<button class="btn small gray">drop it</button></form></div>"""
    cap_rows = "".join(
        f"<tr><td>{esc(c['text'])}</td><td class='acts'>"
        + _f(tok, {"do": "capture_set", "cid": c["id"], "op": "file"}, "filed", "btn small gray")
        + "</td></tr>" for c in sx["captures"])
    cap_html = (f"<div class='card'><div class='cardhead'><h3>📥 INBOX — {len(sx['captures'])} captured"
                f"</h3></div><table>{cap_rows}</table></div>" if sx["captures"] else "")
    lead_rows = "".join(
        f"<tr><td><b>{esc(r['name'])}</b><br><small>{_linkify(esc(r['phone'] or ''))} · "
        f"{esc(r['service'] or '')} · {esc(r['status'])}"
        f"{' · quoted $' + format(int(r['quoted']), ',') if r['quoted'] else ''}</small></td>"
        f"<td class='acts'>"
        + _f(tok, {"do": "lead_touch", "id": r["id"], "kind": "called"}, "☎ called")
        + f"""<form class='inline' method='post' action='/act'>
<input type='hidden' name='token' value='{esc(tok)}'><input type='hidden' name='do' value='lead_touch'>
<input type='hidden' name='id' value='{r['id']}'><input type='hidden' name='kind' value='collected'>
<input name='amount' placeholder='$' class='amt' inputmode='decimal'>
<button class='btn small'>collected</button></form>"""
        + _f(tok, {"do": "lead_touch", "id": r["id"], "kind": "lost"}, "lost", "btn small gray")
        + "</td></tr>" for r in sx["leads"][:20])
    leads_html = (f"<div class='card'><div class='cardhead'>"
                  f"<h3>📇 LEADS — {len(sx['leads'])} open (oldest touch first)</h3></div>"
                  f"<table>{lead_rows}</table></div>" if sx["leads"] else "")
    return prom_html + due_html + tape_html + quick + cap_html + leads_html


def render(st, drift, loops, sessions, agents=None, serve_ctx=None):
    links = config.load()["links"]
    today = datetime.now().astimezone().date()
    days = st["days_to_goal"]
    goal = st["goal_usd"]
    cash = st["cash_usd"] or 0
    if serve_ctx:
        # served mode: the append-only cash ledger is the source of truth
        cash = int(serve_ctx["cash_total"] or 0)
    cash_pct = min(100, round(100 * cash / goal)) if goal else 0
    send, call = _queues(st)
    n_actions = len(send) + len(call) + (1 if st["leads_n"] else 0)

    def _cell(num, lbl, cls=""):
        return (f"<div class='hud-cell'><span class='hud-num {cls}'>{num}</span>"
                f"<span class='hud-lbl'>{esc(lbl)}</span></div>")

    days_cell = (_cell(f"{days}", "days left", "leak" if days < 14 else "")
                 if days is not None else _cell("—", "no goal set"))
    cash_cell = (_cell(f"${cash:,}", f"of {st['goal_label']}", "go")
                 if goal else _cell("—", "set a goal"))
    lead_cell = _cell(f"{st['leads_n'] or 0}", "open leads",
                      "warn" if (st['leads_age'] or 0) >= 7 else "")
    head_stats = (f"<div class='hud'>{days_cell}{cash_cell}{lead_cell}"
                  f"{_cell(f'{n_actions}', 'actions queued')}</div>")

    # ---------- NOW ----------
    ribbon = ""
    if st["degraded"]:
        note = f"cached {st['cached'][:16]}" if st["cached"] else "no cache"
        ribbon = f"<div class='banner bad'>⚠ notes unreadable ({esc(st['degraded'][0])}) — {esc(note)}</div>"
    leak = (f"<div class='banner bad'>TOP LEAK: {esc(st['top_leak'])}</div>"
            if st["top_leak"] != "none detected" else "")
    hero = f"""<div class="hero"><small>SINGLE HIGHEST CASH ACTION</small>
<p>{esc(st['one_move'] or '—')}</p></div>"""
    send_rows = "".join(
        f"<tr><td><b>{esc(r['target'])}</b></td><td>{esc(r['channel'])}</td>"
        f"<td><span class='pill ok'>{esc(r['status'])}</span></td><td>{_linkify(esc(r['next']))}</td></tr>"
        for r in send)
    mail_btn = (f"<a class='btn' href='{esc(links['mail_drafts'])}' target='_blank'>Open drafts →</a>"
                if links.get("mail_drafts") else "")
    send_html = f"""<div class="card action">
<div class="cardhead"><h3>📧 SEND — {len(send)} drafts staged (60-second review each)</h3>
{mail_btn}</div>
<table>{send_rows}</table></div>""" if send else ""
    call_rows = ""
    for r in call:
        m = PHONE.search(r["next"] or "")
        tel = (f"<a class='btn small' href='tel:{re.sub(r'[^0-9]', '', m.group(0))}'>"
               f"📞 {esc(m.group(0))}</a>") if m else esc(r["next"])
        call_rows += (f"<tr><td><b>{esc(r['target'])}</b></td>"
                      f"<td>{esc((r['next'] or '').split(',')[-1].strip()[:40])}</td><td>{tel}</td></tr>")
    call_html = f"""<div class="card action">
<div class="cardhead"><h3>📞 CALL — {len(call)} phone-first targets</h3></div>
<table>{call_rows}</table></div>""" if call else ""
    leads_html = ""
    if st["leads_n"]:
        leads_btn = (f"<a class='btn' href='{esc(links['leads'])}' target='_blank'>Open leads →</a>"
                     if links.get("leads") else "")
        vlabel = ventures.VENTURES.get(st["leads_venture"], {}).get("label", "")
        aged = f", aged ~{st['leads_age']}d" if st.get("leads_age") else ""
        leads_html = f"""<div class="card action">
<div class="cardhead"><h3>🚨 RESCUE — ~{st['leads_n']} open leads{aged}</h3>
{leads_btn}</div>
<p class='hint'>Work newest first: call → no answer → voicemail + text within 60s. Log every touch
in the tracker.{f" <a href='#v-{esc(st['leads_venture'])}'>open {esc(vlabel)} →</a>" if st['leads_venture'] else ''}</p></div>"""
    stale = "".join(f"<span class='pill warn'>{esc(p['name'])} untouched {p['age_days']}d</span>"
                    for p in st["pipelines"] if p["age_days"] >= 3)
    empty_hint = ""
    if not (send or call or st["leads_n"]):
        empty_hint = ("<div class='card'><p class='hint'>No action queue yet. opsroom builds it from "
                      "your pipeline trackers (TOUCH LOG tables) and dashboard note — run "
                      "<b>opsroom init</b> to wire yours up, or <b>opsroom demo</b> to see a loaded "
                      "console.</p></div>")
    serve_now = _serve_now_block(serve_ctx) if serve_ctx else ""
    if serve_ctx and (serve_ctx["due"] or serve_ctx["leads"]):
        empty_hint = ""
    now_tab = ribbon + leak + hero + serve_now + send_html + call_html + leads_html + empty_hint + (
        f"<p>{stale}</p>" if stale else "")

    # ---------- VENTURES ----------
    rev_cards, trap_rows, trap_min, details_pages = "", "", 0, ""
    for v in st["ventures"]:
        details_pages += _venture_detail(v, st, today)
        first_next = (st["next"].get(v["key"]) or ["—"])[0]
        if v["trap"]:
            trap_min += v["week_min"]
            trap_rows += (f"<tr onclick=\"location.hash='v-{esc(v['key'])}'\" class='rowlink'>"
                          f"<td>{esc(v['label'])}</td><td>{esc(v['revenue'])}</td>"
                          f"<td>{_hm(v['week_min'])}</td><td>{_rel(v['last_activity'], today)}</td>"
                          f"<td>{v['open_loops'] or ''}</td></tr>")
            continue
        rev_cards += f"""<div class="card venture vlink" onclick="location.hash='v-{esc(v['key'])}'">
<div class="cardhead"><h3>{f"<span class='track'>TRACK {esc(v['track'])}</span> " if v['track'] else ''}{esc(v['label'])}</h3>
<span class="open">open →</span></div>
<p class="role">{esc(v['revenue'])}</p>
<p class="nums">▶ {esc(first_next[:110])}</p>
<p class="hint">this week {_hm(v['week_min'])} · last touch {_rel(v['last_activity'], today)}{
    f" · <span class='warn'>{v['open_loops']} open loop{'s' if v['open_loops'] != 1 else ''}</span>" if v['open_loops'] else ''}</p></div>"""
    if not st["ventures"]:
        rev_cards = ("<div class='card'><p class='hint'>No ventures configured yet — run "
                     "<b>opsroom init</b>. Until then, activity is tracked as Unattributed.</p></div>")
    trap_block = f"""<details class="trap"><summary>🪤 Trap zone — $0-revenue builds · {_hm(trap_min)} this week (click a row for detail)</summary>
<table><tr><th>venture</th><th>status</th><th>this week</th><th>last touch</th><th>loops</th></tr>
{trap_rows}</table>
<p class="hint">Rule: no building unless it produces cash in-window or unblocks a revenue-track close.</p>
</details>""" if trap_rows else ""
    ventures_tab = f"""<p class="hint">Click any venture for its full brief: what's next, what's done, every target.</p>
<div class="grid">{rev_cards}</div>{trap_block}"""

    # ---------- MONEY ----------
    if goal:
        remaining = goal - cash
        per_day = round(remaining / days) if days and days > 0 else remaining
        band = (f"<p class='hint'>Honest band: <b>{esc(st['band'])}</b></p>"
                if st.get("band") else "")
        days_danger = "leak" if (days or 99) < 14 else ""
        money_tab = f"""<section class="runway">
  <div class="runway-top">
    <div><span class="rnum go">${cash:,}</span><span class="rlbl">collected</span></div>
    <div class="ar"><span class="rnum">${goal:,}</span><span class="rlbl">{esc(st['goal_label'])}</span></div>
  </div>
  <div class="meter"><div class="meter-fill" style="--pct:{max(cash_pct, 0)}"></div></div>
  <div class="meter-cap"><span>{cash_pct}% of goal</span><span>{100 - cash_pct}% to go</span></div>
  <div class="readout">
    <div><span class="rlbl">remaining</span><span class="rnum">${remaining:,}</span></div>
    <div><span class="rlbl">days left</span><span class="rnum {days_danger}">{days if days is not None else '—'}</span></div>
    <div><span class="rlbl">needed / day</span><span class="rnum">${per_day:,}</span></div>
    <div><span class="rlbl">baseline</span><span class="rnum sm">{esc(st['baseline_raw'][:28]) or '—'}</span></div>
  </div>
  {band}
  <p class="hint">Cash counts only when <b>collected</b> — not quoted, not booked.
  {"Log it in the ledger below and this meter moves." if serve_ctx else
   "Update the Live-state table in your dashboard note; opsroom reads it on every refresh."}</p>
</section>"""
        if serve_ctx:
            entry_rows = "".join(
                f"<tr><td>{esc(e['ts'][:10])}</td><td><b>${int(e['amount']):,}</b></td>"
                f"<td>{esc(e['venture'] or '')}</td><td>{esc(e['what'] or '')}</td></tr>"
                for e in serve_ctx["cash_entries"])
            tok = serve_ctx["token"]
            vopts = "".join(f"<option value='{esc(k)}'>{esc(v['label'])}</option>"
                            for k, v in ventures.VENTURES.items() if k != "unknown")
            money_tab += f"""<div class="card"><div class="cardhead"><h3>🧾 Cash ledger (append-only — this drives the bar)</h3></div>
<form class="row" method="post" action="/act">
<input type="hidden" name="token" value="{esc(tok)}"><input type="hidden" name="do" value="cash">
<input name="amount" placeholder="$ amount" required inputmode="decimal">
<select name="venture">{vopts}</select>
<input name="what" placeholder="for what">
<button class="btn small">record</button></form>
<table>{entry_rows or '<tr><td class="hint">nothing collected yet — the first entry moves the bar</td></tr>'}</table></div>"""
    else:
        money_tab = ("<div class='card'><h3>No goal configured</h3><p class='hint'>Set "
                     "[goal] amount + deadline in config.toml (or run <b>opsroom init</b>) and the "
                     "console turns into a countdown: collected vs goal, days left, needed per day."
                     "</p></div>")

    # ---------- ACTIVITY ----------
    drift_rows = "".join(
        f"<tr><td>{esc(r['label'])}{' 🪤' if r['trap'] else ''}</td><td>{_hm(r['minutes'])}</td>"
        f"<td><div class='bar' style='width:{max(2, r['pct'] * 3)}px'></div> {r['pct']}%</td></tr>"
        for r in drift["rows"])
    alert = ("<div class='banner bad'>⚠ RED ALERT: trap-zone time exceeds revenue-venture time this week.</div>"
             if drift["red_alert"] else "")
    loop_rows = "".join(
        f"<div class='loop'>"
        f"<span class='dot {'leak' if (l['age_days'] or 0) >= 7 else 'warn'}'></span>"
        f"<div class='loop-body'>"
        f"<div class='loop-head'><b>{esc(l['venture'] or '')}</b> · {esc(l['project'] or '')}"
        f"<span class='loop-meta'>{l['age_days']}d · {esc(l['signal'] or '')}</span></div>"
        f"<div>{esc(l['description'] or '')}</div><small>{esc((l['evidence'] or '')[:160])}</small></div>"
        + (_f(serve_ctx["token"], {"do": "loop", "lid": l["id"]}, "dismiss", "btn small gray")
           if serve_ctx else "")
        + "</div>"
        for l in loops)
    sess_rows = "".join(
        f"<tr><td>{esc(s['started_at'][:16])}</td><td>{esc(s['venture'] or '')}</td>"
        f"<td>{int(s['duration_min'] or 0)}m</td><td>{esc((s['summary'] or '')[:80])}</td></tr>"
        for s in sessions)
    agent_rows = "".join(
        f"<tr><td><b>{esc(a['agent'])}</b></td><td>{a['sessions']}</td>"
        f"<td>{_hm(a['minutes']) if a['unit'] == 'time' else str(int(a['minutes'])) + ' msgs'}</td>"
        f"<td>{esc(a['top_venture'])}</td><td>{esc(a['last_seen'])}</td></tr>"
        for a in (agents or []))
    agent_block = (f"<h3>By agent · last 7 days</h3><table>"
                   f"<tr><th>agent</th><th>sessions</th><th>volume</th><th>top venture</th><th>last seen</th></tr>"
                   f"{agent_rows}</table>") if agent_rows else ""
    activity_tab = f"""{alert}
{agent_block}
<h3>Effort vs revenue · week of {esc(drift['week_of'])}</h3><table>{drift_rows or '<tr><td>no sessions yet — opsroom sync</td></tr>'}</table>
<h3>Open loops ({len(loops)})</h3>{loop_rows or '<p>none</p>'}
<details><summary>Recent sessions ({len(sessions)})</summary><table>{sess_rows}</table></details>"""

    src = "notes ok" if not st["degraded"] else "notes DEGRADED"
    title_days = f"{days}d left" if days is not None else "opsroom"
    live_dot = "<span class='live'></span>live console — writes land instantly" if serve_ctx else \
        "static snapshot · <b>opsroom dash</b> to rebuild · nothing loads from the network"
    ctx_btn = ("<a class='ctx' href='/context' target='_blank' title='live operator brief — "
               "paste into any AI chat'>📋 context pack</a>" if serve_ctx else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OPERATOR · {title_days}</title><style>
:root{{
  --bg:#0a0b0d; --bg2:#0d0f12; --surface:#14161a; --surface2:#191c22;
  --line:#24272e; --line2:#31353e;
  --ink:#eceef1; --dim:#9aa1ac; --faint:#6c727d;
  --go:#3ddc84; --go-dim:rgba(61,220,132,.13); --go-line:rgba(61,220,132,.32);
  --warn:#f2b13c; --warn-dim:rgba(242,177,60,.13);
  --leak:#ff5f56; --leak-dim:rgba(255,95,86,.12); --leak-line:rgba(255,95,86,.34);
  --cool:#59c1f0;
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --z-sticky:100;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth;scroll-padding-top:150px}}
body{{font:15px/1.55 var(--sans);color:var(--ink);margin:0;padding-bottom:5rem;overflow-x:hidden;
  background:
    radial-gradient(120% 60% at 50% -10%, rgba(61,220,132,.06), transparent 60%),
    linear-gradient(var(--bg2),var(--bg2));
  background-color:var(--bg);
  -webkit-font-smoothing:antialiased;}}
.mono,.hud-num,.rnum,.loop-meta,td.n,code{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
h2{{color:var(--ink);margin:6px 0 2px;font-size:20px;letter-spacing:-.01em}}
h3{{margin:0;color:var(--ink);font-size:14.5px;font-weight:600;letter-spacing:-.005em}}
b{{font-weight:650}}

/* header / cockpit */
header{{position:sticky;top:0;z-index:var(--z-sticky);
  background:linear-gradient(var(--bg),rgba(10,11,13,.92));backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);padding:11px 18px 0;}}
header::before{{content:"";position:absolute;inset:0 0 auto;height:1px;
  background:linear-gradient(90deg,transparent,var(--go-line),transparent);opacity:.6}}
.brand{{display:flex;align-items:baseline;gap:10px;margin-bottom:9px}}
.brand h1{{font:800 15px/1 var(--sans);letter-spacing:.14em;color:var(--ink);margin:0}}
.brand .bolt{{color:var(--go)}}
.brand time{{font-family:var(--mono);font-size:12px;color:var(--faint);letter-spacing:.02em}}
.brand .ctx{{margin-left:auto;font:600 12px var(--mono);color:var(--cool);
  border:1px solid var(--line);border-radius:7px;padding:5px 10px;background:var(--surface)}}
.brand .ctx:hover{{border-color:var(--go-line);color:var(--go);text-decoration:none}}
.hud{{display:flex;gap:10px;flex-wrap:wrap}}
.hud-cell{{flex:1 1 auto;min-width:92px;display:flex;flex-direction:column;gap:1px;
  padding:7px 12px 8px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}}
.hud-num{{font-size:19px;font-weight:600;color:var(--ink);letter-spacing:-.01em}}
.hud-num.go{{color:var(--go)}} .hud-num.warn{{color:var(--warn)}} .hud-num.leak{{color:var(--leak)}}
.hud-lbl{{font-size:11px;color:var(--dim);letter-spacing:.02em}}
nav{{display:flex;gap:4px;margin:10px -2px 0;padding-bottom:9px}}
nav a{{flex:1;text-align:center;padding:8px 4px;font:600 12.5px var(--sans);letter-spacing:.01em;
  color:var(--dim);border:1px solid transparent;border-radius:8px;cursor:pointer;text-decoration:none;
  transition:color .18s,background .18s}}
nav a:hover{{color:var(--ink);background:var(--surface)}}
nav a.on{{color:var(--go);background:var(--go-dim);border-color:var(--go-line)}}

main{{max-width:920px;margin:18px auto;padding:0 18px}}
.panel{{display:none;scroll-margin-top:150px}} .panel.on{{display:block}}
.panel.on>*{{animation:rise .5s cubic-bezier(.16,1,.3,1) both}}
.panel.on>*:nth-child(2){{animation-delay:.04s}}
.panel.on>*:nth-child(3){{animation-delay:.08s}}
.panel.on>*:nth-child(4){{animation-delay:.12s}}
.panel.on>*:nth-child(n+5){{animation-delay:.15s}}
@keyframes rise{{from{{opacity:0;transform:translateY(7px)}}to{{opacity:1;transform:none}}}}

.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:15px 16px;margin:13px 0;overflow-x:auto}}
.card.action{{background:linear-gradient(var(--go-dim),transparent 70%),var(--surface);
  border-color:var(--go-line)}}
.cardhead{{display:flex;justify-content:space-between;align-items:center;gap:10px;
  flex-wrap:wrap;margin-bottom:9px}}

/* NOW hero — the one move */
.hero{{position:relative;background:
    radial-gradient(90% 120% at 0% 0%, var(--go-dim), transparent 55%),var(--surface);
  border:1px solid var(--go-line);border-radius:12px;padding:16px 18px;margin:13px 0;overflow:hidden}}
.hero::after{{content:"";position:absolute;right:-40px;top:-40px;width:150px;height:150px;
  background:radial-gradient(circle,var(--go-dim),transparent 70%);pointer-events:none}}
.hero small{{color:var(--go);font:600 11px/1 var(--mono);letter-spacing:.14em}}
.hero p{{font-size:18px;line-height:1.4;color:var(--ink);margin:9px 0 0;text-wrap:balance}}

/* banners */
.banner{{border-radius:10px;padding:10px 14px;margin:12px 0;font-weight:600;font-size:14px;
  display:flex;gap:9px;align-items:baseline}}
.banner.bad{{background:var(--leak-dim);color:#ff9b95;border:1px solid var(--leak-line)}}
.banner.bad::before{{content:"▲";color:var(--leak);font-size:11px}}

/* buttons + links */
.btn{{display:inline-block;background:var(--go);color:#052012;font-weight:700;border:0;cursor:pointer;
  padding:9px 15px;border-radius:8px;text-decoration:none;white-space:nowrap;font-family:var(--sans);
  transition:filter .15s,transform .05s}}
.btn:hover{{filter:brightness(1.08)}} .btn:active{{transform:translateY(1px)}}
.btn.small{{padding:5px 11px;font-size:12.5px}}
.btn.gray{{background:var(--surface2);color:var(--dim);border:1px solid var(--line)}}
.btn.gray:hover{{color:var(--ink);filter:none;border-color:var(--line2)}}
a{{color:var(--cool);text-decoration:none}} a:hover{{text-decoration:underline}}
a.tel{{color:var(--go);font-weight:600}}

/* tables */
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
td,th{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
tr:last-child td{{border-bottom:0}}
th{{color:var(--faint);font:600 11px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase}}
tr.rowlink{{cursor:pointer}} tr.rowlink:hover td{{background:var(--surface2)}}
td.acts{{text-align:right;white-space:nowrap}}

.pill{{display:inline-block;border-radius:6px;padding:2px 8px;font:600 11px/1.4 var(--mono);
  background:var(--surface2);color:var(--dim);letter-spacing:.02em}}
.pill.ok{{color:var(--go);background:var(--go-dim)}}
.pill.warn{{color:var(--warn);background:var(--warn-dim)}}
.hint{{color:var(--dim);font-size:13px;margin:8px 0 0;max-width:70ch}}
.hint b{{color:var(--ink)}}
small{{color:var(--dim)}} .warn{{color:var(--warn)}}

/* ventures grid */
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px;margin-top:6px}}
.venture{{cursor:pointer;transition:border-color .18s,transform .12s,box-shadow .18s}}
.venture:hover{{border-color:var(--go-line);transform:translateY(-2px);
  box-shadow:0 8px 24px -14px rgba(0,0,0,.8)}}
.track{{font:700 10px/1 var(--mono);letter-spacing:.08em;color:var(--cool);
  background:rgba(89,193,240,.12);border-radius:5px;padding:3px 6px;margin-right:7px;vertical-align:1px}}
.role{{color:var(--dim);margin:5px 0;font-size:13.5px}}
.nums{{color:var(--ink);margin:7px 0 2px;font-size:14px}}
.open{{color:var(--cool);font:600 12px var(--mono)}}

/* venture detail */
.back{{display:inline-block;margin:6px 0 4px;color:var(--cool);font:600 13px var(--sans)}}
.vhead{{margin:2px 0 10px}} .vhead .role{{margin-top:3px}}
ol.next{{margin:10px 0 2px;padding-left:20px;counter-reset:n}} ol.next li{{margin:8px 0;padding-left:4px}}
ol.next li::marker{{color:var(--faint);font-family:var(--mono);font-size:12px}}
ol.next li.first{{color:var(--ink);font-weight:650}}
.hitem{{display:grid;grid-template-columns:88px 1fr;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}}
.hitem:last-child{{border-bottom:0}}
.hitem b{{color:var(--go);font:600 12px/1.5 var(--mono)}}
.hitem p{{margin:0;font-size:13.5px;color:var(--ink)}}
ul.files{{margin:8px 0 0;padding-left:18px}} ul.files li{{margin:4px 0}}
code{{background:var(--bg2);border:1px solid var(--line);padding:1px 6px;border-radius:5px;font-size:12.5px;color:var(--dim)}}

/* targets search + disclosure */
.search{{width:100%;padding:10px 12px;margin:10px 0;background:var(--bg2);border:1px solid var(--line);
  border-radius:9px;color:var(--ink);font:14px var(--sans)}}
.search:focus{{outline:0;border-color:var(--go-line)}}
.search::placeholder,input::placeholder{{color:var(--faint)}}
details{{border-bottom:1px solid var(--line);padding:8px 0}} details:last-child{{border-bottom:0}}
details summary{{cursor:pointer;list-style-position:outside;color:var(--ink)}}
details summary:hover{{color:var(--go)}}
.kvs{{padding:8px 0 12px}}
.kv{{display:grid;grid-template-columns:128px 1fr;gap:10px;padding:5px 0;font-size:13.5px}}
.kv span{{color:var(--faint);font:600 11px/1.6 var(--mono);letter-spacing:.05em;text-transform:uppercase}}
.kv.next div{{color:var(--go);font-weight:600}}
details.trap{{margin:16px 0;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 16px}}
details.trap summary{{font-weight:650;color:var(--warn)}}

/* MONEY — runway instrument */
.runway{{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px;margin:13px 0}}
.runway-top{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px}}
.runway-top .ar{{text-align:right}}
.rnum{{display:block;font-size:30px;font-weight:600;color:var(--ink);letter-spacing:-.02em;line-height:1.05}}
.rnum.go{{color:var(--go)}} .rnum.leak{{color:var(--leak)}} .rnum.sm{{font-size:15px;font-weight:500}}
.rlbl{{display:block;font-size:12px;color:var(--dim);margin-top:3px}}
.meter{{height:12px;border-radius:7px;background:var(--bg2);border:1px solid var(--line);
  margin:16px 0 6px;overflow:hidden}}
.meter-fill{{height:100%;width:calc(var(--pct)*1%);border-radius:6px;transform-origin:left;
  background:linear-gradient(90deg,#2fbf70,var(--go));animation:fill 1s cubic-bezier(.16,1,.3,1) both}}
@keyframes fill{{from{{transform:scaleX(.001)}}to{{transform:scaleX(1)}}}}
.meter-cap{{display:flex;justify-content:space-between;font:600 11px var(--mono);color:var(--faint)}}
.readout{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px;
  margin:20px 0 4px;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
.readout .rnum{{font-size:20px}} .readout .rlbl{{margin:0 0 5px;order:-1;
  font:600 10.5px var(--mono);letter-spacing:.06em;text-transform:uppercase}}
.readout>div{{display:flex;flex-direction:column}}

/* ACTIVITY */
.bar{{display:inline-block;height:9px;border-radius:5px;background:var(--cool);
  vertical-align:middle;margin-right:7px;opacity:.85}}
.loop{{display:flex;gap:11px;align-items:flex-start;padding:11px 0;border-bottom:1px solid var(--line)}}
.loop:last-child{{border-bottom:0}}
.loop .dot{{width:8px;height:8px;border-radius:50%;margin-top:6px;flex:none}}
.dot.warn{{background:var(--warn);box-shadow:0 0 0 3px var(--warn-dim)}}
.dot.leak{{background:var(--leak);box-shadow:0 0 0 3px var(--leak-dim)}}
.loop-body{{flex:1;min-width:0;font-size:13.5px}}
.loop-head{{color:var(--ink);margin-bottom:2px}}
.loop-meta{{font:600 11px var(--mono);color:var(--faint);margin-left:8px}}
.loop-body div{{color:var(--dim);margin:2px 0}} .loop-body small{{color:var(--faint)}}

/* forms */
form.inline{{display:inline-block;margin:2px 0 0 4px}}
form.row{{display:flex;gap:8px;flex-wrap:wrap;margin:9px 0;align-items:center}}
form.row input,form.row select{{background:var(--bg2);border:1px solid var(--line);border-radius:8px;
  color:var(--ink);padding:9px 11px;font:14px var(--sans);flex:1;min-width:120px}}
form.row input:focus,form.row select:focus{{outline:0;border-color:var(--go-line)}}
form.row select{{flex:0 1 160px;cursor:pointer}}
input.amt{{width:76px;background:var(--bg2);border:1px solid var(--line);border-radius:7px;
  color:var(--ink);padding:5px 9px;font:13px var(--mono)}}
.tape{{display:flex;gap:20px;flex-wrap:wrap;background:var(--surface);border:1px solid var(--line);
  border-radius:12px;padding:13px 16px;margin:13px 0;color:var(--dim);font-size:13px}}
.tape b{{color:var(--ink);font-family:var(--mono);font-size:16px;font-weight:600;margin-right:3px}}

footer{{color:var(--faint);font-size:12px;text-align:center;margin:28px auto 0;
  display:flex;gap:7px;justify-content:center;align-items:center;flex-wrap:wrap}}
footer b{{color:var(--dim)}}
.live{{width:7px;height:7px;border-radius:50%;background:var(--go);display:inline-block;
  box-shadow:0 0 0 0 var(--go-line);animation:pulse 2.4s infinite}}
@keyframes pulse{{0%{{box-shadow:0 0 0 0 var(--go-line)}}70%{{box-shadow:0 0 0 7px transparent}}100%{{box-shadow:0 0 0 0 transparent}}}}

@media (max-width:600px){{
  header{{padding:11px 12px 0}} main{{padding:0 12px}}
  .hud-cell{{min-width:calc(50% - 5px)}}
  .runway-top .rnum{{font-size:24px}}
  nav{{gap:2px;margin:10px 0 0}} nav a{{font-size:10.5px;padding:8px 1px;letter-spacing:-.01em}}
  .readout{{grid-template-columns:repeat(2,1fr)}}
  .loop-meta{{display:block;margin:2px 0 0}}
}}
@media (prefers-reduced-motion:reduce){{
  html{{scroll-behavior:auto}}
  *,.panel.on>*,.meter-fill,.live{{animation:none!important;transition:none!important}}
  .meter-fill{{transform:none}}
}}
</style></head><body>
<header>
  <div class="brand"><h1><span class="bolt">⚡</span> OPERATOR</h1><time>{today.isoformat()}</time>{ctx_btn}</div>
  {head_stats}
  <nav>
    <a data-t="now" href="#now">🎯 NOW</a>
    <a data-t="ventures" href="#ventures">🏢 VENTURES</a>
    <a data-t="money" href="#money">💰 MONEY</a>
    <a data-t="activity" href="#activity">📊 ACTIVITY</a>
  </nav>
</header>
<main>
<div class="panel" id="now">{now_tab}</div>
<div class="panel" id="ventures">{ventures_tab}</div>
<div class="panel" id="money">{money_tab}</div>
<div class="panel" id="activity">{activity_tab}</div>
{details_pages}
</main>
<footer>{live_dot}<span>·</span>{esc(src)}<span>·</span>generated {esc(datetime.now(timezone.utc).isoformat()[:16])}Z</footer>
<script>
{f'''var REV = "{serve_ctx['rev']}";
setInterval(function() {{
  fetch('/version', {{cache: 'no-store'}}).then(function(r) {{ return r.text(); }})
    .then(function(v) {{ if (v !== REV) location.reload(); }}).catch(function() {{}});
}}, 5000);''' if serve_ctx else ''}
function route(){{
  var h = location.hash.slice(1) || 'now';
  var found = false;
  document.querySelectorAll('.panel').forEach(function(p){{
    var on = p.id === h; if (on) found = true; p.classList.toggle('on', on);
  }});
  if (!found) {{ document.getElementById('now').classList.add('on'); h = 'now'; }}
  document.querySelectorAll('nav a').forEach(function(b){{
    b.classList.toggle('on', b.dataset.t === h || (h.indexOf('v-') === 0 && b.dataset.t === 'ventures'));
  }});
  window.scrollTo(0, 0);
}}
function filt(inp, listId){{
  var q = inp.value.toLowerCase();
  document.querySelectorAll('#' + listId + ' details').forEach(function(d){{
    d.style.display = d.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
  }});
}}
window.addEventListener('hashchange', route);
route();
</script></body></html>"""
