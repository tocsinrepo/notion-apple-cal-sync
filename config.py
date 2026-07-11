"""Configuration, read from environment variables.

Every value has a safe default except the required secrets. Empty strings
coming from GitHub Actions (unset `vars`) fall back to the defaults.
"""
import os

# Jon's Life OS -> Tasks database. Defaulted so it works even if the
# NOTION_DATABASE_ID secret is not set (the setup guide says "already filled in").
DEFAULT_DATABASE_ID = "d3406f60b6654bb48ff38b90cbea34b7"


def _s(name, default=""):
    v = os.getenv(name)
    return v if v else default


def _i(name, default):
    v = os.getenv(name)
    try:
        return int(v) if v else default
    except ValueError:
        return default


def _b(name, default=False):
    v = os.getenv(name)
    if not v:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Notion ---
    NOTION_TOKEN = _s("NOTION_TOKEN")
    NOTION_DATABASE_ID = _s("NOTION_DATABASE_ID", DEFAULT_DATABASE_ID)
    NOTION_TITLE_PROP = _s("NOTION_TITLE_PROP", "Name")
    NOTION_DATE_PROP = _s("NOTION_DATE_PROP", "Due")
    NOTION_VERSION = _s("NOTION_VERSION", "2022-06-28")

    # --- Apple / iCloud CalDAV ---
    APPLE_ID = _s("APPLE_ID")
    APPLE_APP_PASSWORD = _s("APPLE_APP_PASSWORD")
    APPLE_CALDAV_URL = _s("APPLE_CALDAV_URL", "https://caldav.icloud.com")
    APPLE_CALENDAR_NAME = _s("APPLE_CALENDAR_NAME")  # empty = first writable calendar
    APPLE_TZ = _s("APPLE_TZ", "America/New_York")

    # --- Sync behavior ---
    WINDOW_PAST_DAYS = _i("WINDOW_PAST_DAYS", 30)
    WINDOW_FUTURE_DAYS = _i("WINDOW_FUTURE_DAYS", 180)
    ALLOW_DELETES = _b("ALLOW_DELETES", False)   # default OFF — safest for v1
    DRY_RUN = _b("DRY_RUN", False)               # set true to preview with no writes
    STATE_FILE = _s("STATE_FILE", "sync_state.json")

    @classmethod
    def validate(cls):
        # NOTION_DATABASE_ID has a default, so only these three are truly required.
        required = ("NOTION_TOKEN", "APPLE_ID", "APPLE_APP_PASSWORD")
        missing = [n for n in required if not getattr(cls, n)]
        if missing:
            raise SystemExit(
                "STOP: these GitHub secrets are missing or empty: "
                + ", ".join(missing)
                + ". Add them under Settings -> Secrets and variables -> Actions."
            )
