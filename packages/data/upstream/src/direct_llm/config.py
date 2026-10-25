"""Frozen configuration constants for the Phase 4 direct-LLM baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SPEC_VERSION = "1.0"
PROMPT_VERSION = "direct_llm_v1.0"
PACKET_VERSION = "direct_llm_case_packet_v1.0"
SCHEMA_VERSION = "direct_llm_output_schema_v1.0"
RETRY_POLICY_VERSION = "direct_llm_retry_v1.0"
AS_OF_DATE = "2026-06-30"


@dataclass(frozen=True)
class BaselineConfig:
    provider: str = "OpenAI"
    model_id: str = "gpt-5.6-sol"
    endpoint: str = "Responses API"
    reasoning_effort: str = "medium"
    temperature: None = None
    top_p: None = None
    max_output_tokens: int = 1000
    verbosity: str = "low"
    structured_output_mode: str = "Pydantic/JSON Schema strict"
    store: bool = False
    truncation: str = "disabled"
    service_tier: str = "default"
    concurrency: int = 1
    request_timeout_seconds: float = 120.0
    max_attempts: int = 4
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0)
    context_window_tokens: int = 1_050_000
    reserved_output_tokens: int = 1_000
    token_estimator: str = "ceil(Unicode characters / 3); conservative non-billing estimate"
    pricing_reference_date: str = "2026-08-08"
    input_usd_per_million_tokens: float = 5.0
    cached_input_usd_per_million_tokens: float = 0.5
    output_usd_per_million_tokens: float = 30.0
    stability_repetitions: int = 3
    stability_subset_size: int = 32
    stability_subset_salt: str = "phase4-direct-llm-stability-v1.0"

    def serializable(self) -> dict[str, Any]:
        value = asdict(self)
        value["backoff_seconds"] = list(self.backoff_seconds)
        return value


BASELINE_CONFIG = BaselineConfig()


FAILURE_TYPES: tuple[str, ...] = (
    "F01_DUPLICATE_INVOICE",
    "F02_PO_INVOICE_AMOUNT_MISMATCH",
    "F03_QUANTITY_MISMATCH",
    "F04_INCORRECT_VENDOR_ASSOCIATION",
    "F05_PAYMENT_WITHOUT_VALID_INVOICE",
    "F06_INVOICE_PAID_TWICE",
    "F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE",
    "F08_APPROVAL_WORKFLOW_FAILURE",
    "F09_GL_POSTING_MISMATCH",
    "F10_WRONG_ACCOUNTING_PERIOD",
    "F11_VENDOR_MASTER_CHANGE_CONFLICT",
    "F12_ERP_PAYMENT_MISSING_FROM_BANK",
    "F13_BANK_TRANSACTION_MISSING_FROM_ERP",
    "F14_BANK_ERP_AMOUNT_MISMATCH",
    "F15_INCORRECT_PAYMENT_BANK_MATCH",
)

ALL_CLASSES: tuple[str, ...] = (*FAILURE_TYPES, "NO_FAILURE")


FORBIDDEN_ARTIFACT_NAMES: frozenset[str] = frozenset({
    "case_entity_records.jsonl",
    "rca_ground_truth.jsonl",
    "failure_manifest.csv",
    "causal_edges.csv",
    "mutation_log.jsonl",
    "dataset_quality_report.json",
    "predictions.jsonl",
    "rule_traces.jsonl",
})

FORBIDDEN_PACKET_KEYS: frozenset[str] = frozenset({
    "failure_type",
    "expected_failure_type",
    "has_reconciliation_failure",
    "is_anomaly",
    "anomaly_indicator",
    "evidence_ids",
    "evidence_required",
    "expected_answer",
    "expected_resolution",
    "root_cause",
    "root_cause_category",
    "observed_symptom",
    "difficulty",
    "tier",
    "reasoning_hops",
    "hop_count",
    "split",
    "triggered_rule_id",
    "rules_status",
    "rules_prediction",
    "ml_prediction",
    "ml_probability",
    "correctness",
})
