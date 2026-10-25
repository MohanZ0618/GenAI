from src.rules_sql.engine import INSUFFICIENT
from src.rules_sql.registry import PRECEDENCE, RULES
from src.schema import TABLE_SCHEMAS

from tests.rules_sql.helpers import engine, row


def test_registry_has_all_15_frozen_rules_and_distribution() -> None:
    assert [rule.rule_id for rule in RULES] == [f"RSQL_F{number:02d}_V1" for number in range(1, 16)]
    assert len(PRECEDENCE) == 15
    assert sum(rule.tier == 1 for rule in RULES) == 1
    assert sum(rule.tier == 2 for rule in RULES) == 5
    assert sum(rule.tier == 3 for rule in RULES) == 9
    assert {rule.hop_count for rule in RULES} == {0, 1, 2, 3, 4}


def test_every_registered_spec_field_exists_in_actual_schema() -> None:
    missing = [
        f"{table}.{field}"
        for rule in RULES
        for table, fields in rule.required_fields.items()
        for field in fields
        if table not in TABLE_SCHEMAS or field not in TABLE_SCHEMAS[table]
    ]
    assert missing == []


def test_missing_primary_evidence_is_insufficient_for_every_rule(tmp_path) -> None:
    baseline = engine(tmp_path)
    traces = [baseline.rule_functions[f"RSQL_F{number:02d}_V1"]("MISSING") for number in range(1, 15)]
    traces.append(baseline._f15(["MISSING"]))
    assert [trace.status for trace in traces] == [INSUFFICIENT] * 15


def test_null_required_fields_are_not_collapsed_to_match(tmp_path) -> None:
    tables = {
        "invoices": [row("invoices", invoice_id="I_NULL")],
        "payments": [row("payments", payment_id="P_NULL")],
        "bank_transactions": [row("bank_transactions", bank_transaction_id="B_NULL")],
    }
    baseline = engine(tmp_path, tables)
    invoice_rules = (1, 2, 3, 4, 6, 7)
    payment_rules = (5, 8, 9, 10, 11, 12, 14)
    traces = [baseline.rule_functions[f"RSQL_F{number:02d}_V1"]("I_NULL") for number in invoice_rules]
    traces += [baseline.rule_functions[f"RSQL_F{number:02d}_V1"]("P_NULL") for number in payment_rules]
    traces += [baseline.rule_functions["RSQL_F13_V1"]("B_NULL"), baseline._f15(["P_NULL"])]
    assert len(traces) == 15
    assert all(trace.status == INSUFFICIENT for trace in traces)


def test_prohibited_column_access_audit(tmp_path) -> None:
    baseline = engine(tmp_path, {"audit_log": [row(
        "audit_log", event_id="A1", entity_id="B1", entity_type="bank_transaction",
        event_type="fx_conversion_applied", timestamp="2026-06-01T00:00:00",
    )]})
    audit = baseline.store.leakage_audit()
    assert audit["status"] == "PASS"
    assert audit["prohibited_column_accesses"] == []
    assert "audit_log.entity_id" in audit["accessed_columns"]
