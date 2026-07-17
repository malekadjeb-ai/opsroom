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
    m = (f"this week {_hm(v['week_min'])} · last touch {_rel(v['last_activity'], today)}"
         + (f" · {v['open_loops']} open loops" if v['open_loops'] else ""))
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


def render(st, drift, loops, sessions):
    links = config.load()["links"]
    today = datetime.now().astimezone().date()
    days = st["days_to_goal"]
    goal = st["goal_usd"]
    cash = st["cash_usd"] or 0
    cash_pct = min(100, round(100 * cash / goal)) if goal else 0
    send, call = _queues(st)
    n_actions = len(send) + len(call) + (1 if st["leads_n"] else 0)

    days_stat = (f"<span class='stat {'bad' if days < 14 else ''}'><b>{days}d</b> left</span>"
                 if days is not None else "<span class='stat'><b>—</b> no goal</span>")
    cash_stat = (f"<span class='stat'><b>${cash:,}</b> / {esc(st['goal_label'])}</span>"
                 if goal else "<span class='stat'><b>—</b> set a goal</span>")
    head_stats = f"""
<div class="strip">
  {days_stat}
  {cash_stat}
  <span class="stat {'warn' if (st['leads_age'] or 0) >= 7 else ''}"><b>{st['leads_n'] or 0}</b> leads ~{st['leads_age'] or 0}d</span>
  <span class="stat"><b>{n_actions}</b> actions queued</span>
</div>"""

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
        leads_html = f"""<div class="card action">
<div class="cardhead"><h3>🚨 RESCUE — ~{st['leads_n']} open leads, aged ~{st['leads_age']}d</h3>
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
    now_tab = ribbon + leak + hero + send_html + call_html + leads_html + empty_hint + (
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
    f" · <span class='warn'>{v['open_loops']} open loops</span>" if v['open_loops'] else ''}</p></div>"""
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
        band = f"<p>Honest band: <b>{esc(st['band'])}</b></p>" if st.get("band") else ""
        money_tab = f"""<div class="card">
<h3>${cash:,} collected of ${goal:,} — {esc(st['goal_label'])}</h3>
<div class="track2"><div class="fill" style="width:{max(cash_pct, 1)}%"></div></div>
<div class="grid stats">
  <div><small>REMAINING</small><div class="big">${remaining:,}</div></div>
  <div><small>DAYS LEFT</small><div class="big {'bad' if (days or 99) < 14 else ''}">{days if days is not None else '—'}</div></div>
  <div><small>NEEDED / DAY</small><div class="big">${per_day:,}</div></div>
  <div><small>BASELINE</small><div>{esc(st['baseline_raw'][:40]) or '—'}</div></div>
</div>{band}
<p class="hint">Cash counts only when <b>collected</b> — not quoted, not booked. Update the
Live-state table in your dashboard note; opsroom reads it on every refresh.</p></div>"""
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
        f"<b>[{l['age_days']}d · {esc(l['signal'] or '')}] {esc(l['venture'] or '')} · {esc(l['project'] or '')}</b>"
        f"<div>{esc(l['description'] or '')}</div><small>{esc((l['evidence'] or '')[:160])}</small></div>"
        for l in loops)
    sess_rows = "".join(
        f"<tr><td>{esc(s['started_at'][:16])}</td><td>{esc(s['venture'] or '')}</td>"
        f"<td>{int(s['duration_min'] or 0)}m</td><td>{esc((s['summary'] or '')[:80])}</td></tr>"
        for s in sessions)
    activity_tab = f"""{alert}
<h3>Effort vs revenue · week of {esc(drift['week_of'])}</h3><table>{drift_rows or '<tr><td>no sessions yet — opsroom sync</td></tr>'}</table>
<h3>Open loops ({len(loops)})</h3>{loop_rows or '<p>none</p>'}
<details><summary>Recent sessions ({len(sessions)})</summary><table>{sess_rows}</table></details>"""

    src = "notes ok" if not st["degraded"] else "notes DEGRADED"
    title_days = f"{days}d left" if days is not None else "opsroom"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Operator Console · {title_days}</title><style>
:root{{--bg:#101014;--card:#1a1b21;--line:#2a2c35;--txt:#d6d7dd;--dim:#8a8d98;
--green:#4caf7d;--red:#e5534b;--amber:#d9a03f;--blue:#4a9eda}}
*{{box-sizing:border-box}}
body{{font:15px/1.5 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--txt);
margin:0;padding-bottom:4rem}}
header{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
padding:10px 16px;z-index:9}}
h1{{font-size:15px;margin:0 0 6px;color:#fff}} h2{{color:#fff;margin:8px 0}}
h3{{margin:0;color:#fff;font-size:15px}}
.strip{{display:flex;gap:14px;flex-wrap:wrap}}
.stat{{color:var(--dim);font-size:13px}} .stat b{{color:#fff;font-size:16px}}
.stat.bad b{{color:var(--red)}} .stat.warn b{{color:var(--amber)}}
nav{{display:flex;gap:6px;margin-top:8px}}
nav a{{flex:1;text-align:center;padding:9px 4px;font:600 13px -apple-system,system-ui,sans-serif;
background:var(--card);color:var(--dim);border:1px solid var(--line);border-radius:8px;
cursor:pointer;text-decoration:none}}
nav a.on{{background:#26313f;color:#fff;border-color:var(--blue)}}
main{{max-width:880px;margin:14px auto;padding:0 16px}}
.panel{{display:none}} .panel.on{{display:block}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}}
.card.action{{border-left:3px solid var(--green)}}
.cardhead{{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}}
.hero{{background:#16211a;border:1px solid #2c4636;border-left:4px solid var(--green);
border-radius:10px;padding:14px;margin:12px 0}}
.hero small{{color:var(--green);font-weight:700;letter-spacing:.5px}}
.hero p{{font-size:17px;color:#fff;margin:6px 0 0}}
.banner{{border-radius:8px;padding:10px 14px;margin:12px 0;font-weight:600}}
.banner.bad{{background:#2a1715;color:#ff8a80;border:1px solid #4a2320}}
.btn{{display:inline-block;background:var(--green);color:#08130c;font-weight:700;
padding:9px 14px;border-radius:8px;text-decoration:none;white-space:nowrap}}
.btn.small{{padding:5px 10px;font-size:13px}}
a{{color:var(--blue)}} a.tel{{color:var(--green);font-weight:600;text-decoration:none}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--dim);font-weight:600}}
tr.rowlink{{cursor:pointer}} tr.rowlink:hover td{{background:#20222a}}
.pill{{display:inline-block;border-radius:10px;padding:1px 9px;font-size:12px;background:#26313f}}
.pill.ok{{color:var(--green)}} .pill.warn{{color:var(--amber);background:#2c2515;margin:3px 6px 0 0}}
.hint{{color:var(--dim);font-size:13px;margin:6px 0 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}}
.track{{background:#26313f;color:var(--blue);border-radius:6px;padding:1px 7px;
font-size:11px;font-weight:800;vertical-align:2px;margin-right:6px}}
.role{{color:var(--dim);margin:4px 0}} .nums{{color:#fff;margin:4px 0;font-size:14px}}
.vlink{{cursor:pointer}} .vlink:hover{{border-color:var(--blue)}}
.open{{color:var(--blue);font-size:13px;font-weight:600}}
.back{{display:inline-block;margin:10px 0 2px;color:var(--blue);text-decoration:none;font-weight:600}}
.vhead .role{{margin-top:2px}}
ol.next{{margin:8px 0 2px;padding-left:22px}} ol.next li{{margin:7px 0}}
ol.next li.first{{color:#fff;font-weight:700}}
.hitem{{border-left:2px solid var(--line);padding:2px 10px;margin:8px 0}}
.hitem b{{color:var(--green)}} .hitem p{{margin:2px 0;font-size:14px}}
ul.files{{margin:6px 0;padding-left:20px}} code{{background:#26272e;padding:1px 6px;border-radius:5px;font-size:13px}}
.search{{width:100%;padding:10px 12px;margin:8px 0;background:#101014;border:1px solid var(--line);
border-radius:8px;color:#fff;font-size:14px}}
details{{border-bottom:1px solid var(--line);padding:6px 0}}
details summary{{cursor:pointer;list-style-position:outside}}
.kvs{{padding:6px 0 10px}}
.kv{{display:grid;grid-template-columns:130px 1fr;gap:8px;padding:4px 0;font-size:14px}}
.kv span{{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.4px}}
.kv.next div{{color:var(--green);font-weight:600}}
details.trap{{margin:16px 0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}}
details.trap summary{{font-weight:700;color:var(--amber)}}
.track2{{height:14px;background:#26272e;border-radius:7px;margin:10px 0}}
.fill{{height:14px;background:var(--green);border-radius:7px}}
.grid.stats div small{{color:var(--dim)}} .big{{font-size:26px;color:#fff}} .big.bad{{color:var(--red)}}
.bar{{display:inline-block;height:10px;background:var(--blue);vertical-align:middle}}
.loop{{border-left:3px solid #555;padding:6px 10px;margin:8px 0;background:var(--card);font-size:14px}}
small{{color:var(--dim)}}
.warn{{color:var(--amber)}}
footer{{color:var(--dim);font-size:12px;text-align:center;margin-top:24px}}
</style></head><body>
<header><h1>⚡ Operator Console · {today.isoformat()}</h1>{head_stats}
<nav>
<a data-t="now" href="#now">🎯 NOW</a>
<a data-t="ventures" href="#ventures">🏢 VENTURES</a>
<a data-t="money" href="#money">💰 MONEY</a>
<a data-t="activity" href="#activity">📊 ACTIVITY</a>
</nav></header>
<main>
<div class="panel" id="now">{now_tab}</div>
<div class="panel" id="ventures">{ventures_tab}</div>
<div class="panel" id="money">{money_tab}</div>
<div class="panel" id="activity">{activity_tab}</div>
{details_pages}
</main>
<footer>generated {esc(datetime.now(timezone.utc).isoformat()[:16])}Z · {esc(src)} ·
refresh: <b>opsroom dash</b> · local file, nothing loads from the network</footer>
<script>
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
