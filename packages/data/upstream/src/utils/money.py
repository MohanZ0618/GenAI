"""Decimal-only monetary arithmetic."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


CENT = Decimal("0.01")
ZERO = Decimal("0.00")
CURRENCY_QUANTA = {"JPY": Decimal("1"), "USD": CENT, "EUR": CENT, "GBP": CENT, "CAD": CENT}


def decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: object, currency: str = "USD") -> Decimal:
    """Quantize a value using the configured currency precision."""
    return decimal(value).quantize(CURRENCY_QUANTA.get(currency, CENT), rounding=ROUND_HALF_UP)


def sum_money(values: Iterable[object], currency: str = "USD") -> Decimal:
    return money(sum((decimal(value) for value in values), ZERO), currency)


def split_money(total: object, weights: list[object], currency: str = "USD") -> list[Decimal]:
    """Split an amount without losing rounding remainders."""
    amount = money(total, currency)
    normalized = [decimal(weight) for weight in weights]
    denominator = sum(normalized, ZERO)
    if denominator <= 0:
        raise ValueError("Split weights must have a positive sum")
    pieces: list[Decimal] = []
    remaining = amount
    for index, weight in enumerate(normalized):
        piece = remaining if index == len(normalized) - 1 else money(amount * weight / denominator, currency)
        pieces.append(piece)
        remaining -= piece
    return pieces


def as_text(value: object, currency: str = "USD") -> str:
    return format(money(value, currency), "f")

