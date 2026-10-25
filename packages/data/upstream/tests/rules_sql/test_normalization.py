from datetime import date
from decimal import Decimal

from src.rules_sql.normalization import (
    business_days_between,
    edit_sim,
    norm_reference,
    norm_status,
    norm_text,
    parse_date,
    parse_integer,
    parse_ts,
    q_money,
    within_money,
)


def test_frozen_text_and_reference_normalization() -> None:
    assert norm_text(None) is None
    assert norm_text("  Ａcme\u2003  corp  ") == "ACME CORP"
    assert norm_reference(" ００-012.ab ") == "00012AB"
    assert norm_reference("---") is None
    assert norm_status(" credit-applied ") == "CREDIT_APPLIED"


def test_edit_similarity_exact_boundary() -> None:
    assert edit_sim("ABCDEFGHIJ", "ABCDEFGHIX") == Decimal("0.9")
    assert edit_sim(None, "A") is None


def test_strict_dates_timestamps_and_integer_parsing() -> None:
    assert parse_date("2026-06-30") == date(2026, 6, 30)
    assert parse_date("2026-6-30") is None
    assert parse_date("2026-02-30") is None
    assert parse_ts("2026-06-30T12:00:00") is not None
    assert parse_ts("06/30/2026 12:00") is None
    assert parse_ts("2026-06-30T12:00:00+00:00") is None
    assert parse_integer("10") == 10
    assert parse_integer("10.0") is None


def test_decimal_half_up_and_money_boundaries() -> None:
    assert q_money("1.005", "USD") == Decimal("1.01")
    assert q_money("1.5", "JPY") == Decimal("2")
    assert within_money("100.00", "100.01", "USD") is True
    assert within_money("100.00", "100.02", "USD") is False
    assert within_money("100", "101", "JPY") is True
    assert within_money("1", "1", "CHF") is None


def test_business_day_boundaries() -> None:
    assert business_days_between(date(2026, 6, 26), date(2026, 6, 29)) == 1
    assert business_days_between(date(2026, 6, 29), date(2026, 6, 29)) == 0
    assert business_days_between(date(2026, 6, 30), date(2026, 6, 29)) is None
