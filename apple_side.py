"""Apple side of the sync via iCloud CalDAV.

Connects with an Apple ID + app-specific password, reads events in a time
window, and creates/updates/deletes VEVENTs. Normalized "item" dict matches the
Notion side: {source, uid, title, start, end, all_day, last_mod}.
All-day events use "YYYY-MM-DD" strings; timed events use ISO datetimes.
"""
import datetime as dt
import uuid

import caldav
from dateutil import parser as dtparser
from dateutil import tz
from icalendar import Calendar, Event

from config import Config

UTC = tz.UTC


def connect():
    client = caldav.DAVClient(
        url=Config.APPLE_CALDAV_URL,
        username=Config.APPLE_ID,
        password=Config.APPLE_APP_PASSWORD,
    )
    try:
        principal = client.principal()
        calendars = principal.calendars()
    except Exception as e:
        raise SystemExit(
            "Could not sign in to iCloud CalDAV. Check that APPLE_ID is your full iCloud "
            "email and APPLE_APP_PASSWORD is an APP-SPECIFIC password (looks like "
            "abcd-efgh-ijkl-mnop), not your normal Apple password. Details: " + str(e)
        )
    if not calendars:
        raise SystemExit("No CalDAV calendars found on this iCloud account.")
    if Config.APPLE_CALENDAR_NAME:
        for c in calendars:
            if (c.name or "") == Config.APPLE_CALENDAR_NAME:
                return c
        names = ", ".join((c.name or "?") for c in calendars)
        raise SystemExit(
            f"Calendar '{Config.APPLE_CALENDAR_NAME}' not found. Available: {names}"
        )
    return calendars[0]


def _date_only(s):
    return dt.date.fromisoformat(str(s)[:10])


def _parse_dt(s, zone):
    d = dtparser.isoparse(str(s))
    if d.tzinfo is None:
        d = d.replace(tzinfo=zone)
    return d


def _to_iso(dtstart, dtend, all_day):
    """Convert an ical component's start/end into our normalized ISO strings."""
    if all_day:
        start = dtstart.isoformat()
        end = None
        if dtend is not None:
            # iCal all-day DTEND is exclusive; store inclusive last day, or drop
            # it entirely for a single-day event.
            span = (dtend - dtstart).days
            if span > 1:
                end = (dtend - dt.timedelta(days=1)).isoformat()
        return start, end
    start = dtstart.isoformat()
    end = dtend.isoformat() if dtend is not None else None
    return start, end


def _component_to_item(comp):
    uid = str(comp.get("uid"))
    summary = str(comp.get("summary", "(untitled)"))
    dtstart = comp.get("dtstart").dt
    dtend_c = comp.get("dtend")
    dtend = dtend_c.dt if dtend_c else None
    all_day = not isinstance(dtstart, dt.datetime)
    start_iso, end_iso = _to_iso(dtstart, dtend, all_day)
    lm = comp.get("last-modified")
    if lm is not None:
        last_mod = lm.dt.isoformat()
    else:
        last_mod = dt.datetime.now(tz=UTC).isoformat()
    return {
        "source": "apple",
        "uid": uid,
        "title": summary,
        "start": start_iso,
        "end": end_iso,
        "all_day": all_day,
        "last_mod": str(last_mod),
    }


def fetch_events(calendar):
    now = dt.datetime.now(tz=tz.gettz(Config.APPLE_TZ))
    start = now - dt.timedelta(days=Config.WINDOW_PAST_DAYS)
    end = now + dt.timedelta(days=Config.WINDOW_FUTURE_DAYS)
    results = calendar.search(start=start, end=end, event=True, expand=False)
    items = []
    for ev in results:
        try:
            cal = Calendar.from_ical(ev.data)
        except Exception:
            continue
        for comp in cal.walk("VEVENT"):
            items.append(_component_to_item(comp))
            break
    return items


def _apply_dates(ev, item):
    zone = tz.gettz(Config.APPLE_TZ)
    if item["all_day"]:
        d = _date_only(item["start"])
        ev.add("dtstart", d)
        if item.get("end"):
            ev.add("dtend", _date_only(item["end"]) + dt.timedelta(days=1))
        else:
            ev.add("dtend", d + dt.timedelta(days=1))
    else:
        s = _parse_dt(item["start"], zone)
        ev.add("dtstart", s)
        if item.get("end"):
            ev.add("dtend", _parse_dt(item["end"], zone))
        else:
            ev.add("dtend", s + dt.timedelta(minutes=30))


def create_event(calendar, item):
    cal = Calendar()
    cal.add("prodid", "-//notion-apple-cal-sync//EN")
    cal.add("version", "2.0")
    ev = Event()
    uid = f"{uuid.uuid4()}@notion-apple-cal-sync"
    ev.add("uid", uid)
    ev.add("summary", item["title"])
    _apply_dates(ev, item)
    ev.add("dtstamp", dt.datetime.now(tz=UTC))
    ev.add("last-modified", dt.datetime.now(tz=UTC))
    cal.add_component(ev)
    calendar.save_event(cal.to_ical().decode("utf-8"))
    return uid


def _find(calendar, uid):
    try:
        return calendar.event_by_uid(uid)
    except Exception:
        for ev in calendar.events():
            if uid in (ev.data or ""):
                return ev
    return None


def update_event(calendar, uid, item):
    ev = _find(calendar, uid)
    if ev is None:
        return create_event(calendar, item)
    cal = Calendar.from_ical(ev.data)
    for comp in cal.walk("VEVENT"):
        if "summary" in comp:
            del comp["summary"]
        comp.add("summary", item["title"])
        for k in ("dtstart", "dtend"):
            if k in comp:
                del comp[k]
        _apply_dates(comp, item)
        if "last-modified" in comp:
            del comp["last-modified"]
        comp.add("last-modified", dt.datetime.now(tz=UTC))
        break
    ev.data = cal.to_ical().decode("utf-8")
    ev.save()
    return uid


def delete_event(calendar, uid):
    ev = _find(calendar, uid)
    if ev is not None:
        ev.delete()
