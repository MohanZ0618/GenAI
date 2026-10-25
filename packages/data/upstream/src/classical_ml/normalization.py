"""Independent normalization primitives frozen for classical ML v1.0."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def norm_text(value: object | None) -> str | None:
    if value is None or str(value) == "":
        return None
    result = " ".join(unicodedata.normalize("NFKC", str(value)).strip().split()).upper()
    return result or None


def norm_status(value: object | None) -> str | None:
    result = norm_text(value)
    return result.replace(" ", "_").replace("-", "_") if result else None


def norm_reference(value: object | None) -> str | None:
    if value is None:
        return None
    result = re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", str(value)).upper())
    return result or None


def trim_id(value: object | None) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def parse_decimal(value: object | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def parse_integer(value: object | None) -> int | None:
    if value is None or not re.fullmatch(r"[+-]?[0-9]+", str(value).strip()):
        return None
    return int(str(value).strip())


def parse_date(value: object | None) -> date | None:
    if value is None or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(value)):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def parse_ts(value: object | None) -> datetime | None:
    if value is None or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?", str(value)):
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return result if result.tzinfo is None else None


def quantum(currency: object | None) -> Decimal | None:
    value = norm_text(currency)
    if value == "JPY":
        return Decimal("1")
    if value in {"USD", "EUR", "GBP", "CAD"}:
        return Decimal("0.01")
    return None


def q_money(value: object | None, currency: object | None) -> Decimal | None:
    amount = parse_decimal(value)
    unit = quantum(currency)
    return amount.quantize(unit, rounding=ROUND_HALF_UP) if amount is not None and unit is not None else None


def within_money(left: object | None, right: object | None, currency: object | None) -> bool | None:
    a, b, unit = q_money(left, currency), q_money(right, currency), quantum(currency)
    return abs(a - b) <= unit if a is not None and b is not None and unit is not None else None


def levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for other_index, other_char in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[other_index] + 1, previous[other_index - 1] + (char != other_char)))
        previous = current
    return previous[-1]


def reference_similarity(left: object | None, right: object | None) -> float | None:
    a, b = norm_reference(left), norm_reference(right)
    if a is None or b is None:
        return None
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))
