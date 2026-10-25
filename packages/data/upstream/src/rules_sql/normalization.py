"""Normalization primitives frozen in baseline specification v1.0."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_REFERENCE_DROP = re.compile(r"[^A-Z0-9]")
_PERIOD = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def norm_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    return " ".join(normalized.split()).upper()


def norm_reference(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).upper()
    result = _REFERENCE_DROP.sub("", normalized)
    return result or None


def levenshtein_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def edit_sim(left: object | None, right: object | None) -> Decimal | None:
    left_reference = norm_reference(left)
    right_reference = norm_reference(right)
    if left_reference is None or right_reference is None:
        return None
    denominator = max(len(left_reference), len(right_reference))
    return Decimal(1) - Decimal(levenshtein_distance(left_reference, right_reference)) / Decimal(denominator)


def norm_status(value: object | None) -> str | None:
    normalized = norm_text(value)
    if normalized is None:
        return None
    return normalized.replace(" ", "_").replace("-", "_")


def parse_date(value: object | None) -> date | None:
    if value is None:
        return None
    text = str(value)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def parse_ts(value: object | None) -> datetime | None:
    if value is None:
        return None
    text = str(value)
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?",
        text,
    ):
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else None


def parse_decimal(value: object | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def parse_integer(value: object | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?[0-9]+", text):
        return None
    return int(text)


def trim_id(value: object | None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def currency_quantum(currency: object | None) -> Decimal | None:
    normalized = norm_text(currency)
    if normalized == "JPY":
        return Decimal("1")
    if normalized in {"USD", "EUR", "GBP", "CAD"}:
        return Decimal("0.01")
    return None


def q_money(value: object | None, currency: object | None) -> Decimal | None:
    amount = parse_decimal(value)
    quantum = currency_quantum(currency)
    if amount is None or quantum is None:
        return None
    return amount.quantize(quantum, rounding=ROUND_HALF_UP)


def within_money(left: object | None, right: object | None, currency: object | None) -> bool | None:
    left_amount = q_money(left, currency)
    right_amount = q_money(right, currency)
    quantum = currency_quantum(currency)
    if left_amount is None or right_amount is None or quantum is None:
        return None
    return abs(left_amount - right_amount) <= quantum


def business_days_between(start: date | None, end: date | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    count = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def valid_accounting_period(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if _PERIOD.fullmatch(text) else None
