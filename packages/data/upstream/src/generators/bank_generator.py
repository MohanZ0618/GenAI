"""External bank activity and mathematically consistent statements."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.generators.context import GenerationContext
from src.generators.gl_generator import _line
from src.utils.dates import accounting_period, add_business_days, month_end, parse_date
from src.utils.money import decimal, money, sum_money


METHOD_TO_TYPE = {"ACH": "ACH debit", "wire": "wire debit", "check": "check clearing", "virtual_card": "card settlement"}


def _company_account(ctx: GenerationContext, currency: str, payment_id: str) -> str:
    accounts = ctx.config["generation"]["bank_accounts"]
    if currency != "USD":
        return str(accounts[-1])
    stable_bucket = sum(payment_id.encode("utf-8")) % 2
    return str(accounts[stable_bucket])


def generate_bank_transactions(ctx: GenerationContext) -> None:
    vendor_by_id = {row["vendor_id"]: row for row in ctx.dataset.rows("vendors")}
    clearing = {
        "ACH": int(ctx.config["generation"]["ach_clearing_business_days"]),
        "wire": int(ctx.config["generation"]["wire_clearing_business_days"]),
        "check": int(ctx.config["generation"]["check_clearing_business_days"]),
        "virtual_card": 2,
    }
    for payment in ctx.dataset.rows("payments"):
        method = str(payment["payment_method"])
        transaction_date = parse_date(str(payment["payment_date"]))
        posted_date = add_business_days(transaction_date, clearing[method])
        bank_id = ctx.ids.next("BT")
        company_account = _company_account(ctx, str(payment["payment_currency"]), str(payment["payment_id"]))
        vendor = vendor_by_id[payment["vendor_id"]]
        ctx.dataset.add(
            "bank_transactions",
            {
                "bank_transaction_id": bank_id,
                "bank_account_id": company_account,
                "transaction_date": transaction_date.isoformat(),
                "posted_date": posted_date.isoformat(),
                "transaction_type": METHOD_TO_TYPE[method],
                "amount": payment["payment_amount"],
                "currency": payment["payment_currency"],
                "direction": "debit",
                "bank_reference": f"BANKREF-{ctx.ids.counters['BT'] + (ctx.config['seed'] % 983):011d}",
                "counterparty_token": vendor["bank_account_token"],
                "payment_reference": payment["reference_number"],
                "status": "posted",
                "source_system": "Bank",
            },
        )
        ctx.edge("payment", str(payment["payment_id"]), "settles_as", "bank_transaction", bank_id)

        # A small set of separately posted and accounted-for fees are legitimate unmatched bank entries.
        if method == "wire" and ctx.rng.py.random() < 0.08:
            fee = money(ctx.rng.choice(["15", "20", "25", "35"]), str(payment["payment_currency"]))
            fee_bank_id = ctx.ids.next("BT")
            ctx.dataset.add(
                "bank_transactions",
                {
                    "bank_transaction_id": fee_bank_id,
                    "bank_account_id": company_account,
                    "transaction_date": transaction_date.isoformat(),
                    "posted_date": posted_date.isoformat(),
                    "transaction_type": "bank fee",
                    "amount": fee,
                    "currency": payment["payment_currency"],
                    "direction": "debit",
                    "bank_reference": f"BANKFEE-{ctx.ids.counters['BT']:010d}",
                    "counterparty_token": "BANK-FEE-DESK",
                    "payment_reference": payment["reference_number"],
                    "status": "posted",
                    "source_system": "Bank",
                },
            )
            journal_id = ctx.ids.next("JE")
            ctx.dataset.add(
                "gl_entries",
                _line(ctx, journal_id, "bank_fee", fee_bank_id, posted_date.isoformat(), "710000-BANK-FEES", fee, 0,
                      str(payment["payment_currency"]), "Finance", "CC-03-01", "Bank fee expense"),
            )
            ctx.dataset.add(
                "gl_entries",
                _line(ctx, journal_id, "bank_fee", fee_bank_id, posted_date.isoformat(), "100000-CASH", 0, fee,
                      str(payment["payment_currency"]), "Finance", "CC-03-01", "Bank fee cash impact"),
            )
            ctx.edge("bank_transaction", fee_bank_id, "generates", "gl_journal", journal_id)
    rebuild_bank_statements(ctx.dataset, ctx.config, ctx.ids)


def _months(first: date, last: date) -> list[date]:
    result: list[date] = []
    current = first.replace(day=1)
    while current <= last:
        result.append(month_end(current))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def rebuild_bank_statements(dataset, config, ids=None) -> None:
    """Recalculate statements after bank-side failure mutations."""
    dataset.tables["bank_statements"] = []
    transactions = dataset.rows("bank_transactions")
    if not transactions:
        return
    accounts = list(config["generation"]["bank_accounts"])
    start = parse_date(config["date_range"]["start"])
    last_posted = max(parse_date(str(row["posted_date"])) for row in transactions)
    by_account_month: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in transactions:
        by_account_month[(str(row["bank_account_id"]), accounting_period(str(row["posted_date"])))].append(row)
    for account_index, account in enumerate(accounts):
        opening = money(5_000_000 + account_index * 2_000_000)
        for statement_date in _months(start, last_posted):
            period = accounting_period(statement_date)
            rows = by_account_month.get((str(account), period), [])
            debits = sum_money((row["amount"] for row in rows if row["direction"] == "debit"))
            credits = sum_money((row["amount"] for row in rows if row["direction"] == "credit"))
            closing = money(decimal(opening) + decimal(credits) - decimal(debits))
            statement_id = ids.next("BST") if ids is not None else f"BST-{account_index + 1:02d}-{period}"
            dataset.add(
                "bank_statements",
                {
                    "bank_statement_id": statement_id,
                    "bank_account_id": account,
                    "statement_date": statement_date.isoformat(),
                    "opening_balance": opening,
                    "closing_balance": closing,
                    "total_debits": debits,
                    "total_credits": credits,
                    "source_system": "Bank",
                },
            )
            opening = closing
