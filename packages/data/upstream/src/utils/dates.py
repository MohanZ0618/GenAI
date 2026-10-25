"""Date generation and business-day helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from random import Random


def parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def iso(value: date | datetime) -> str:
    return value.isoformat()


def random_date(rng: Random, start: str | date, end: str | date) -> date:
    first, last = parse_date(start), parse_date(end)
    if first > last:
        raise ValueError("Date range is inverted")
    return first + timedelta(days=rng.randint(0, (last - first).days))


def add_business_days(value: str | date, days: int) -> date:
    current = parse_date(value)
    direction = 1 if days >= 0 else -1
    remaining = abs(days)
    while remaining:
        current += timedelta(days=direction)
        if current.weekday() < 5:
            remaining -= 1
    return current


def month_end(value: str | date) -> date:
    current = parse_date(value)
    next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def accounting_period(value: str | date) -> str:
    current = parse_date(value)
    return f"{current.year:04d}-{current.month:02d}"


def at_time(value: str | date, hour: int, minute: int = 0) -> str:
    current = parse_date(value)
    return datetime(current.year, current.month, current.day, hour, minute).isoformat()

