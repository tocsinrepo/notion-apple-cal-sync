"""Build a health page for the calendar sync, straight from what the last runs said.

Offline by design. Reads two local files:
  * state.json  — the link store, one entry per Notion page <-> Apple event pair
  * sync.log    — appended by run-sync.sh, one block per run

and writes two more next to them:
  * health.json — machine readable, in case something else wants it later
  * health.html — single file, no build step, safe to open straight from Finder

Nothing here contacts Notion or iCloud, so it costs nothing to run after every
sync. That also means it reports what the sync BELIEVES, which is the useful
thing: if the engine's view of the world has gone stale, this page shows it.
"""
import datetime as dt
import json
import os
import re
import sys
from string import Template

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.getenv("HEALTH_ROOT", os.path.dirname(DIR))
STATE = os.path.join(ROOT, "state.json")
LOG = os.path.join(ROOT, "sync.log")
OUT_HTML = os.path.join(ROOT, "health.html")
OUT_JSON = os.path.join(ROOT, "health.json")

RUN_HEADER = re.compile(r"^=====\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+=====")
DONE = re.compile(r"total links: (\d+)\s+writes this run: (\d+)")
PAGES = re.compile(r"notion pages: (\d+) in window \((\d+) deferred[^)]*\)\s+apple events: (\d+)")
CAL = re.compile(r"using calendar: (.+)")


def read_runs(limit=12):
    """Most recent runs, newest first, from the appended log blocks."""
    try:
        with open(LOG, errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    runs, cur = [], None
    for ln in lines:
        m = RUN_HEADER.match(ln)
        if m:
            if cur:
                runs.append(cur)
            cur = {"at": m.group(1), "writes": None, "links": None,
                   "pages": None, "deferred": None, "events": None,
                   "calendar": None, "error": None}
            continue
        if cur is None:
            continue
        d = DONE.search(ln)
        if d:
            cur["links"], cur["writes"] = int(d.group(1)), int(d.group(2))
        p = PAGES.search(ln)
        if p:
            cur["pages"] = int(p.group(1))
            cur["deferred"] = int(p.group(2))
            cur["events"] = int(p.group(3))
        c = CAL.search(ln)
        if c:
            cur["calendar"] = c.group(1).strip()
        low = ln.lower()
        if ("traceback" in low or "stop:" in low or "error" in low) and not cur["error"]:
            cur["error"] = ln.strip()[:160]
    if cur:
        runs.append(cur)
    runs.reverse()
    return runs[:limit]


def read_links():
    try:
        with open(STATE) as fh:
            return json.load(fh).get("links", [])
    except (OSError, ValueError):
        return []


def upcoming(links, now, count=6):
    """Next few dated items, parsed out of the stored Notion fingerprints."""
    out = []
    for lk in links:
        canon = lk.get("notion_canon") or ""
        parts = canon.split("|")
        if len(parts) < 4 or not parts[1]:
            continue
        raw, all_day = parts[1], parts[3] == "AD"
        try:
            when = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if when.tzinfo:
                when = when.astimezone().replace(tzinfo=None)
        except ValueError:
            try:
                when = dt.datetime.fromisoformat(raw[:10])
            except ValueError:
                continue
        if when < now - dt.timedelta(hours=12):
            continue
        out.append({"title": lk.get("title") or parts[0] or "(untitled)",
                    "when": when, "all_day": all_day})
    out.sort(key=lambda r: r["when"])
    return out[:count]


def verdict(runs, now):
    if not runs:
        return "fault", "No run has been recorded yet."
    last = runs[0]
    if last["error"]:
        return "fault", "The last run reported an error."
    if last["writes"] is None:
        return "fault", "The last run did not finish."
    try:
        age = (now - dt.datetime.strptime(last["at"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
    except ValueError:
        return "fault", "The last run has no readable timestamp."
    if age > 40:
        return "stale", f"Last run was {int(age)} minutes ago. The timer expects 10."
    if age > 25:
        return "stale", f"Last run was {int(age)} minutes ago. Slightly behind."
    busy = [r["writes"] for r in runs[:6] if r["writes"]]
    if len(busy) >= 5 and min(busy) > 0:
        return "stale", "Six runs in a row wrote something. That can mean a loop."
    return "ok", "Both sides agree. Nothing to do."


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def clock(when, all_day):
    if all_day:
        return "all day"
    h = when.strftime("%I:%M %p").lstrip("0").lower()
    return h


def build():
    now = dt.datetime.now()
    runs = read_runs()
    links = read_links()
    state = verdict(runs, now)
    last = runs[0] if runs else {}
    nxt = upcoming(links, now)

    payload = {
        "generated": now.isoformat(timespec="seconds"),
        "verdict": state[0],
        "reason": state[1],
        "links": len(links),
        "last_run": last.get("at"),
        "writes": last.get("writes"),
        "pages": last.get("pages"),
        "deferred": last.get("deferred"),
        "events": last.get("events"),
        "calendar": last.get("calendar"),
        "runs": [{k: v for k, v in r.items()} for r in runs],
    }
    with open(OUT_JSON, "w") as fh:
        json.dump(payload, fh, indent=1)

    words = {"ok": "Healthy", "stale": "Behind", "fault": "Needs a look"}
    rows = ""
    for r in runs:
        w = r["writes"]
        mark = "quiet" if w == 0 else (f"{w} change" if w == 1 else f"{w} changes")
        cls = "z" if w == 0 else "w"
        if r["error"] or w is None:
            mark, cls = "failed", "f"
        rows += (f'<tr><td class="t">{esc(r["at"][11:16])}</td>'
                 f'<td class="d">{esc(r["at"][:10])}</td>'
                 f'<td class="{cls}">{esc(mark)}</td>'
                 f'<td class="n">{esc(r["links"] if r["links"] is not None else "")}</td></tr>')

    ups = ""
    for r in nxt:
        day = r["when"].strftime("%a %b %d").replace(" 0", " ")
        ups += (f'<li><span class="u-when">{esc(day)}</span>'
                f'<span class="u-time">{esc(clock(r["when"], r["all_day"]))}</span>'
                f'<span class="u-title">{esc(r["title"])}</span></li>')
    if not ups:
        ups = '<li><span class="u-title">Nothing dated in range.</span></li>'

    tpl = Template(HTML)
    html = tpl.safe_substitute(
        verdict=state[0],
        verdict_word=words.get(state[0], "Unknown"),
        reason=esc(state[1]),
        stamp=now.strftime("%A %B %d, %I:%M %p").replace(" 0", " "),
        last_run=esc(last.get("at") or "never"),
        links=len(links),
        pages=esc(last.get("pages") if last.get("pages") is not None else "?"),
        deferred=esc(last.get("deferred") if last.get("deferred") is not None else "?"),
        events=esc(last.get("events") if last.get("events") is not None else "?"),
        calendar=esc(last.get("calendar") or "unknown"),
        writes=esc(last.get("writes") if last.get("writes") is not None else "?"),
        rows=rows,
        upcoming=ups,
    )
    with open(OUT_HTML, "w") as fh:
        fh.write(html)
    return OUT_HTML


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="120">
<title>Calendar sync health</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0D100E; --panel:#151916; --line:#262C28;
    --ink:#E6EAE5; --mut:#838C84; --dim:#5C645E;
    --ok:#6FA97F; --bad:#C4614F;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:var(--bg);color:var(--ink);
    font-family:'Space Grotesk',system-ui,sans-serif;font-size:16px;line-height:1.5;
    -webkit-font-smoothing:antialiased}
  .mono{font-family:'IBM Plex Mono',monospace}
  .wrap{max-width:940px;margin:0 auto;padding:0 26px}

  /* verdict: asymmetric split */
  header{padding:70px 0 34px}
  .top{display:grid;grid-template-columns:1.45fr 1fr;gap:40px;align-items:end}
  .lamp{display:flex;align-items:center;gap:14px;margin-bottom:20px}
  .dot{width:11px;height:11px;border-radius:50%;background:var(--ok)}
  .dot.stale,.dot.fault{background:var(--bad)}
  .lamp span{font-family:'IBM Plex Mono',monospace;font-size:11.5px;
    letter-spacing:.16em;text-transform:uppercase;color:var(--mut)}
  h1{font-size:clamp(38px,6.4vw,62px);font-weight:700;letter-spacing:-.03em;line-height:1}
  .why{color:var(--mut);font-size:17px;margin-top:16px;max-width:34ch}
  .stampbox{border-left:1px solid var(--line);padding-left:22px}
  .stampbox div{font-family:'IBM Plex Mono',monospace;font-size:12.5px;color:var(--dim);
    padding:5px 0}
  .stampbox strong{display:block;color:var(--ink);font-weight:500;font-size:13.5px}

  /* vitals: ledger strip, 4 across with rules */
  .vitals{display:grid;grid-template-columns:repeat(4,1fr);
    border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-top:44px}
  .v{padding:24px 22px;border-right:1px solid var(--line)}
  .v:last-child{border-right:none}
  .v b{display:block;font-family:'IBM Plex Mono',monospace;font-weight:600;
    font-size:33px;letter-spacing:-.02em}
  .v small{display:block;color:var(--mut);font-size:12.5px;margin-top:5px}

  /* runs: bordered table */
  section{padding:52px 0}
  h2{font-size:13px;font-weight:500;letter-spacing:.15em;text-transform:uppercase;
    color:var(--mut);margin-bottom:20px}
  table{width:100%;border-collapse:collapse;font-family:'IBM Plex Mono',monospace;font-size:13.5px}
  th{text-align:left;color:var(--dim);font-weight:400;font-size:11.5px;
    letter-spacing:.1em;text-transform:uppercase;padding-bottom:11px;border-bottom:1px solid var(--line)}
  td{padding:11px 0;border-bottom:1px solid var(--line)}
  td.d{color:var(--dim)}
  td.z{color:var(--mut)}
  td.w{color:var(--ok)}
  td.f{color:var(--bad)}
  td.n{text-align:right;color:var(--dim)}

  /* next up: feature plate + pair */
  .plate{background:var(--panel);border:1px solid var(--line);border-radius:3px;padding:30px 32px}
  ul{list-style:none}
  .plate li{display:grid;grid-template-columns:112px 92px 1fr;gap:14px;
    padding:12px 0;align-items:baseline}
  .plate li+li{border-top:1px solid var(--line)}
  .u-when{font-family:'IBM Plex Mono',monospace;font-size:12.5px;color:var(--mut)}
  .u-time{font-family:'IBM Plex Mono',monospace;font-size:12.5px;color:var(--dim)}
  .u-title{font-size:15.5px}

  /* how: instruction strip */
  .how{display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;
    border-top:1px solid var(--line)}
  .how div{padding:22px 22px 30px;border-right:1px solid var(--line)}
  .how div:last-child{border-right:none}
  .how b{display:block;font-size:15px;font-weight:500;margin-bottom:6px}
  .how p{color:var(--mut);font-size:13.5px}
  footer{border-top:1px solid var(--line);padding:22px 0 60px;
    font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--dim)}

  @media(max-width:760px){
    .top,.vitals,.how{grid-template-columns:1fr}
    .stampbox{border-left:none;border-top:1px solid var(--line);padding:18px 0 0}
    .v{border-right:none;border-bottom:1px solid var(--line)}
    .how div{border-right:none;border-bottom:1px solid var(--line)}
    .plate li{grid-template-columns:1fr;gap:2px}
  }
</style>
</head>
<body>

<header>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="lamp"><span class="dot $verdict"></span><span>Notion and Apple Calendar</span></div>
        <h1>$verdict_word</h1>
        <p class="why">$reason</p>
      </div>
      <div class="stampbox">
        <div>Last run<strong>$last_run</strong></div>
        <div>Writing to<strong>$calendar calendar</strong></div>
        <div>Checked<strong>$stamp</strong></div>
      </div>
    </div>

    <div class="vitals">
      <div class="v"><b>$links</b><small>tasks linked</small></div>
      <div class="v"><b>$pages</b><small>Notion pages in range</small></div>
      <div class="v"><b>$events</b><small>calendar events in range</small></div>
      <div class="v"><b>$writes</b><small>changes on last run</small></div>
    </div>
  </div>
</header>

<section>
  <div class="wrap">
    <h2>Coming up</h2>
    <div class="plate"><ul>$upcoming</ul></div>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>Recent runs</h2>
    <table>
      <tr><th>Time</th><th>Date</th><th>Result</th><th style="text-align:right">Links</th></tr>
      $rows
    </table>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="how">
      <div><b>Automatic</b><p>Every 10 minutes while this Mac is awake.</p></div>
      <div><b>Sync Now</b><p>The app in Applications, CalendarSync. Click it any time.</p></div>
      <div><b>Ask Claude</b><p>Say sync my calendar and it runs here.</p></div>
    </div>
  </div>
</section>

<footer>
  <div class="wrap">
    Quiet is correct. A run that changes nothing means both sides already agree.
    $deferred item(s) sit outside the 30 day back, 180 day forward range and wait their turn.
    This page reloads itself every 2 minutes.
  </div>
</footer>

</body>
</html>
"""


if __name__ == "__main__":
    path = build()
    print(f"[health] wrote {path}", file=sys.stderr)
