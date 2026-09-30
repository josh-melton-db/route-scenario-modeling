from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache


DEFAULT_DEMO_HORIZON_DAYS = 28


def parse_demo_date_anchor(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("DEMO_DATE_ANCHOR must be an ISO date (YYYY-MM-DD).") from exc


@lru_cache(maxsize=1)
def demo_date_anchor() -> date:
    """Resolve the demo anchor once so a running process cannot slide at midnight."""

    configured = os.getenv("DEMO_DATE_ANCHOR", "").strip()
    return parse_demo_date_anchor(configured) if configured else _local_today()


def _local_today() -> date:
    return date.today()


def snapshot_published_at(anchor: date) -> datetime:
    return datetime.combine(anchor, time(hour=12), tzinfo=timezone.utc)


def snapshot_version_id(prefix: str, anchor: date) -> str:
    return f"{prefix}_{anchor:%Y%m%d}_V1"


def first_weekday_on_or_after(anchor: date, weekday: int) -> date:
    return anchor + timedelta(days=(weekday - anchor.weekday()) % 7)
