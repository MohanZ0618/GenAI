"""Dataset quality metrics and researcher-readable statistics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from src.ground_truth.rca_builder import GroundTruthValidation
from src.ground_truth.splits import leakage_report
from src.io import serializable
from src.models import FinanceDataset
from src.schema import PRIMARY_KEYS
from src.utils.money import decimal, sum_money
from src.validation import ValidationReport, validate_dataset
from src.validation.failure_signatures import validate_failure_signatures
from src.validation.financial_rules import validate_bank_statements, validate_gl_balance
from src.validation.reconciliation_rules import validate_erp_bank, validate_operational_gl


def canonical_dataset_hash(dataset: FinanceDataset, cases: list[dict[str, Any]]) -> str:
    payload = {"tables": serializable(dataset.tables), "cases": serializable(cases)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _distribution(values: list[object]) -> dict[str, str]:
    if not values:
        return {"count": "0", "min": "0", "median": "0", "p95": "0", "max": "0", "sum": "0"}
    ordered = sorted(decimal(value) for value in values)
    return {
        "count": str(len(ordered)),
        "min": format(ordered[0], "f"),
        "median": format(ordered[len(ordered) // 2], "f"),
        "p95": format(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], "f"),
        "max": format(ordered[-1], "f"),
        "sum": format(sum(ordered, Decimal("0")), "f"),
    }


def _duplicate_ids(dataset: FinanceDataset) -> dict[str, int]:
    result: dict[str, int] = {}
    for table, keys in PRIMARY_KEYS.items():
        identities = [tuple(row[key] for key in keys) for row in dataset.rows(table)]
        result[table] = len(identities) - len(set(identities))
    return result


def _null_statistics(dataset: FinanceDataset) -> dict[str, dict[str, int]]:
    return {
        table: {field: sum(row[field] in (None, "") for row in rows) for field in (rows[0].keys() if rows else [])}
        for table, rows in dataset.tables.items()
    }


def build_quality_report(
    clean: FinanceDataset,
    benchmark: FinanceDataset,
    cases: list[dict[str, Any]],
    clean_validation: ValidationReport,
    ground_truth_validation: GroundTruthValidation,
) -> dict[str, Any]:
    failures = [case for case in cases if case["failure_type"] != "NO_FAILURE"]
    vendor_spend: dict[str, list[object]] = defaultdict(list)
    for invoice in benchmark.rows("invoices"):
        vendor_spend[str(invoice["vendor_id"])].append(invoice["invoice_total"])
    totals = {vendor: sum_money(values) for vendor, values in vendor_spend.items()}
    total_spend = sum(totals.values(), Decimal("0"))
    top_ten = sum(sorted(totals.values(), reverse=True)[:10], Decimal("0"))
    strict_benchmark = validate_dataset(benchmark, clean=False)
    gl_issues = validate_gl_balance(benchmark)
    statement_issues = validate_bank_statements(benchmark)
    report = {
        "benchmark_version": "1.0.0",
        "synthetic_data_only": True,
        "dataset_hash": canonical_dataset_hash(benchmark, cases),
        "table_row_counts": {table: len(rows) for table, rows in benchmark.tables.items()},
        "clean_table_row_counts": {table: len(rows) for table, rows in clean.tables.items()},
        "number_of_cases": len(cases),
        "failure_cases": len(failures),
        "non_failure_cases": len(cases) - len(failures),
        "failures_per_category": dict(sorted(Counter(case["failure_type"] for case in failures).items())),
        "cases_by_difficulty": dict(sorted(Counter(case["difficulty"] for case in cases).items())),
        "monetary_distributions": {
            "invoice_total": _distribution([row["invoice_total"] for row in benchmark.rows("invoices")]),
            "payment_amount": _distribution([row["payment_amount"] for row in benchmark.rows("payments")]),
            "bank_transaction_amount": _distribution([row["amount"] for row in benchmark.rows("bank_transactions")]),
        },
        "vendor_concentration": {
            "vendors_with_invoices": len(totals),
            "top_10_vendor_spend_share": format(top_ten / total_spend if total_spend else Decimal("0"), ".6f"),
        },
        "payment_method_distribution": dict(sorted(Counter(str(row["payment_method"]) for row in benchmark.rows("payments")).items())),
        "date_range": {
            "invoice_min": min(str(row["invoice_date"]) for row in benchmark.rows("invoices")),
            "invoice_max": max(str(row["invoice_date"]) for row in benchmark.rows("invoices")),
            "bank_posted_min": min(str(row["posted_date"]) for row in benchmark.rows("bank_transactions")),
            "bank_posted_max": max(str(row["posted_date"]) for row in benchmark.rows("bank_transactions")),
        },
        "clean_validation": clean_validation.to_dict(),
        "post_injection_invariant_validation": strict_benchmark.to_dict(),
        "reconciliation_validation_results": {
            "operational_gl_issue_count": len(validate_operational_gl(benchmark)),
            "erp_bank_issue_count": len(validate_erp_bank(benchmark)),
            "note": "Post-injection reconciliation findings include intended benchmark cases.",
        },
        "gl_balancing_results": {"passed": not gl_issues, "unbalanced_journals": len(gl_issues)},
        "bank_statement_results": {"passed": not statement_issues, "invalid_statements": len(statement_issues)},
        "duplicate_ids": _duplicate_ids(benchmark),
        "null_statistics": _null_statistics(benchmark),
        "ground_truth_validation": {
            "passed": ground_truth_validation.passed,
            "issue_count": ground_truth_validation.issue_count,
            "issues": ground_truth_validation.issues,
        },
        "failure_signature_validation": validate_failure_signatures(benchmark, cases),
        "train_test_leakage_checks": leakage_report(cases),
    }
    report["quality_gate_passed"] = bool(
        clean_validation.passed
        and not gl_issues
        and not statement_issues
        and ground_truth_validation.passed
        and report["failure_signature_validation"]["passed"]
        and report["train_test_leakage_checks"]["passed"]
        and not any(report["duplicate_ids"].values())
    )
    return report


def build_statistics_markdown(report: dict[str, Any]) -> str:
    rows = report["table_row_counts"]
    failures = report["failures_per_category"]
    difficulty = report["cases_by_difficulty"]
    lines = [
        "# FinRCA-Bench Dataset Statistics",
        "",
        f"Dataset hash: `{report['dataset_hash']}`",
        "",
        f"Quality gate: **{'PASS' if report['quality_gate_passed'] else 'FAIL'}**",
        "",
        "## Case composition",
        "",
        f"- Total cases: {report['number_of_cases']}",
        f"- Failure cases: {report['failure_cases']}",
        f"- Legitimate/no-failure cases: {report['non_failure_cases']}",
        f"- Difficulty: {', '.join(f'{key}={value}' for key, value in difficulty.items())}",
        "",
        "## Table row counts",
        "",
        "| Table | Rows |",
        "|---|---:|",
        *[f"| {table} | {count} |" for table, count in rows.items()],
        "",
        "## Failure categories",
        "",
        "| Category | Cases |",
        "|---|---:|",
        *[f"| {category} | {count} |" for category, count in failures.items()],
        "",
        "## Financial profile",
        "",
        f"Top-ten vendor spend share: {report['vendor_concentration']['top_10_vendor_spend_share']}",
        "",
        f"Payment methods: {report['payment_method_distribution']}",
        "",
        "All records are synthetic and identifiers are tokenized. Post-injection reconciliation findings are intentional; "
        "the quality gate separately requires the clean baseline, double-entry journals, bank statements, evidence links, "
        "and split leakage checks to pass.",
        "",
    ]
    return "\n".join(lines)

