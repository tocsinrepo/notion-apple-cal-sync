"""Notion side of the sync: read dated pages, create/update/archive pages.

Uses the plain REST API via `requests`. Notion's 2025 API queries a DATA SOURCE
(collection) rather than the database container, so we query the data source
first and fall back to the legacy /databases/{id}/query endpoint.

A normalized "item" dict looks like:
    {source, page_id, title, start, end, all_day, last_mod, archived}
where `start`/`end` are ISO strings ("YYYY-MM-DD" for all-day).
"""
import requests

from config import Config

API = "https://api.notion.com/v1"


class _NotFound(Exception):
    """404 from an endpoint — lets us try a fallback endpoint."""


def _headers():
    return {
        "Authorization": f"Bearer {Config.NOTION_TOKEN}",
        "Notion-Version": Config.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def whoami():
    """Identity of the current token (which integration / workspace). Diagnostic."""
    r = requests.get(f"{API}/users/me", headers=_headers(), timeout=30)
    if r.status_code >= 400:
        return f"(users/me error {r.status_code}: {r.text[:160]})"
    d = r.json()
    name = d.get("name", "?")
    ws = (d.get("bot") or {}).get("workspace_name", "?")
    return f"bot='{name}'  workspace='{ws}'  type={d.get('type','?')}"


def _read_title(props):
    for v in props.values():
        if v.get("type") == "title":
            txt = "".join(t.get("plain_text", "") for t in v.get("title", []))
            return txt or "(untitled)"
    return "(untitled)"


def _page_to_item(pg):
    props = pg.get("properties", {})
    dp = props.get(Config.NOTION_DATE_PROP, {})
    date = dp.get("date")
    if not date or not date.get("start"):
        return None
    start = date["start"]
    end = date.get("end")
    all_day = "T" not in start
    return {
        "source": "notion",
        "page_id": pg["id"],
        "title": _read_title(props),
        "start": start,
        "end": end,
        "all_day": all_day,
        "last_mod": pg.get("last_edited_time", ""),
        "archived": pg.get("archived", False),
    }


def _query(path):
    """Run a paginated query against a full endpoint path; raise _NotFound on 404."""
    items = []
    url = f"{API}{path}"
    payload = {
        "page_size": 100,
        "filter": {"property": Config.NOTION_DATE_PROP, "date": {"is_not_empty": True}},
    }
    cursor = None
    while True:
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if r.status_code == 401:
            raise SystemExit("Notion rejected the token (401). Re-check the NOTION_TOKEN secret.")
        if r.status_code == 404:
            raise _NotFound()
        if r.status_code >= 400:
            raise SystemExit(f"Notion error {r.status_code}: {r.text[:300]}")
        data = r.json()
        for pg in data.get("results", []):
            if pg.get("archived"):
                continue
            it = _page_to_item(pg)
            if it:
                items.append(it)
        if data.get("has_more"):
            cursor = data.get("next_cursor")
        else:
            break
    return items


def fetch_pages():
    """Query the data source first (modern API), then the database (legacy)."""
    attempts = []
    if Config.NOTION_DATA_SOURCE_ID:
        attempts.append(("data source", f"/data_sources/{Config.NOTION_DATA_SOURCE_ID}/query"))
    attempts.append(("database", f"/databases/{Config.NOTION_DATABASE_ID}/query"))
    for label, path in attempts:
        try:
            return _query(path)
        except _NotFound:
            print(f"[notion] {label} endpoint returned 404, trying next…", flush=True)
    raise SystemExit(
        "Notion returned 404 from BOTH the data source and database endpoints. "
        "Open your Tasks database -> ••• -> Connections and confirm 'Apple Cal Sync' "
        "is added with Read content. IDs used: "
        f"data_source={Config.NOTION_DATA_SOURCE_ID}, database={Config.NOTION_DATABASE_ID}."
    )


def _date_payload(item):
    d = {"start": item["start"]}
    if item.get("end"):
        d["end"] = item["end"]
    return d


def _props(item):
    return {
        Config.NOTION_TITLE_PROP: {"title": [{"text": {"content": item["title"]}}]},
        Config.NOTION_DATE_PROP: {"date": _date_payload(item)},
    }


def _parent():
    if Config.NOTION_DATA_SOURCE_ID:
        return {"type": "data_source_id", "data_source_id": Config.NOTION_DATA_SOURCE_ID}
    return {"type": "database_id", "database_id": Config.NOTION_DATABASE_ID}


def create_page(item):
    body = {"parent": _parent(), "properties": _props(item)}
    r = requests.post(f"{API}/pages", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def update_page(page_id, item):
    r = requests.patch(
        f"{API}/pages/{page_id}", headers=_headers(), json={"properties": _props(item)}, timeout=30
    )
    r.raise_for_status()


def archive_page(page_id):
    r = requests.patch(
        f"{API}/pages/{page_id}", headers=_headers(), json={"archived": True}, timeout=30
    )
    r.raise_for_status()
