"""Faithful deterministic implementation of frozen Rules/SQL baseline v1.0."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Callable, Iterable

from src.rules_sql.normalization import (
    business_days_between,
    currency_quantum,
    edit_sim,
    norm_reference,
    norm_status,
    norm_text,
    parse_date,
    parse_decimal,
    parse_integer,
    parse_ts,
    q_money,
    trim_id,
    valid_accounting_period,
    within_money,
)
from src.rules_sql.registry import PRECEDENCE_INDEX, RULES, RuleDefinition
from src.rules_sql.store import TableStore
from src.schema import PRIMARY_KEYS


ANOMALY = "ANOMALY"
MATCH = "MATCH"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


@dataclass
class RuleTrace:
    rule_id: str
    failure_type: str
    tier: int
    hop_count: int
    status: str
    reason: str
    evidence_record_ids: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    evidence_contract_pass: bool = True
    evidence_contract_notes: list[str] = field(default_factory=list)
    subject_ids: list[str] = field(default_factory=list)

    def serializable(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CasePrediction:
    case_id: str
    method: str
    is_anomaly: bool | None
    predicted_failure_type: str | None
    confidence: None
    evidence_record_ids: list[str]
    triggered_rule_id: str
    hop_count: int
    status: str
    reason: str
    rule_traces: list[dict[str, Any]]
    collision: dict[str, Any]
    latency_ns: int

    def serializable(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class F01Parameters:
    duplicate_date_window_days: int = 14
    duplicate_reference_similarity: Decimal = Decimal("0.90")


class FrozenRulesBaseline:
    """In-memory SQL-style deterministic engine with explicit tri-state traces."""

    def __init__(self, data_dir: Path, f01: F01Parameters | None = None):
        self.store = TableStore(data_dir)
        self.f01 = f01 or F01Parameters()
        self.as_of_date = date(2026, 6, 30)
        self.po_tolerance_percent = Decimal("2.0")
        self.cross_match_days = 7
        self.clearing_limits = {"ACH": 3, "WIRE": 1, "CHECK": 10, "VIRTUAL_CARD": 2}
        self.rule_functions: dict[str, Callable[[str], RuleTrace]] = {
            "RSQL_F01_V1": self._f01,
            "RSQL_F02_V1": self._f02,
            "RSQL_F03_V1": self._f03,
            "RSQL_F04_V1": self._f04,
            "RSQL_F05_V1": self._f05,
            "RSQL_F06_V1": self._f06,
            "RSQL_F07_V1": self._f07,
            "RSQL_F08_V1": self._f08,
            "RSQL_F09_V1": self._f09,
            "RSQL_F10_V1": self._f10,
            "RSQL_F11_V1": self._f11,
            "RSQL_F12_V1": self._f12,
            "RSQL_F13_V1": self._f13,
            "RSQL_F14_V1": self._f14,
        }
        self.rules_by_id = {rule.rule_id: rule for rule in RULES}

    def _evidence_id(self, table: str, row: dict[str, str]) -> str:
        values = [self.store.field(table, row, field) or "" for field in PRIMARY_KEYS[table]]
        return f"{table}:{'|'.join(values)}"

    def _trace(
        self,
        rule_number: int,
        status: str,
        reason: str,
        evidence: Iterable[tuple[str, dict[str, str]]] = (),
        required: Iterable[str] = (),
        absence_tables: Iterable[str] = (),
        notes: Iterable[str] = (),
        subject_ids: Iterable[str] = (),
    ) -> RuleTrace:
        rule = RULES[rule_number - 1]
        evidence_ids = sorted({self._evidence_id(table, row) for table, row in evidence})
        returned_tables = {value.split(":", 1)[0] for value in evidence_ids}
        required_list = list(required)
        absence = set(absence_tables)
        missing = [table for table in required_list if table not in returned_tables and table not in absence]
        incomplete_absence = [table for table in absence if not self.store.complete.get(table, False)]
        contract_notes = list(notes)
        if missing:
            contract_notes.append(f"missing returned record tables: {','.join(sorted(missing))}")
        if incomplete_absence:
            contract_notes.append(f"uncertified absence tables: {','.join(sorted(incomplete_absence))}")
        contract_pass = status != ANOMALY or (not missing and not incomplete_absence)
        return RuleTrace(
            rule_id=rule.rule_id,
            failure_type=rule.failure_type,
            tier=rule.tier,
            hop_count=rule.hop_count,
            status=status,
            reason=reason,
            evidence_record_ids=evidence_ids,
            required_evidence=required_list,
            evidence_contract_pass=contract_pass,
            evidence_contract_notes=contract_notes,
            subject_ids=sorted(set(subject_ids)),
        )

    def _unavailable(self, number: int, subject: str, tables: Iterable[str]) -> RuleTrace | None:
        missing = self.store.require_tables(tables)
        if not missing:
            return None
        return self._trace(
            number,
            INSUFFICIENT,
            f"Required table snapshot(s) unavailable for {subject}: {', '.join(sorted(missing))}.",
            subject_ids=[subject],
        )

    def _combine(self, traces: list[RuleTrace]) -> RuleTrace:
        if not traces:
            raise ValueError("cannot combine empty trace list")
        for desired in (ANOMALY, INSUFFICIENT, MATCH):
            selected = [trace for trace in traces if trace.status == desired]
            if selected:
                selected.sort(key=lambda trace: (trace.subject_ids, trace.reason))
                first = selected[0]
                first.subject_ids = sorted({value for trace in selected for value in trace.subject_ids})
                if desired == ANOMALY:
                    first.evidence_record_ids = sorted({value for trace in selected for value in trace.evidence_record_ids})
                    first.evidence_contract_pass = all(trace.evidence_contract_pass for trace in selected)
                    first.evidence_contract_notes = sorted({value for trace in selected for value in trace.evidence_contract_notes})
                return first
        raise AssertionError("unknown trace state")

    def _scope(self, entity_type: str, entity_id: str) -> tuple[dict[str, set[str]], str | None]:
        entity_type = norm_status(entity_type) or ""
        identity = trim_id(entity_id) or ""
        scope = {"invoices": set(), "payments": set(), "bank_transactions": set()}
        issue: str | None = None
        if entity_type == "INVOICE":
            scope["invoices"].add(identity)
        elif entity_type == "PAYMENT":
            scope["payments"].add(identity)
        elif entity_type == "BANK_TRANSACTION":
            scope["bank_transactions"].add(identity)
        elif entity_type == "GL_JOURNAL":
            rows = [
                row for row in self.store.rows("gl_entries")
                if trim_id(self.store.field("gl_entries", row, "journal_id")) == identity
            ]
            payment_ids = {
                trim_id(self.store.field("gl_entries", row, "source_transaction_id"))
                for row in rows
                if norm_status(self.store.field("gl_entries", row, "transaction_type")) == "PAYMENT"
            }
            scope["payments"].update(value for value in payment_ids if value)
            if not rows:
                issue = f"Primary GL journal {identity} is missing."
            elif not scope["payments"]:
                issue = f"GL journal {identity} has no source-linked PAYMENT relationship."
        else:
            issue = f"Unsupported primary entity type {entity_type or '<NULL>'}."

        # Resolve references in both directions, then allocation relationships in both directions.
        for bank_id in list(scope["bank_transactions"]):
            bank = self.store.row("bank_transactions", bank_id)
            if bank:
                ref = norm_reference(self.store.field("bank_transactions", bank, "payment_reference"))
                if ref:
                    scope["payments"].update(
                        trim_id(self.store.field("payments", payment, "payment_id")) or ""
                        for payment in self.store.payments_by_reference.get(ref, [])
                    )
        for payment_id in list(scope["payments"]):
            for allocation in self.store.allocations_by_payment.get(payment_id, []):
                invoice_id = trim_id(self.store.field("payment_allocations", allocation, "invoice_id"))
                if invoice_id:
                    scope["invoices"].add(invoice_id)
        for invoice_id in list(scope["invoices"]):
            for allocation in self.store.allocations_by_invoice.get(invoice_id, []):
                payment_id = trim_id(self.store.field("payment_allocations", allocation, "payment_id"))
                if payment_id:
                    scope["payments"].add(payment_id)
        for payment_id in list(scope["payments"]):
            payment = self.store.row("payments", payment_id)
            if payment:
                ref = norm_reference(self.store.field("payments", payment, "reference_number"))
                if ref:
                    scope["bank_transactions"].update(
                        trim_id(self.store.field("bank_transactions", bank, "bank_transaction_id")) or ""
                        for bank in self.store.banks_by_reference.get(ref, [])
                    )
        for values in scope.values():
            values.discard("")
        return scope, issue

    def predict_case(self, case_id: str, primary_entity_type: str, primary_entity_id: str) -> CasePrediction:
        started = perf_counter_ns()
        scope, scope_issue = self._scope(primary_entity_type, primary_entity_id)
        traces: list[RuleTrace] = []
        invoice_rules = (1, 2, 3, 4, 6, 7)
        payment_rules = (5, 8, 9, 10, 11, 12, 14)
        bank_rules = (13,)
        for number in invoice_rules:
            subjects = sorted(scope["invoices"])
            if subjects:
                traces.append(self._combine([self.rule_functions[f"RSQL_F{number:02d}_V1"](subject) for subject in subjects]))
        for number in payment_rules:
            subjects = sorted(scope["payments"])
            if subjects:
                traces.append(self._combine([self.rule_functions[f"RSQL_F{number:02d}_V1"](subject) for subject in subjects]))
        for number in bank_rules:
            subjects = sorted(scope["bank_transactions"])
            if subjects:
                traces.append(self._combine([self.rule_functions[f"RSQL_F{number:02d}_V1"](subject) for subject in subjects]))
        if scope["payments"]:
            traces.append(self._f15(sorted(scope["payments"])))

        anomaly_traces = sorted(
            (trace for trace in traces if trace.status == ANOMALY),
            key=lambda trace: PRECEDENCE_INDEX[trace.failure_type],
        )
        collision = {
            "case_id": case_id,
            "all_triggered_rules": [trace.rule_id for trace in anomaly_traces],
            "all_triggered_failure_types": [trace.failure_type for trace in anomaly_traces],
            "selected_output": anomaly_traces[0].failure_type if anomaly_traces else None,
            "precedence_rule_applied": len(anomaly_traces) > 1,
            "matches_frozen_precedence": True,
        }
        if anomaly_traces:
            selected = anomaly_traces[0]
            status = ANOMALY
            is_anomaly: bool | None = True
            failure = selected.failure_type
            triggered = selected.rule_id
            hop_count = selected.hop_count
            evidence = selected.evidence_record_ids
            reason = selected.reason
        else:
            insufficient = [trace for trace in traces if trace.status == INSUFFICIENT]
            if insufficient or scope_issue or not traces:
                status = INSUFFICIENT
                is_anomaly = None
                failure = None
                triggered = "RSQL_EVIDENCE_GATE_V1"
                hop_count = max((trace.hop_count for trace in insufficient), default=0)
                evidence = sorted({value for trace in insufficient for value in trace.evidence_record_ids})
                reasons = [trace.reason for trace in insufficient]
                if scope_issue:
                    reasons.insert(0, scope_issue)
                if not reasons:
                    reasons.append("No applicable frozen rule could be reached from the primary entity.")
                reason = " ".join(reasons)
            else:
                status = MATCH
                is_anomaly = False
                failure = "NO_FAILURE"
                triggered = "RSQL_NO_ANOMALY_V1"
                hop_count = max(trace.hop_count for trace in traces)
                evidence = sorted({value for trace in traces for value in trace.evidence_record_ids})
                reason = f"All {len(traces)} applicable frozen rules returned MATCH with sufficient evidence."
        latency = perf_counter_ns() - started
        return CasePrediction(
            case_id=case_id,
            method="rules_sql",
            is_anomaly=is_anomaly,
            predicted_failure_type=failure,
            confidence=None,
            evidence_record_ids=evidence,
            triggered_rule_id=triggered,
            hop_count=hop_count,
            status=status,
            reason=reason,
            rule_traces=[trace.serializable() for trace in sorted(traces, key=lambda value: value.rule_id)],
            collision=collision,
            latency_ns=latency,
        )

    def _f01(self, invoice_id: str) -> RuleTrace:
        unavailable = self._unavailable(1, invoice_id, ("invoices",))
        if unavailable:
            return unavailable
        invoice = self.store.row("invoices", invoice_id)
        if invoice is None:
            return self._trace(1, INSUFFICIENT, f"Primary invoice {invoice_id} is missing.", subject_ids=[invoice_id])
        evidence = [("invoices", invoice)]
        status = norm_status(self.store.field("invoices", invoice, "status"))
        total = parse_decimal(self.store.field("invoices", invoice, "invoice_total"))
        if status is None or total is None:
            return self._trace(1, INSUFFICIENT, f"Invoice {invoice_id} has missing status or amount.", evidence, subject_ids=[invoice_id])
        if status in {"CANCELED", "CREDIT_APPLIED"} or total <= 0:
            return self._trace(1, MATCH, f"Invoice {invoice_id} is canceled, credited, or nonpositive and excluded from F01.", evidence, subject_ids=[invoice_id])
        vendor = trim_id(self.store.field("invoices", invoice, "vendor_id"))
        currency = norm_text(self.store.field("invoices", invoice, "currency"))
        reference = norm_reference(self.store.field("invoices", invoice, "invoice_number"))
        invoice_date = parse_date(self.store.field("invoices", invoice, "invoice_date"))
        if vendor is None or currency is None or reference is None or invoice_date is None or currency_quantum(currency) is None:
            return self._trace(1, INSUFFICIENT, f"Invoice {invoice_id} lacks a valid vendor, currency, reference, or date.", evidence, subject_ids=[invoice_id])
        candidates: list[tuple[str, dict[str, str], str, Decimal, int]] = []
        for other in self.store.rows("invoices"):
            other_id = trim_id(self.store.field("invoices", other, "invoice_id"))
            if other_id is None or other_id == invoice_id:
                continue
            other_status = norm_status(self.store.field("invoices", other, "status"))
            other_total = parse_decimal(self.store.field("invoices", other, "invoice_total"))
            if other_status in {"CANCELED", "CREDIT_APPLIED"} or other_total is None or other_total <= 0:
                continue
            if trim_id(self.store.field("invoices", other, "vendor_id")) != vendor:
                continue
            other_currency = norm_text(self.store.field("invoices", other, "currency"))
            if other_currency != currency or within_money(total, other_total, currency) is not True:
                continue
            other_date = parse_date(self.store.field("invoices", other, "invoice_date"))
            other_reference = norm_reference(self.store.field("invoices", other, "invoice_number"))
            if other_date is None or other_reference is None:
                continue
            day_difference = abs((invoice_date - other_date).days)
            similarity = edit_sim(reference, other_reference)
            if day_difference <= self.f01.duplicate_date_window_days and (
                reference == other_reference
                or (similarity is not None and similarity >= self.f01.duplicate_reference_similarity)
            ):
                candidates.append((other_id, other, other_reference, similarity or Decimal(0), day_difference))
        if not candidates:
            return self._trace(1, MATCH, f"Invoice {invoice_id} has no qualifying active duplicate in the complete invoice snapshot.", evidence, subject_ids=[invoice_id])
        other_id, other, other_reference, similarity, day_difference = sorted(candidates, key=lambda value: value[0])[0]
        pair = sorted((invoice_id, other_id))
        return self._trace(
            1,
            ANOMALY,
            f"Invoice {pair[0]} and invoice {pair[1]} share vendor {vendor}, normalized references {reference} and {other_reference}, currency {currency}, totals {total} and {parse_decimal(self.store.field('invoices', other, 'invoice_total'))}, and date difference {day_difference} days (similarity {similarity}).",
            evidence + [("invoices", other)],
            required=["invoices"],
            subject_ids=[invoice_id],
        )

    def _f02(self, invoice_id: str) -> RuleTrace:
        unavailable = self._unavailable(2, invoice_id, ("invoices", "invoice_lines", "purchase_orders", "po_lines"))
        if unavailable:
            return unavailable
        invoice = self.store.row("invoices", invoice_id)
        if invoice is None:
            return self._trace(2, INSUFFICIENT, f"Invoice {invoice_id} is missing.", subject_ids=[invoice_id])
        evidence = [("invoices", invoice)]
        normalized_status = norm_status(self.store.field("invoices", invoice, "status"))
        invoice_total = parse_decimal(self.store.field("invoices", invoice, "invoice_total"))
        if normalized_status is None or invoice_total is None:
            return self._trace(2, INSUFFICIENT, f"Invoice {invoice_id} lacks status or total required for F02 scope.", evidence, subject_ids=[invoice_id])
        if normalized_status in {"CANCELED", "CREDIT_APPLIED"} or invoice_total <= 0:
            return self._trace(2, MATCH, f"Invoice {invoice_id} is excluded from active positive F02 scope.", evidence, subject_ids=[invoice_id])
        po_id = trim_id(self.store.field("invoices", invoice, "po_id"))
        if po_id is None:
            return self._trace(2, MATCH, f"Invoice {invoice_id} is non-PO and F02 is not applicable.", evidence, subject_ids=[invoice_id])
        po = self.store.row("purchase_orders", po_id)
        if po is None:
            return self._trace(2, INSUFFICIENT, f"Invoice {invoice_id} references missing purchase order {po_id}.", evidence, subject_ids=[invoice_id])
        evidence.append(("purchase_orders", po))
        currency = norm_text(self.store.field("invoices", invoice, "currency"))
        po_currency = norm_text(self.store.field("purchase_orders", po, "currency"))
        if currency is None or po_currency is None or currency_quantum(currency) is None or currency != po_currency:
            return self._trace(2, INSUFFICIENT, f"Invoice {invoice_id} and PO {po_id} have missing, unknown, or unequal currencies.", evidence, subject_ids=[invoice_id])
        invoice_tax = parse_decimal(self.store.field("invoices", invoice, "tax"))
        invoice_shipping = parse_decimal(self.store.field("invoices", invoice, "shipping"))
        po_tax = parse_decimal(self.store.field("purchase_orders", po, "tax"))
        po_shipping = parse_decimal(self.store.field("purchase_orders", po, "shipping"))
        if None in (invoice_tax, invoice_shipping, po_tax, po_shipping):
            return self._trace(2, INSUFFICIENT, f"Invoice {invoice_id} or PO {po_id} lacks required tax/shipping money.", evidence, subject_ids=[invoice_id])
        invoice_lines = self.store.invoice_lines_by_invoice.get(invoice_id, [])
        if not invoice_lines:
            return self._trace(2, INSUFFICIENT, f"Invoice {invoice_id} has no invoice lines.", evidence, subject_ids=[invoice_id])
        line_pairs: list[tuple[dict[str, str], dict[str, str]]] = []
        line_anomalies: list[tuple[dict[str, str], dict[str, str], Decimal, Decimal, Decimal, Decimal]] = []
        for line in invoice_lines:
            line_id = trim_id(self.store.field("invoice_lines", line, "invoice_line_id")) or "<NULL>"
            po_line_id = trim_id(self.store.field("invoice_lines", line, "po_line_id"))
            if po_line_id is None:
                return self._trace(2, INSUFFICIENT, f"PO-backed invoice line {line_id} has no PO-line reference.", evidence + [("invoice_lines", line)], subject_ids=[invoice_id])
            po_line = self.store.row("po_lines", po_line_id)
            if po_line is None or trim_id(self.store.field("po_lines", po_line, "po_id")) != po_id:
                return self._trace(2, INSUFFICIENT, f"Invoice line {line_id} has a missing or wrong-PO target {po_line_id}.", evidence + [("invoice_lines", line)], subject_ids=[invoice_id])
            quantity = parse_integer(self.store.field("invoice_lines", line, "quantity"))
            line_unit = parse_decimal(self.store.field("invoice_lines", line, "unit_price"))
            line_amount = parse_decimal(self.store.field("invoice_lines", line, "line_amount"))
            po_quantity = parse_integer(self.store.field("po_lines", po_line, "quantity"))
            po_unit = parse_decimal(self.store.field("po_lines", po_line, "unit_price"))
            po_line_amount = parse_decimal(self.store.field("po_lines", po_line, "line_amount"))
            if None in (quantity, line_unit, line_amount, po_quantity, po_unit, po_line_amount):
                return self._trace(2, INSUFFICIENT, f"Invoice line {line_id} or PO line {po_line_id} has invalid quantity or money.", evidence + [("invoice_lines", line), ("po_lines", po_line)], subject_ids=[invoice_id])
            authorized_amount = Decimal(quantity) * po_unit
            quantum = currency_quantum(currency) or Decimal(0)
            unit_tolerance = max(quantum, abs(po_unit) * self.po_tolerance_percent / Decimal(100))
            amount_tolerance = max(quantum, abs(authorized_amount) * self.po_tolerance_percent / Decimal(100))
            unit_delta = abs(line_unit - po_unit)
            amount_delta = abs(line_amount - authorized_amount)
            line_pairs.append((line, po_line))
            if unit_delta > unit_tolerance or amount_delta > amount_tolerance:
                line_anomalies.append((line, po_line, unit_delta, unit_tolerance, amount_delta, amount_tolerance))
        if line_anomalies:
            line, po_line, unit_delta, unit_tol, amount_delta, amount_tol = line_anomalies[0]
            line_id = trim_id(self.store.field("invoice_lines", line, "invoice_line_id"))
            po_line_id = trim_id(self.store.field("po_lines", po_line, "po_line_id"))
            return self._trace(2, ANOMALY,
                f"Invoice {invoice_id} line {line_id} versus PO line {po_line_id}: unit delta {unit_delta} (tolerance {unit_tol}), extended delta {amount_delta} (tolerance {amount_tol}).",
                evidence + [("invoice_lines", line), ("po_lines", po_line)], required=["invoices", "purchase_orders", "invoice_lines", "po_lines"], subject_ids=[invoice_id])
        po_lines = self.store.po_lines_by_po.get(po_id, [])
        po_ids = [trim_id(self.store.field("po_lines", row, "po_line_id")) for row in po_lines]
        invoice_po_ids = [trim_id(self.store.field("invoice_lines", row, "po_line_id")) for row in invoice_lines]
        quantity_equal = all(
            parse_integer(self.store.field("invoice_lines", line, "quantity")) == parse_integer(self.store.field("po_lines", po_line, "quantity"))
            for line, po_line in line_pairs
        )
        full_coverage = bool(po_lines) and len(invoice_po_ids) == len(set(invoice_po_ids)) and set(invoice_po_ids) == set(po_ids) and quantity_equal
        if full_coverage:
            quantum = currency_quantum(currency) or Decimal(0)
            tax_tolerance = max(quantum, abs(po_tax) * self.po_tolerance_percent / Decimal(100))
            shipping_tolerance = max(quantum, abs(po_shipping) * self.po_tolerance_percent / Decimal(100))
            tax_delta = abs(invoice_tax - po_tax)
            shipping_delta = abs(invoice_shipping - po_shipping)
            if tax_delta > tax_tolerance or shipping_delta > shipping_tolerance:
                all_evidence = evidence + [("invoice_lines", line) for line in invoice_lines] + [("po_lines", line) for line in po_lines]
                return self._trace(2, ANOMALY,
                    f"Fully covered invoice {invoice_id} versus PO {po_id}: tax delta {tax_delta} (tolerance {tax_tolerance}), shipping delta {shipping_delta} (tolerance {shipping_tolerance}).",
                    all_evidence, required=["invoices", "purchase_orders", "invoice_lines", "po_lines"], subject_ids=[invoice_id])
        return self._trace(2, MATCH, f"Invoice {invoice_id} is within the frozen PO line and eligible header tolerances.", evidence, subject_ids=[invoice_id])

    def _f03(self, invoice_id: str) -> RuleTrace:
        unavailable = self._unavailable(3, invoice_id, ("invoices", "invoice_lines", "po_lines"))
        if unavailable:
            return unavailable
        invoice = self.store.row("invoices", invoice_id)
        if invoice is None:
            return self._trace(3, INSUFFICIENT, f"Invoice {invoice_id} is missing.", subject_ids=[invoice_id])
        evidence = [("invoices", invoice)]
        status = norm_status(self.store.field("invoices", invoice, "status"))
        if status is None:
            return self._trace(3, INSUFFICIENT, f"Invoice {invoice_id} has no valid status.", evidence, subject_ids=[invoice_id])
        if status in {"CANCELED", "CREDIT_APPLIED"}:
            return self._trace(3, MATCH, f"Invoice {invoice_id} is canceled or credited and excluded from F03.", evidence, subject_ids=[invoice_id])
        lines = self.store.invoice_lines_by_invoice.get(invoice_id, [])
        if not lines:
            return self._trace(3, INSUFFICIENT, f"Invoice {invoice_id} has no invoice lines.", evidence, subject_ids=[invoice_id])
        compared = 0
        for line in lines:
            po_line_id = trim_id(self.store.field("invoice_lines", line, "po_line_id"))
            if po_line_id is None:
                continue
            compared += 1
            po_line = self.store.row("po_lines", po_line_id)
            line_id = trim_id(self.store.field("invoice_lines", line, "invoice_line_id")) or "<NULL>"
            if po_line is None:
                return self._trace(3, INSUFFICIENT, f"Invoice line {line_id} references missing PO line {po_line_id}.", evidence + [("invoice_lines", line)], subject_ids=[invoice_id])
            invoice_quantity = parse_integer(self.store.field("invoice_lines", line, "quantity"))
            po_quantity = parse_integer(self.store.field("po_lines", po_line, "quantity"))
            if invoice_quantity is None or po_quantity is None:
                return self._trace(3, INSUFFICIENT, f"Invoice line {line_id} or PO line {po_line_id} has a NULL/nonintegral quantity.", evidence + [("invoice_lines", line), ("po_lines", po_line)], subject_ids=[invoice_id])
            if invoice_quantity != po_quantity:
                return self._trace(3, ANOMALY,
                    f"Invoice {invoice_id} line {line_id} quantity {invoice_quantity} differs from PO line {po_line_id} quantity {po_quantity}.",
                    evidence + [("invoice_lines", line), ("po_lines", po_line)], required=["invoices", "invoice_lines", "po_lines"], subject_ids=[invoice_id])
        return self._trace(3, MATCH, f"Invoice {invoice_id} has {compared} linked line(s) with equal quantities; non-PO lines are not applicable.", evidence, subject_ids=[invoice_id])

    def _f04(self, invoice_id: str) -> RuleTrace:
        unavailable = self._unavailable(4, invoice_id, ("invoices", "purchase_orders"))
        if unavailable:
            return unavailable
        invoice = self.store.row("invoices", invoice_id)
        if invoice is None:
            return self._trace(4, INSUFFICIENT, f"Invoice {invoice_id} is missing.", subject_ids=[invoice_id])
        evidence = [("invoices", invoice)]
        status = norm_status(self.store.field("invoices", invoice, "status"))
        if status is None:
            return self._trace(4, INSUFFICIENT, f"Invoice {invoice_id} has no status.", evidence, subject_ids=[invoice_id])
        if status in {"CANCELED", "CREDIT_APPLIED"}:
            return self._trace(4, MATCH, f"Invoice {invoice_id} is canceled or credited and excluded from F04.", evidence, subject_ids=[invoice_id])
        po_id = trim_id(self.store.field("invoices", invoice, "po_id"))
        if po_id is None:
            return self._trace(4, MATCH, f"Invoice {invoice_id} is non-PO and F04 is not applicable.", evidence, subject_ids=[invoice_id])
        po = self.store.row("purchase_orders", po_id)
        if po is None:
            return self._trace(4, INSUFFICIENT, f"Invoice {invoice_id} references missing PO {po_id}.", evidence, subject_ids=[invoice_id])
        invoice_vendor = trim_id(self.store.field("invoices", invoice, "vendor_id"))
        po_vendor = trim_id(self.store.field("purchase_orders", po, "vendor_id"))
        if invoice_vendor is None or po_vendor is None:
            return self._trace(4, INSUFFICIENT, f"Invoice {invoice_id} or PO {po_id} has no vendor ID.", evidence + [("purchase_orders", po)], subject_ids=[invoice_id])
        if invoice_vendor != po_vendor:
            return self._trace(4, ANOMALY,
                f"Invoice vendor_id {invoice_vendor} differs from purchase order vendor_id {po_vendor}.",
                evidence + [("purchase_orders", po)], required=["invoices", "purchase_orders"], subject_ids=[invoice_id])
        return self._trace(4, MATCH, f"Invoice {invoice_id} and PO {po_id} share vendor_id {invoice_vendor}.", evidence + [("purchase_orders", po)], subject_ids=[invoice_id])

    def _effective_payment(self, payment: dict[str, str]) -> bool | None:
        status = norm_status(self.store.field("payments", payment, "payment_status"))
        settlement = norm_status(self.store.field("payments", payment, "settlement_status"))
        if status is None or settlement is None:
            return None
        return status == "COMPLETED" and settlement == "SETTLED"

    def _f05(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(5, payment_id, ("payments", "payment_allocations", "invoices"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(5, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        evidence = [("payments", payment)]
        effective = self._effective_payment(payment)
        amount = parse_decimal(self.store.field("payments", payment, "payment_amount"))
        if effective is None or amount is None:
            return self._trace(5, INSUFFICIENT, f"Payment {payment_id} lacks valid statuses or amount.", evidence, subject_ids=[payment_id])
        if not effective or amount <= 0:
            return self._trace(5, MATCH, f"Payment {payment_id} is reversed/non-effective or nonpositive and excluded from F05.", evidence, subject_ids=[payment_id])
        valid_count = 0
        invalid: list[dict[str, str]] = []
        for allocation in self.store.allocations_by_payment.get(payment_id, []):
            allocated = parse_decimal(self.store.field("payment_allocations", allocation, "allocated_amount"))
            invoice_id = trim_id(self.store.field("payment_allocations", allocation, "invoice_id"))
            allocation_date = parse_date(self.store.field("payment_allocations", allocation, "allocation_date"))
            if allocated is None or allocation_date is None:
                return self._trace(5, INSUFFICIENT, f"Payment {payment_id} has an allocation with invalid amount/date.", evidence + [("payment_allocations", allocation)], subject_ids=[payment_id])
            invoice = self.store.row("invoices", invoice_id)
            if invoice_id is not None and invoice is None:
                invalid.append(allocation)
            elif allocated > 0 and invoice is not None:
                valid_count += 1
        if valid_count == 0 or invalid:
            return self._trace(5, ANOMALY,
                f"Effective payment {payment_id} has {valid_count} positive valid allocation(s) and {len(invalid)} allocation(s) referencing missing invoices.",
                evidence + [("payment_allocations", row) for row in invalid], required=["payments"], absence_tables=["payment_allocations", "invoices"], subject_ids=[payment_id])
        return self._trace(5, MATCH, f"Payment {payment_id} has {valid_count} positive allocation(s), all referencing existing invoices.", evidence, subject_ids=[payment_id])

    def _net_paid(self, invoice_id: str, currency: str) -> tuple[Decimal | None, list[tuple[str, dict[str, str]]], str | None]:
        total = Decimal(0)
        evidence: list[tuple[str, dict[str, str]]] = []
        for allocation in self.store.allocations_by_invoice.get(invoice_id, []):
            payment_id = trim_id(self.store.field("payment_allocations", allocation, "payment_id"))
            payment = self.store.row("payments", payment_id)
            if payment is None:
                return None, evidence + [("payment_allocations", allocation)], f"allocation references missing payment {payment_id}"
            effective = self._effective_payment(payment)
            if effective is None:
                return None, evidence + [("payment_allocations", allocation), ("payments", payment)], f"payment {payment_id} has missing status"
            if not effective:
                continue
            payment_currency = norm_text(self.store.field("payments", payment, "payment_currency"))
            if payment_currency is None or payment_currency != currency:
                return None, evidence + [("payment_allocations", allocation), ("payments", payment)], f"effective payment {payment_id} currency differs from invoice"
            allocated = parse_decimal(self.store.field("payment_allocations", allocation, "allocated_amount"))
            allocation_date = parse_date(self.store.field("payment_allocations", allocation, "allocation_date"))
            if allocated is None or allocation_date is None:
                return None, evidence + [("payment_allocations", allocation), ("payments", payment)], f"allocation for payment {payment_id} has invalid amount/date"
            total += allocated
            evidence.extend((("payment_allocations", allocation), ("payments", payment)))
        return total, evidence, None

    def _f06(self, invoice_id: str) -> RuleTrace:
        unavailable = self._unavailable(6, invoice_id, ("invoices", "payment_allocations", "payments"))
        if unavailable:
            return unavailable
        invoice = self.store.row("invoices", invoice_id)
        if invoice is None:
            return self._trace(6, INSUFFICIENT, f"Invoice {invoice_id} is missing.", subject_ids=[invoice_id])
        base = [("invoices", invoice)]
        status = norm_status(self.store.field("invoices", invoice, "status"))
        currency = norm_text(self.store.field("invoices", invoice, "currency"))
        invoice_total = parse_decimal(self.store.field("invoices", invoice, "invoice_total"))
        if status is None or currency is None or invoice_total is None or currency_quantum(currency) is None:
            return self._trace(6, INSUFFICIENT, f"Invoice {invoice_id} lacks valid status, currency, or total.", base, subject_ids=[invoice_id])
        if status in {"CANCELED", "CREDIT_APPLIED"} or invoice_total <= 0:
            return self._trace(6, MATCH, f"Invoice {invoice_id} is canceled, credited, or nonpositive and excluded from F06.", base, subject_ids=[invoice_id])
        net_paid, paid_evidence, issue = self._net_paid(invoice_id, currency)
        if issue or net_paid is None:
            return self._trace(6, INSUFFICIENT, f"Invoice {invoice_id} net-paid aggregate is unavailable: {issue}.", base + paid_evidence, subject_ids=[invoice_id])
        excess = net_paid - invoice_total
        if excess > (currency_quantum(currency) or Decimal(0)):
            return self._trace(6, ANOMALY,
                f"Invoice {invoice_id} total {invoice_total} {currency} has effective net paid {net_paid}, excess {excess}.",
                base + paid_evidence, required=["invoices", "payment_allocations", "payments"], subject_ids=[invoice_id])
        return self._trace(6, MATCH, f"Invoice {invoice_id} total {invoice_total} has effective net paid {net_paid}, not above the frozen overpayment tolerance.", base + paid_evidence, subject_ids=[invoice_id])

    def _f07(self, invoice_id: str) -> RuleTrace:
        unavailable = self._unavailable(7, invoice_id, ("invoices", "payment_allocations", "payments"))
        if unavailable:
            return unavailable
        invoice = self.store.row("invoices", invoice_id)
        if invoice is None:
            return self._trace(7, INSUFFICIENT, f"Invoice {invoice_id} is missing.", subject_ids=[invoice_id])
        base = [("invoices", invoice)]
        status = norm_status(self.store.field("invoices", invoice, "status"))
        currency = norm_text(self.store.field("invoices", invoice, "currency"))
        invoice_total = parse_decimal(self.store.field("invoices", invoice, "invoice_total"))
        if status is None or currency is None or invoice_total is None or currency_quantum(currency) is None:
            return self._trace(7, INSUFFICIENT, f"Invoice {invoice_id} lacks valid status, currency, or total.", base, subject_ids=[invoice_id])
        net_paid, paid_evidence, issue = self._net_paid(invoice_id, currency)
        if issue or net_paid is None:
            return self._trace(7, INSUFFICIENT, f"Invoice {invoice_id} net-paid aggregate is unavailable: {issue}.", base + paid_evidence, subject_ids=[invoice_id])
        if status == "PAID" and net_paid == 0:
            return self._trace(7, INSUFFICIENT, f"Invoice {invoice_id} is marked PAID but has zero effective allocations; F07 requires a positive partial payment.", base, subject_ids=[invoice_id])
        residual = invoice_total - net_paid
        if status == "PAID" and net_paid > 0 and residual > (currency_quantum(currency) or Decimal(0)):
            return self._trace(7, ANOMALY,
                f"Invoice {invoice_id} status PAID has total {invoice_total} {currency}, effective net paid {net_paid}, and residual {residual}.",
                base + paid_evidence, required=["invoices", "payment_allocations", "payments"], subject_ids=[invoice_id])
        return self._trace(7, MATCH, f"Invoice {invoice_id} status {status} with total {invoice_total} and net paid {net_paid} does not meet F07.", base + paid_evidence, subject_ids=[invoice_id])

    @staticmethod
    def _required_roles(amount: Decimal) -> list[str]:
        if amount <= Decimal("500"):
            return ["AUTO"]
        if amount <= Decimal("10000"):
            return ["MANAGER"]
        if amount <= Decimal("50000"):
            return ["MANAGER", "DIRECTOR"]
        if amount <= Decimal("250000"):
            return ["MANAGER", "DIRECTOR", "CONTROLLER"]
        return ["MANAGER", "DIRECTOR", "TREASURY"]

    def _f08(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(8, payment_id, ("payments", "payment_allocations", "invoices", "approval_events", "employees"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(8, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        base = [("payments", payment)]
        payment_status = norm_status(self.store.field("payments", payment, "payment_status"))
        payment_time = parse_ts(self.store.field("payments", payment, "created_at"))
        if payment_status is None or payment_time is None:
            return self._trace(8, INSUFFICIENT, f"Payment {payment_id} lacks valid status or creation timestamp.", base, subject_ids=[payment_id])
        if payment_status not in {"COMPLETED", "SUBMITTED"}:
            return self._trace(8, MATCH, f"Payment {payment_id} status {payment_status} is outside released-payment F08 scope.", base, subject_ids=[payment_id])
        allocations = self.store.allocations_by_payment.get(payment_id, [])
        if not allocations:
            return self._trace(8, INSUFFICIENT, f"Payment {payment_id} has no allocation through which approval can be evaluated.", base, subject_ids=[payment_id])
        for allocation in allocations:
            invoice_id = trim_id(self.store.field("payment_allocations", allocation, "invoice_id"))
            allocation_date = parse_date(self.store.field("payment_allocations", allocation, "allocation_date"))
            invoice = self.store.row("invoices", invoice_id)
            chain = base + [("payment_allocations", allocation)]
            if invoice is None or allocation_date is None:
                return self._trace(8, INSUFFICIENT, f"Payment {payment_id} has a missing invoice or invalid allocation date for {invoice_id}.", chain, subject_ids=[payment_id])
            chain.append(("invoices", invoice))
            amount = parse_decimal(self.store.field("invoices", invoice, "invoice_total"))
            currency = norm_text(self.store.field("invoices", invoice, "currency"))
            if amount is None or currency_quantum(currency) is None:
                return self._trace(8, INSUFFICIENT, f"Invoice {invoice_id} lacks valid nominal amount/currency for approval policy.", chain, subject_ids=[payment_id])
            required_roles = self._required_roles(amount)
            all_events = self.store.approvals_by_invoice.get(invoice_id or "", [])
            parsed_events: list[tuple[object, int, str, dict[str, str]]] = []
            for event in all_events:
                event_time = parse_ts(self.store.field("approval_events", event, "event_timestamp"))
                level = parse_integer(self.store.field("approval_events", event, "approval_level"))
                event_id = trim_id(self.store.field("approval_events", event, "approval_event_id")) or ""
                if event_time is None or level is None:
                    return self._trace(8, INSUFFICIENT, f"Invoice {invoice_id} has an approval event with invalid timestamp/level.", chain + [("approval_events", event)], subject_ids=[payment_id])
                parsed_events.append((event_time, level, event_id, event))
            parsed_events.sort(key=lambda item: (item[0], item[1], item[2]))
            effective_events = [
                item for item in parsed_events
                if norm_status(self.store.field("approval_events", item[3], "action")) in {"APPROVED", "AUTO_APPROVED"}
                and item[0] <= payment_time
            ]
            observed = [norm_status(self.store.field("approval_events", item[3], "approver_role")) for item in effective_events]
            relied: list[tuple[object, int, str, dict[str, str]]] = []
            cursor = -1
            last_level = -10**9
            for role in required_roles:
                found = None
                for index in range(cursor + 1, len(effective_events)):
                    item = effective_events[index]
                    item_role = norm_status(self.store.field("approval_events", item[3], "approver_role"))
                    if item_role == role and item[1] > last_level:
                        found = (index, item)
                        break
                if found is None:
                    return self._trace(8, ANOMALY,
                        f"Payment {payment_id} released invoice {invoice_id} requiring roles {required_roles}; observed pre-release roles/levels are {[(observed[i], effective_events[i][1]) for i in range(len(effective_events))]} and required role {role} is missing or out of order.",
                        chain + [("approval_events", item[3]) for item in parsed_events], required=["payments", "payment_allocations", "invoices"], absence_tables=["approval_events"], subject_ids=[payment_id])
                cursor, item = found
                relied.append(item)
                last_level = item[1]
            employee_evidence: list[tuple[str, dict[str, str]]] = []
            for event_time, level, event_id, event in relied:
                role = norm_status(self.store.field("approval_events", event, "approver_role"))
                actor = trim_id(self.store.field("approval_events", event, "approver_id"))
                action = norm_status(self.store.field("approval_events", event, "action"))
                if role == "AUTO":
                    valid_auto = amount <= Decimal("500") and action == "AUTO_APPROVED" and actor == "SYSTEM-AUTO-APPROVAL"
                    if not valid_auto:
                        return self._trace(8, ANOMALY,
                            f"Invoice {invoice_id} has invalid AUTO approval actor/action {actor}/{action} for nominal total {amount}.",
                            chain + [("approval_events", event)], required=["payments", "payment_allocations", "invoices", "approval_events"], subject_ids=[payment_id])
                    continue
                employee = self.store.row("employees", actor)
                if employee is None:
                    return self._trace(8, ANOMALY,
                        f"Invoice {invoice_id} approval event {event_id} claims human actor {actor}, but no employee record exists.",
                        chain + [("approval_events", event)], required=["payments", "payment_allocations", "invoices", "approval_events"], absence_tables=["employees"], subject_ids=[payment_id])
                employee_evidence.append(("employees", employee))
                employee_role = norm_status(self.store.field("employees", employee, "role"))
                active = norm_status(self.store.field("employees", employee, "active_status"))
                limit = parse_decimal(self.store.field("employees", employee, "approval_limit"))
                if employee_role != role or active != "ACTIVE" or limit is None:
                    return self._trace(8, ANOMALY,
                        f"Invoice {invoice_id} approval event {event_id} actor {actor} is unauthorized: event role {role}, employee role {employee_role}, status {active}, limit {limit}.",
                        chain + [("approval_events", event), ("employees", employee)], required=["payments", "payment_allocations", "invoices", "approval_events", "employees"], subject_ids=[payment_id])
            final_event = relied[-1]
            final_role = norm_status(self.store.field("approval_events", final_event[3], "approver_role"))
            if final_role != "AUTO":
                final_actor = trim_id(self.store.field("approval_events", final_event[3], "approver_id"))
                final_employee = self.store.row("employees", final_actor)
                final_limit = parse_decimal(self.store.field("employees", final_employee, "approval_limit")) if final_employee else None
                if final_limit is None or final_limit < amount:
                    return self._trace(8, ANOMALY,
                        f"Invoice {invoice_id} final approver {final_actor} limit {final_limit} is below invoice total {amount}.",
                        chain + [("approval_events", item[3]) for item in relied] + employee_evidence,
                        required=["payments", "payment_allocations", "invoices", "approval_events", "employees"], subject_ids=[payment_id])
        return self._trace(8, MATCH, f"Payment {payment_id} completed the frozen approval ladder before release for every allocated invoice.", base, subject_ids=[payment_id])

    def _payment_gl_rows(self, payment_id: str) -> list[dict[str, str]]:
        return [
            row for row in self.store.gl_by_source.get(payment_id, [])
            if norm_status(self.store.field("gl_entries", row, "transaction_type")) == "PAYMENT"
        ]

    def _f09(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(9, payment_id, ("payments", "gl_entries"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(9, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        base = [("payments", payment)]
        effective = self._effective_payment(payment)
        payment_date = parse_date(self.store.field("payments", payment, "payment_date"))
        amount = parse_decimal(self.store.field("payments", payment, "payment_amount"))
        currency = norm_text(self.store.field("payments", payment, "payment_currency"))
        if effective is None or payment_date is None or amount is None or currency_quantum(currency) is None:
            return self._trace(9, INSUFFICIENT, f"Payment {payment_id} lacks valid status, date, currency, or amount.", base, subject_ids=[payment_id])
        if not effective:
            return self._trace(9, MATCH, f"Payment {payment_id} is not an effective completed/settled payment.", base, subject_ids=[payment_id])
        age = business_days_between(payment_date, self.as_of_date)
        if age is None:
            return self._trace(9, INSUFFICIENT, f"Payment {payment_id} date {payment_date} is after the observation cutoff.", base, subject_ids=[payment_id])
        rows = self._payment_gl_rows(payment_id)
        if not rows:
            return self._trace(9, ANOMALY,
                f"Effective payment {payment_id} amount {amount} {currency} has zero source-linked PAYMENT GL rows in a complete snapshot after posting lag 0.",
                base, required=["payments"], absence_tables=["gl_entries"], subject_ids=[payment_id])
        total_debit = Decimal(0)
        total_credit = Decimal(0)
        ap_debit = Decimal(0)
        cash_credit = Decimal(0)
        currency_errors = 0
        for row in rows:
            debit = parse_decimal(self.store.field("gl_entries", row, "debit"))
            credit = parse_decimal(self.store.field("gl_entries", row, "credit"))
            row_currency = norm_text(self.store.field("gl_entries", row, "currency"))
            posting_date = parse_date(self.store.field("gl_entries", row, "posting_date"))
            account = norm_text(self.store.field("gl_entries", row, "gl_account"))
            if debit is None or credit is None or posting_date is None or account is None or row_currency is None:
                return self._trace(9, INSUFFICIENT, f"Payment {payment_id} has a source-linked GL line with invalid amount/date/account/currency.", base + [("gl_entries", row)], subject_ids=[payment_id])
            total_debit += debit
            total_credit += credit
            if row_currency != currency:
                currency_errors += 1
            if account == "200000-ACCOUNTS-PAYABLE":
                ap_debit += debit
            if account == "100000-CASH":
                cash_credit += credit
        balanced = within_money(total_debit, total_credit, currency)
        ap_matches = within_money(ap_debit, amount, currency)
        cash_matches = within_money(cash_credit, amount, currency)
        all_evidence = base + [("gl_entries", row) for row in rows]
        if currency_errors or balanced is not True or ap_matches is not True or cash_matches is not True:
            return self._trace(9, ANOMALY,
                f"Payment {payment_id} {amount} {currency}: GL lines {len(rows)}, debit {total_debit}, credit {total_credit}, AP debit {ap_debit}, cash credit {cash_credit}, currency errors {currency_errors}.",
                all_evidence, required=["payments", "gl_entries"], subject_ids=[payment_id])
        return self._trace(9, MATCH,
            f"Payment {payment_id} {amount} {currency} has a balanced {len(rows)}-line journal with matching AP debit and cash credit.",
            all_evidence, subject_ids=[payment_id])

    def _f10(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(10, payment_id, ("payments", "gl_entries"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(10, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        base = [("payments", payment)]
        payment_date = parse_date(self.store.field("payments", payment, "payment_date"))
        if payment_date is None:
            return self._trace(10, INSUFFICIENT, f"Payment {payment_id} has an invalid payment date.", base, subject_ids=[payment_id])
        rows = self._payment_gl_rows(payment_id)
        if not rows:
            return self._trace(10, INSUFFICIENT, f"Payment {payment_id} has no source-linked PAYMENT journal; missing posting is evaluated by F09.", base, subject_ids=[payment_id])
        expected = payment_date.strftime("%Y-%m")
        observed: list[tuple[str, str, str]] = []
        mismatch = False
        for row in rows:
            posting_date = parse_date(self.store.field("gl_entries", row, "posting_date"))
            period = valid_accounting_period(self.store.field("gl_entries", row, "accounting_period"))
            line_id = trim_id(self.store.field("gl_entries", row, "journal_line_id")) or "<NULL>"
            if posting_date is None or period is None:
                return self._trace(10, INSUFFICIENT, f"Payment {payment_id} journal line {line_id} has invalid posting date/accounting period.", base + [("gl_entries", row)], subject_ids=[payment_id])
            observed.append((line_id, posting_date.isoformat(), period))
            if period != expected or posting_date.strftime("%Y-%m") != period:
                mismatch = True
        evidence = base + [("gl_entries", row) for row in rows]
        if mismatch:
            return self._trace(10, ANOMALY,
                f"Payment {payment_id} date {payment_date} requires period {expected}; observed journal line posting dates/periods {observed}.",
                evidence, required=["payments", "gl_entries"], subject_ids=[payment_id])
        return self._trace(10, MATCH, f"Payment {payment_id} date {payment_date} and all {len(rows)} GL lines use accounting period {expected}.", evidence, subject_ids=[payment_id])

    def _f11(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(11, payment_id, ("payments", "vendors", "vendor_change_log", "bank_transactions"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(11, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        base = [("payments", payment)]
        vendor_id = trim_id(self.store.field("payments", payment, "vendor_id"))
        payment_token = trim_id(self.store.field("payments", payment, "bank_account_id"))
        payment_time = parse_ts(self.store.field("payments", payment, "created_at"))
        reference = norm_reference(self.store.field("payments", payment, "reference_number"))
        settlement = norm_status(self.store.field("payments", payment, "settlement_status"))
        if None in (vendor_id, payment_token, payment_time, reference, settlement):
            return self._trace(11, INSUFFICIENT, f"Payment {payment_id} lacks vendor/token/time/reference/settlement evidence.", base, subject_ids=[payment_id])
        vendor = self.store.row("vendors", vendor_id)
        if vendor is None:
            return self._trace(11, INSUFFICIENT, f"Payment {payment_id} references missing vendor {vendor_id}.", base, subject_ids=[payment_id])
        base.append(("vendors", vendor))
        current_token = trim_id(self.store.field("vendors", vendor, "bank_account_token"))
        if current_token is None:
            return self._trace(11, INSUFFICIENT, f"Vendor {vendor_id} has no current bank token.", base, subject_ids=[payment_id])
        changes: list[tuple[object, dict[str, str]]] = []
        for row in self.store.changes_by_vendor.get(vendor_id or "", []):
            if norm_status(self.store.field("vendor_change_log", row, "field_changed")) != "BANK_ACCOUNT_TOKEN":
                continue
            changed_at = parse_ts(self.store.field("vendor_change_log", row, "changed_at"))
            if changed_at is None:
                return self._trace(11, INSUFFICIENT, f"Vendor {vendor_id} bank-token history has an invalid timestamp.", base + [("vendor_change_log", row)], subject_ids=[payment_id])
            changes.append((changed_at, row))
        changes.sort(key=lambda value: (value[0], trim_id(self.store.field("vendor_change_log", value[1], "change_id")) or ""))
        before = [item for item in changes if item[0] <= payment_time]
        after = [item for item in changes if item[0] > payment_time]
        state_evidence: list[tuple[str, dict[str, str]]] = []
        if before:
            state_row = before[-1][1]
            effective_token = trim_id(self.store.field("vendor_change_log", state_row, "new_value"))
            state_evidence.append(("vendor_change_log", state_row))
        elif after:
            state_row = after[0][1]
            effective_token = trim_id(self.store.field("vendor_change_log", state_row, "old_value"))
            state_evidence.append(("vendor_change_log", state_row))
        else:
            effective_token = current_token
        if effective_token is None:
            return self._trace(11, INSUFFICIENT, f"Vendor {vendor_id} effective bank token at {payment_time.isoformat()} cannot be reconstructed.", base + state_evidence, subject_ids=[payment_id])
        if payment_token == effective_token:
            return self._trace(11, MATCH, f"Payment {payment_id} token {payment_token} equals vendor {vendor_id} effective token at {payment_time.isoformat()}.", base + state_evidence, subject_ids=[payment_id])
        decisive = [
            row for _, row in changes
            if trim_id(self.store.field("vendor_change_log", row, "old_value")) == payment_token
            and trim_id(self.store.field("vendor_change_log", row, "new_value")) == effective_token
        ]
        if not decisive:
            return self._trace(11, INSUFFICIENT,
                f"Payment {payment_id} token {payment_token} differs from effective token {effective_token}, but no decisive transition establishes that relationship.",
                base + state_evidence, subject_ids=[payment_id])
        banks = self.store.banks_by_reference.get(reference or "", [])
        if len(banks) != 1:
            return self._trace(11, INSUFFICIENT, f"Payment {payment_id} reference {reference} has {len(banks)} matched bank outcomes; exactly one is required.", base + [("vendor_change_log", row) for row in decisive], subject_ids=[payment_id])
        bank = banks[0]
        bank_status = norm_status(self.store.field("bank_transactions", bank, "status"))
        counterparty = trim_id(self.store.field("bank_transactions", bank, "counterparty_token"))
        posted_date = parse_date(self.store.field("bank_transactions", bank, "posted_date"))
        if bank_status is None or counterparty is None or posted_date is None:
            return self._trace(11, INSUFFICIENT, f"Payment {payment_id} matched bank outcome lacks token/status/date.", base + [("vendor_change_log", row) for row in decisive] + [("bank_transactions", bank)], subject_ids=[payment_id])
        all_evidence = base + [("vendor_change_log", row) for row in decisive] + [("bank_transactions", bank)]
        if counterparty == payment_token and (bank_status == "RETURNED" or settlement == "FAILED"):
            return self._trace(11, ANOMALY,
                f"Payment {payment_id} at {payment_time.isoformat()} used stale token {payment_token} instead of effective token {effective_token}; bank counterparty {counterparty}, bank status {bank_status}, settlement {settlement}.",
                all_evidence, required=["payments", "vendors", "vendor_change_log", "bank_transactions"], subject_ids=[payment_id])
        return self._trace(11, MATCH,
            f"Payment {payment_id} token differs from effective token, but bank token/status and settlement do not meet the frozen returned/failed conflict condition.",
            all_evidence, subject_ids=[payment_id])

    def _f12(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(12, payment_id, ("payments", "bank_transactions"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(12, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        base = [("payments", payment)]
        effective = self._effective_payment(payment)
        if effective is None:
            return self._trace(12, INSUFFICIENT, f"Payment {payment_id} lacks valid payment/settlement status.", base, subject_ids=[payment_id])
        if not effective:
            return self._trace(12, MATCH, f"Payment {payment_id} is pending/submitted/reversed and is not F12.", base, subject_ids=[payment_id])
        reference = norm_reference(self.store.field("payments", payment, "reference_number"))
        if reference is None:
            return self._trace(12, INSUFFICIENT, f"Payment {payment_id} has no normalized reference.", base, subject_ids=[payment_id])
        reference_use_count = len(self.store.payments_by_reference.get(reference, []))
        if reference_use_count != 1:
            return self._trace(12, INSUFFICIENT, f"Payment reference {reference} is used by {reference_use_count} payments; exactly one is required.", base, subject_ids=[payment_id])
        payment_date = parse_date(self.store.field("payments", payment, "payment_date"))
        method = norm_status(self.store.field("payments", payment, "payment_method"))
        if payment_date is None or method not in self.clearing_limits:
            return self._trace(12, INSUFFICIENT, f"Payment {payment_id} has invalid date or unsupported exact method {method}.", base, subject_ids=[payment_id])
        age = business_days_between(payment_date, self.as_of_date)
        if age is None:
            return self._trace(12, INSUFFICIENT, f"Payment {payment_id} date {payment_date} is after cutoff {self.as_of_date}.", base, subject_ids=[payment_id])
        evidence_rows: list[dict[str, str]] = []
        for bank in self.store.banks_by_reference.get(reference, []):
            transaction_type = norm_status(self.store.field("bank_transactions", bank, "transaction_type"))
            bank_status = norm_status(self.store.field("bank_transactions", bank, "status"))
            posted_date = parse_date(self.store.field("bank_transactions", bank, "posted_date"))
            if posted_date is None:
                return self._trace(12, INSUFFICIENT, f"Payment {payment_id} has a reference-matched bank row with invalid posted date.", base + [("bank_transactions", bank)], subject_ids=[payment_id])
            if transaction_type != "BANK_FEE" and bank_status in {"POSTED", "RETURNED"} and posted_date <= self.as_of_date:
                evidence_rows.append(bank)
        limit = self.clearing_limits[method]
        if not evidence_rows and age > limit:
            return self._trace(12, ANOMALY,
                f"Payment {payment_id} method {method}, date {payment_date}, cutoff {self.as_of_date}, business-day age {age}, limit {limit}, reference {reference}: zero qualifying bank records.",
                base, required=["payments"], absence_tables=["bank_transactions"], subject_ids=[payment_id])
        return self._trace(12, MATCH,
            f"Payment {payment_id} method {method} has business-day age {age} versus limit {limit} and {len(evidence_rows)} qualifying bank record(s).",
            base + [("bank_transactions", row) for row in evidence_rows], subject_ids=[payment_id])

    def _journal_groups(self, source_id: str, transaction_type: str) -> dict[str, list[dict[str, str]]]:
        groups: dict[str, list[dict[str, str]]] = {}
        for row in self.store.gl_by_source.get(source_id, []):
            if norm_status(self.store.field("gl_entries", row, "transaction_type")) != transaction_type:
                continue
            journal_id = trim_id(self.store.field("gl_entries", row, "journal_id")) or ""
            groups.setdefault(journal_id, []).append(row)
        return groups

    def _balanced_journals(self, source_id: str, transaction_type: str, currency: str) -> tuple[list[list[dict[str, str]]], str | None]:
        balanced: list[list[dict[str, str]]] = []
        for rows in self._journal_groups(source_id, transaction_type).values():
            debit = Decimal(0)
            credit = Decimal(0)
            for row in rows:
                row_debit = parse_decimal(self.store.field("gl_entries", row, "debit"))
                row_credit = parse_decimal(self.store.field("gl_entries", row, "credit"))
                row_currency = norm_text(self.store.field("gl_entries", row, "currency"))
                if row_debit is None or row_credit is None or row_currency is None:
                    return [], "linked journal contains invalid money/currency"
                if row_currency != currency:
                    return [], f"linked journal currency {row_currency} differs from {currency}"
                debit += row_debit
                credit += row_credit
            if within_money(debit, credit, currency) is True:
                balanced.append(rows)
        return balanced, None

    def _f13(self, bank_id: str) -> RuleTrace:
        unavailable = self._unavailable(13, bank_id, ("bank_transactions", "payments", "gl_entries"))
        if unavailable:
            return unavailable
        bank = self.store.row("bank_transactions", bank_id)
        if bank is None:
            return self._trace(13, INSUFFICIENT, f"Bank transaction {bank_id} is missing.", subject_ids=[bank_id])
        base = [("bank_transactions", bank)]
        direction = norm_status(self.store.field("bank_transactions", bank, "direction"))
        bank_status = norm_status(self.store.field("bank_transactions", bank, "status"))
        posted_date = parse_date(self.store.field("bank_transactions", bank, "posted_date"))
        transaction_type = norm_status(self.store.field("bank_transactions", bank, "transaction_type"))
        amount = parse_decimal(self.store.field("bank_transactions", bank, "amount"))
        currency = norm_text(self.store.field("bank_transactions", bank, "currency"))
        if None in (direction, bank_status, posted_date, transaction_type, amount) or currency_quantum(currency) is None:
            return self._trace(13, INSUFFICIENT, f"Bank transaction {bank_id} lacks valid type/direction/status/date/amount/currency.", base, subject_ids=[bank_id])
        if direction != "DEBIT" or bank_status != "POSTED" or posted_date > self.as_of_date:
            return self._trace(13, MATCH, f"Bank transaction {bank_id} is not a posted debit through the cutoff.", base, subject_ids=[bank_id])
        if transaction_type == "PAYMENT_REVERSAL":
            return self._trace(13, MATCH, f"Bank transaction {bank_id} is a documented payment reversal and excluded from F13.", base, subject_ids=[bank_id])
        if transaction_type == "BANK_FEE":
            balanced, issue = self._balanced_journals(bank_id, "BANK_FEE", currency or "")
            if issue:
                return self._trace(13, INSUFFICIENT, f"Bank fee {bank_id} journal cannot be evaluated: {issue}.", base, subject_ids=[bank_id])
            if balanced:
                journal_rows = [row for journal in balanced for row in journal]
                return self._trace(13, MATCH, f"Bank fee {bank_id} has {len(balanced)} balanced source-linked BANK_FEE journal(s).", base + [("gl_entries", row) for row in journal_rows], subject_ids=[bank_id])
            return self._trace(13, ANOMALY,
                f"Posted bank fee {bank_id} amount {amount} {currency} has no balanced source-linked BANK_FEE journal in the complete GL snapshot.",
                base, required=["bank_transactions"], absence_tables=["gl_entries"], subject_ids=[bank_id])
        reference = norm_reference(self.store.field("bank_transactions", bank, "payment_reference"))
        if reference is None:
            return self._trace(13, INSUFFICIENT, f"Bank transaction {bank_id} has no normalized payment reference.", base, subject_ids=[bank_id])
        matches = self.store.payments_by_reference.get(reference, [])
        operational = {"ACH_DEBIT", "WIRE_DEBIT", "CHECK_CLEARING", "CARD_SETTLEMENT"}
        if transaction_type in operational and len(matches) == 0:
            return self._trace(13, ANOMALY,
                f"Posted operational debit {bank_id} type {transaction_type}, amount {amount} {currency}, reference {reference} has zero ERP payment matches.",
                base, required=["bank_transactions"], absence_tables=["payments"], subject_ids=[bank_id])
        if transaction_type in operational and len(matches) == 1:
            return self._trace(13, MATCH,
                f"Posted operational debit {bank_id} reference {reference} uniquely matches ERP payment {trim_id(self.store.field('payments', matches[0], 'payment_id'))}.",
                base + [("payments", matches[0])], subject_ids=[bank_id])
        if transaction_type in operational:
            return self._trace(13, INSUFFICIENT, f"Bank transaction {bank_id} reference {reference} matches {len(matches)} ERP payments and is ambiguous.", base + [("payments", row) for row in matches], subject_ids=[bank_id])
        return self._trace(13, INSUFFICIENT, f"Posted debit {bank_id} has unknown transaction type {transaction_type}; frozen F13 does not classify it.", base, subject_ids=[bank_id])

    def _f14(self, payment_id: str) -> RuleTrace:
        unavailable = self._unavailable(14, payment_id, ("payments", "bank_transactions", "gl_entries", "audit_log"))
        if unavailable:
            return unavailable
        payment = self.store.row("payments", payment_id)
        if payment is None:
            return self._trace(14, INSUFFICIENT, f"Payment {payment_id} is missing.", subject_ids=[payment_id])
        base = [("payments", payment)]
        reference = norm_reference(self.store.field("payments", payment, "reference_number"))
        payment_currency = norm_text(self.store.field("payments", payment, "payment_currency"))
        payment_amount = parse_decimal(self.store.field("payments", payment, "payment_amount"))
        if reference is None or payment_amount is None or currency_quantum(payment_currency) is None:
            return self._trace(14, INSUFFICIENT, f"Payment {payment_id} lacks valid reference/currency/amount.", base, subject_ids=[payment_id])
        banks: list[dict[str, str]] = []
        for bank in self.store.banks_by_reference.get(reference, []):
            direction = norm_status(self.store.field("bank_transactions", bank, "direction"))
            status = norm_status(self.store.field("bank_transactions", bank, "status"))
            transaction_type = norm_status(self.store.field("bank_transactions", bank, "transaction_type"))
            posted_date = parse_date(self.store.field("bank_transactions", bank, "posted_date"))
            if posted_date is None:
                return self._trace(14, INSUFFICIENT, f"Payment {payment_id} has a reference-matched bank row with invalid posted date.", base + [("bank_transactions", bank)], subject_ids=[payment_id])
            if direction == "DEBIT" and status == "POSTED" and transaction_type != "BANK_FEE" and posted_date <= self.as_of_date:
                banks.append(bank)
        if len(banks) != 1:
            return self._trace(14, INSUFFICIENT, f"Payment {payment_id} reference {reference} has {len(banks)} qualifying non-fee posted bank debit(s); exactly one is required.", base + [("bank_transactions", row) for row in banks], subject_ids=[payment_id])
        bank = banks[0]
        bank_id = trim_id(self.store.field("bank_transactions", bank, "bank_transaction_id")) or ""
        bank_currency = norm_text(self.store.field("bank_transactions", bank, "currency"))
        bank_amount = parse_decimal(self.store.field("bank_transactions", bank, "amount"))
        if bank_currency is None or bank_amount is None:
            return self._trace(14, INSUFFICIENT, f"Matched bank transaction {bank_id} lacks currency/amount.", base + [("bank_transactions", bank)], subject_ids=[payment_id])
        evidence = base + [("bank_transactions", bank)]
        if bank_currency != payment_currency:
            balanced_fx, issue = self._balanced_journals(bank_id, "FX_SETTLEMENT", bank_currency)
            if issue:
                return self._trace(14, INSUFFICIENT, f"Cross-currency bank transaction {bank_id} FX journal is invalid: {issue}.", evidence, subject_ids=[payment_id])
            fx_events: list[dict[str, str]] = []
            for event in self.store.audit_by_entity.get(bank_id, []):
                entity_type = norm_status(self.store.field("audit_log", event, "entity_type"))
                event_type = norm_status(self.store.field("audit_log", event, "event_type"))
                if entity_type != "BANK_TRANSACTION" or event_type != "FX_CONVERSION_APPLIED":
                    continue
                event_time = parse_ts(self.store.field("audit_log", event, "timestamp"))
                if event_time is None:
                    return self._trace(14, INSUFFICIENT, f"Bank transaction {bank_id} has an FX_CONVERSION_APPLIED event with invalid timestamp.", evidence + [("audit_log", event)], subject_ids=[payment_id])
                if event_time.date() <= self.as_of_date:
                    fx_events.append(event)
            if balanced_fx and fx_events:
                fx_rows = [row for journal in balanced_fx for row in journal]
                return self._trace(14, MATCH,
                    f"Payment {payment_id} {payment_amount} {payment_currency} and bank {bank_id} {bank_amount} {bank_currency} have balanced FX journal=true and pre-cutoff FX event=true.",
                    evidence + [("gl_entries", row) for row in fx_rows] + [("audit_log", row) for row in fx_events], subject_ids=[payment_id])
            return self._trace(14, INSUFFICIENT,
                f"Payment {payment_id} and bank {bank_id} currencies differ ({payment_currency}/{bank_currency}); balanced FX journal={bool(balanced_fx)}, structured FX event={bool(fx_events)}.",
                evidence, subject_ids=[payment_id])
        delta = abs(payment_amount - bank_amount)
        balanced_fees, issue = self._balanced_journals(bank_id, "BANK_FEE", payment_currency or "")
        if issue:
            return self._trace(14, INSUFFICIENT, f"Bank transaction {bank_id} linked fee journal is invalid: {issue}.", evidence, subject_ids=[payment_id])
        explained_fee = Decimal(0)
        fee_rows: list[dict[str, str]] = []
        for journal in balanced_fees:
            fee_rows.extend(journal)
            explained_fee += sum(parse_decimal(self.store.field("gl_entries", row, "debit")) or Decimal(0) for row in journal)
        quantum = currency_quantum(payment_currency) or Decimal(0)
        if delta <= quantum or abs(delta - explained_fee) <= quantum:
            return self._trace(14, MATCH,
                f"Payment {payment_id} {payment_amount} {payment_currency}, bank {bank_id} {bank_amount}: absolute delta {delta}, explained balanced fee {explained_fee}.",
                evidence + [("gl_entries", row) for row in fee_rows], subject_ids=[payment_id])
        return self._trace(14, ANOMALY,
            f"Payment {payment_id} {payment_amount} {payment_currency}, bank {bank_id} {bank_amount}: absolute delta {delta}, explained balanced fee {explained_fee}.",
            evidence + [("gl_entries", row) for row in fee_rows], required=["payments", "bank_transactions"], absence_tables=["gl_entries"] if not fee_rows else [], subject_ids=[payment_id])

    def _valid_f15_obligation(self, payment: dict[str, str]) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
        payment_id = trim_id(self.store.field("payments", payment, "payment_id")) or ""
        vendor_id = trim_id(self.store.field("payments", payment, "vendor_id"))
        if vendor_id is None:
            return [], "payment vendor is missing"
        valid: list[tuple[str, dict[str, str]]] = []
        for allocation in self.store.allocations_by_payment.get(payment_id, []):
            invoice_id = trim_id(self.store.field("payment_allocations", allocation, "invoice_id"))
            allocation_date = parse_date(self.store.field("payment_allocations", allocation, "allocation_date"))
            allocated_amount = parse_decimal(self.store.field("payment_allocations", allocation, "allocated_amount"))
            invoice = self.store.row("invoices", invoice_id)
            if allocation_date is None or allocated_amount is None:
                return [], "allocation date/amount is invalid"
            if invoice is not None and trim_id(self.store.field("invoices", invoice, "vendor_id")) == vendor_id:
                valid.extend((("payment_allocations", allocation), ("invoices", invoice)))
        return valid, None if valid else "no allocation references an existing same-vendor invoice"

    def _build_f15_analysis(self) -> dict[str, Any]:
        if hasattr(self, "_f15_analysis"):
            return self._f15_analysis
        issues: dict[str, list[str]] = {}
        evaluated: set[str] = set()
        obligations: dict[str, list[tuple[str, dict[str, str]]]] = {}
        payment_rows: dict[str, dict[str, str]] = {}
        economic_index: dict[tuple[str, str, Decimal], list[dict[str, str]]] = {}
        for payment in self.store.rows("payments"):
            payment_id = trim_id(self.store.field("payments", payment, "payment_id")) or ""
            payment_rows[payment_id] = payment
            effective = self._effective_payment(payment)
            currency = norm_text(self.store.field("payments", payment, "payment_currency"))
            amount = q_money(self.store.field("payments", payment, "payment_amount"), currency)
            token = trim_id(self.store.field("payments", payment, "bank_account_id"))
            payment_date = parse_date(self.store.field("payments", payment, "payment_date"))
            reference = norm_reference(self.store.field("payments", payment, "reference_number"))
            obligation, obligation_issue = self._valid_f15_obligation(payment)
            if obligation_issue is None:
                obligations[payment_id] = obligation
            if None in (effective, currency, amount, token, payment_date, reference) or currency_quantum(currency) is None:
                issues.setdefault(payment_id, []).append("missing token/reference/date/currency/amount/status")
                continue
            if effective and obligation_issue is None:
                economic_index.setdefault((currency or "", token or "", amount), []).append(payment)
        edges: dict[str, tuple[str, str]] = {}
        edge_banks: dict[str, dict[str, str]] = {}
        for bank in self.store.rows("bank_transactions"):
            bank_id = trim_id(self.store.field("bank_transactions", bank, "bank_transaction_id")) or ""
            direction = norm_status(self.store.field("bank_transactions", bank, "direction"))
            status = norm_status(self.store.field("bank_transactions", bank, "status"))
            posted_date = parse_date(self.store.field("bank_transactions", bank, "posted_date"))
            if direction != "DEBIT" or status != "POSTED" or posted_date is None or posted_date > self.as_of_date:
                continue
            reference = norm_reference(self.store.field("bank_transactions", bank, "payment_reference"))
            ref_candidates = self.store.payments_by_reference.get(reference or "", [])
            ref_ids = [trim_id(self.store.field("payments", row, "payment_id")) or "" for row in ref_candidates]
            bank_currency = norm_text(self.store.field("bank_transactions", bank, "currency"))
            bank_amount = q_money(self.store.field("bank_transactions", bank, "amount"), bank_currency)
            token = trim_id(self.store.field("bank_transactions", bank, "counterparty_token"))
            transaction_date = parse_date(self.store.field("bank_transactions", bank, "transaction_date"))
            econ_candidates: list[dict[str, str]] = []
            if bank_currency is not None and bank_amount is not None and token is not None and transaction_date is not None:
                quantum = currency_quantum(bank_currency)
                amounts = {bank_amount}
                if quantum is not None:
                    amounts.update((bank_amount - quantum, bank_amount + quantum))
                candidates = {
                    trim_id(self.store.field("payments", row, "payment_id")) or "": row
                    for candidate_amount in amounts
                    for row in economic_index.get((bank_currency, token, candidate_amount), [])
                }
                for row in candidates.values():
                    payment_date = parse_date(self.store.field("payments", row, "payment_date"))
                    if payment_date is not None and abs((transaction_date - payment_date).days) <= self.cross_match_days and within_money(
                        self.store.field("bank_transactions", bank, "amount"),
                        self.store.field("payments", row, "payment_amount"),
                        bank_currency,
                    ) is True:
                        econ_candidates.append(row)
            econ_ids = [trim_id(self.store.field("payments", row, "payment_id")) or "" for row in econ_candidates]
            for payment_id in set(ref_ids + econ_ids):
                evaluated.add(payment_id)
            if len(ref_ids) != 1:
                for payment_id in ref_ids:
                    issues.setdefault(payment_id, []).append(f"bank {bank_id} has {len(ref_ids)} reference candidates")
            if len(econ_ids) != 1:
                for payment_id in set(ref_ids + econ_ids):
                    issues.setdefault(payment_id, []).append(f"bank {bank_id} has {len(econ_ids)} economic candidates")
            if len(ref_ids) == 1 and len(econ_ids) == 1:
                if ref_ids[0] != econ_ids[0]:
                    edges[bank_id] = (ref_ids[0], econ_ids[0])
                    edge_banks[bank_id] = bank
        cycles: dict[str, list[dict[str, Any]]] = {}
        edge_ids = sorted(edges)
        for index, bank_a_id in enumerate(edge_ids):
            ref_a, econ_a = edges[bank_a_id]
            for bank_b_id in edge_ids[index + 1:]:
                ref_b, econ_b = edges[bank_b_id]
                if ref_a != econ_b or econ_a != ref_b:
                    continue
                payment_a = payment_rows[econ_a]
                payment_b = payment_rows[econ_b]
                vendor_a = trim_id(self.store.field("payments", payment_a, "vendor_id"))
                vendor_b = trim_id(self.store.field("payments", payment_b, "vendor_id"))
                amount_a = parse_decimal(self.store.field("payments", payment_a, "payment_amount"))
                amount_b = parse_decimal(self.store.field("payments", payment_b, "payment_amount"))
                currency_a = norm_text(self.store.field("payments", payment_a, "payment_currency"))
                if vendor_a != vendor_b or amount_a is None or amount_b is None or currency_quantum(currency_a) is None:
                    continue
                if within_money(amount_a, amount_b, currency_a) is not False:
                    continue
                cycle = {
                    "banks": [edge_banks[bank_a_id], edge_banks[bank_b_id]],
                    "payments": [payment_a, payment_b],
                    "obligations": obligations[econ_a] + obligations[econ_b],
                    "bank_ids": [bank_a_id, bank_b_id],
                    "payment_ids": [econ_a, econ_b],
                    "reference_pairs": [(bank_a_id, ref_a), (bank_b_id, ref_b)],
                    "economic_pairs": [(bank_a_id, econ_a), (bank_b_id, econ_b)],
                }
                for payment_id in {ref_a, econ_a, ref_b, econ_b}:
                    cycles.setdefault(payment_id, []).append(cycle)
        self._f15_analysis = {"issues": issues, "evaluated": evaluated, "cycles": cycles}
        return self._f15_analysis

    def _f15(self, payment_ids: list[str]) -> RuleTrace:
        unavailable = self._unavailable(15, ",".join(payment_ids), ("payments", "bank_transactions", "payment_allocations", "invoices"))
        if unavailable:
            return unavailable
        analysis = self._build_f15_analysis()
        for payment_id in payment_ids:
            cycles = analysis["cycles"].get(payment_id, [])
            if cycles:
                cycle = sorted(cycles, key=lambda value: (value["bank_ids"], value["payment_ids"]))[0]
                payments = cycle["payments"]
                banks = cycle["banks"]
                amount_pairs = [
                    (trim_id(self.store.field("payments", payment, "payment_id")), self.store.field("payments", payment, "payment_amount"))
                    for payment in payments
                ]
                token_pairs = [
                    (trim_id(self.store.field("bank_transactions", bank, "bank_transaction_id")), self.store.field("bank_transactions", bank, "counterparty_token"))
                    for bank in banks
                ]
                evidence = [("payments", row) for row in payments] + [("bank_transactions", row) for row in banks] + cycle["obligations"]
                return self._trace(15, ANOMALY,
                    f"Reciprocal cross-match: current reference pairs {cycle['reference_pairs']}, unique economic pairs {cycle['economic_pairs']}, payment amounts {amount_pairs}, bank counterparty tokens {token_pairs}.",
                    evidence, required=["payments", "bank_transactions", "payment_allocations", "invoices"], subject_ids=payment_ids)
        relevant_issues = [issue for payment_id in payment_ids for issue in analysis["issues"].get(payment_id, [])]
        unevaluated = [payment_id for payment_id in payment_ids if payment_id not in analysis["evaluated"]]
        if relevant_issues or unevaluated:
            details = sorted(set(relevant_issues + [f"payment {payment_id} has no unique reference/economic bank candidate" for payment_id in unevaluated]))
            evidence = [("payments", payment) for payment_id in payment_ids if (payment := self.store.row("payments", payment_id)) is not None]
            return self._trace(15, INSUFFICIENT, f"F15 candidate evidence is missing or ambiguous: {'; '.join(details)}.", evidence, subject_ids=payment_ids)
        evidence = [("payments", payment) for payment_id in payment_ids if (payment := self.store.row("payments", payment_id)) is not None]
        return self._trace(15, MATCH, f"Payment(s) {payment_ids} have unique consistent bank/economic pairings and no reciprocal two-cycle.", evidence, subject_ids=payment_ids)
