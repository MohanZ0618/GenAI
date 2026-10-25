"""Failure injection contract, mutation provenance, and common helpers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from src.generators.bank_generator import METHOD_TO_TYPE
from src.models import FinanceDataset
from src.schema import PRIMARY_KEYS
from src.utils.dates import accounting_period, add_business_days, at_time, parse_date
from src.utils.ids import IDFactory
from src.utils.money import money
from src.utils.random_utils import RandomSource


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def record_id(table: str, row: dict[str, Any]) -> str:
    return "|".join(str(row[key]) for key in PRIMARY_KEYS[table])


@dataclass
class InjectionContext:
    dataset: FinanceDataset
    config: dict[str, Any]
    rng: RandomSource
    ids: IDFactory
    causal_edges: list[dict[str, str]]
    mutation_log: list[dict[str, Any]] = field(default_factory=list)
    claimed: set[tuple[str, str]] = field(default_factory=set)

    def available(self, entity_type: str, entity_id: str) -> bool:
        return (entity_type, entity_id) not in self.claimed

    def claim(self, *entities: tuple[str, str]) -> None:
        self.claimed.update(entities)

    def mutate(
        self,
        case_id: str,
        table: str,
        row: dict[str, Any],
        field_name: str,
        new_value: Any,
        reason: str,
    ) -> None:
        old_value = row[field_name]
        if old_value == new_value:
            return
        self.mutation_log.append(
            {
                "case_id": case_id,
                "table": table,
                "record_id": record_id(table, row),
                "field": field_name,
                "original_value": old_value,
                "mutated_value": new_value,
                "injection_reason": reason,
            }
        )
        row[field_name] = new_value

    def add(self, case_id: str, table: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
        self.dataset.add(table, row)
        self.mutation_log.append(
            {
                "case_id": case_id,
                "table": table,
                "record_id": record_id(table, row),
                "field": "__record__",
                "original_value": None,
                "mutated_value": json.dumps(row, default=_json_default, sort_keys=True),
                "injection_reason": reason,
            }
        )
        return row

    def remove(self, case_id: str, table: str, row: dict[str, Any], reason: str) -> None:
        self.mutation_log.append(
            {
                "case_id": case_id,
                "table": table,
                "record_id": record_id(table, row),
                "field": "__record__",
                "original_value": json.dumps(row, default=_json_default, sort_keys=True),
                "mutated_value": None,
                "injection_reason": reason,
            }
        )
        self.dataset.rows(table).remove(row)

    def edge(self, source_type: str, source_id: str, relationship: str, target_type: str, target_id: str) -> None:
        self.causal_edges.append(
            {
                "source_entity_type": source_type,
                "source_entity_id": source_id,
                "relationship": relationship,
                "target_entity_type": target_type,
                "target_entity_id": target_id,
            }
        )

    def audit(
        self,
        case_id: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        timestamp: str,
        actor_id: str,
        field_name: str = "",
        old_value: str = "",
        new_value: str = "",
        source_system: str = "ERP",
    ) -> str:
        event_id = self.ids.next("EVT")
        self.add(
            case_id,
            "audit_log",
            {
                "event_id": event_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "event_type": event_type,
                "timestamp": timestamp,
                "actor_id": actor_id,
                "field": field_name,
                "old_value": old_value,
                "new_value": new_value,
                "source_system": source_system,
            },
            f"Evidence trail for {event_type}",
        )
        self.edge("audit_event", event_id, "records", entity_type, entity_id)
        return event_id


class FailureInjector(ABC):
    """Interface implemented independently by each primary failure class."""

    failure_type: str
    difficulty: str
    reasoning_hops: int
    severity: str = "medium"

    @abstractmethod
    def inject(self, ctx: InjectionContext, case_id: str) -> dict[str, Any]:
        """Apply one eligible mutation and return exact RCA ground truth."""

    def case(
        self,
        case_id: str,
        primary_type: str,
        primary_id: str,
        vendor_id: str,
        affected: list[tuple[str, str]],
        symptom: str,
        root_cause: str,
        category: str,
        evidence_tables: list[str],
        evidence_ids: list[str],
        resolution: str,
        injected_timestamp: str,
        systems: list[str],
        variant: str,
    ) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "failure_type": self.failure_type,
            "severity": self.severity,
            "primary_entity": {"type": primary_type, "id": primary_id},
            "affected_entities": [{"type": kind, "id": identity} for kind, identity in affected],
            "observed_symptom": symptom,
            "root_cause": root_cause,
            "root_cause_category": category,
            "evidence_required": evidence_tables,
            "evidence_ids": evidence_ids,
            "expected_resolution": resolution,
            "reasoning_hops": self.reasoning_hops,
            "difficulty": self.difficulty,
            "injected_timestamp": injected_timestamp,
            "affected_systems": systems,
            "scenario_variant": variant,
            "group_vendor_id": vendor_id,
        }


def add_payment_gl_and_bank(
    ctx: InjectionContext,
    case_id: str,
    payment: dict[str, Any],
    vendor: dict[str, Any],
    reason: str,
    include_bank: bool = True,
) -> tuple[str, str | None]:
    """Propagate a synthetic payment into a balanced journal and optional bank debit."""
    journal_id = ctx.ids.next("JE")
    for account, debit, credit, memo in (
        ("200000-ACCOUNTS-PAYABLE", payment["payment_amount"], 0, "Payment clears payable"),
        ("100000-CASH", 0, payment["payment_amount"], "Payment cash disbursement"),
    ):
        ctx.add(
            case_id,
            "gl_entries",
            {
                "journal_id": journal_id,
                "journal_line_id": ctx.ids.next("JEL"),
                "transaction_type": "payment",
                "source_transaction_id": payment["payment_id"],
                "posting_date": payment["payment_date"],
                "accounting_period": accounting_period(payment["payment_date"]),
                "gl_account": account,
                "debit": money(debit, str(payment["payment_currency"])),
                "credit": money(credit, str(payment["payment_currency"])),
                "currency": payment["payment_currency"],
                "department": "Finance",
                "cost_center": "CC-03-01",
                "memo": memo,
                "source_system": "ERP-GL",
            },
            reason,
        )
    ctx.edge("payment", str(payment["payment_id"]), "generates", "gl_journal", journal_id)
    if not include_bank:
        return journal_id, None
    method = str(payment["payment_method"])
    clearing = {"ACH": 3, "wire": 1, "check": 10, "virtual_card": 2}[method]
    posted = add_business_days(payment["payment_date"], clearing)
    bank_id = ctx.ids.next("BT")
    accounts = ctx.config["generation"]["bank_accounts"]
    company_account = accounts[-1] if payment["payment_currency"] != "USD" else accounts[sum(str(payment["payment_id"]).encode()) % 2]
    ctx.add(
        case_id,
        "bank_transactions",
        {
            "bank_transaction_id": bank_id,
            "bank_account_id": company_account,
            "transaction_date": payment["payment_date"],
            "posted_date": posted.isoformat(),
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
        reason,
    )
    ctx.edge("payment", str(payment["payment_id"]), "settles_as", "bank_transaction", bank_id)
    return journal_id, bank_id


def shift_month(date_text: str, months: int = 1) -> str:
    value = parse_date(date_text)
    shifted = value.replace(day=1)
    for _ in range(months):
        shifted = (shifted.replace(day=28) + timedelta(days=4)).replace(day=1)
    return shifted.isoformat()

