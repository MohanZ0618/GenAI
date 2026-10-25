"""Normative constants transcribed from the checksum-frozen RAG v1.0 spec."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SPEC_RELATIVE_PATH = Path("docs/frozen_rag_baseline_spec_v1.0.md")
SPEC_SHA_RELATIVE_PATH = Path("docs/frozen_rag_baseline_spec_v1.0.sha256")
SPEC_SHA256 = "390a23c63989a1b7593d336bd96b51f171180729f1e66284688032a01243d715"
SPEC_VERSION = "1.0"
CORPUS_VERSION = "finrca_standard_rag_corpus_v1.0"
QUERY_VERSION = "standard_rag_query_v1.0"
PROMPT_VERSION = "standard_rag_reasoning_prompt_v1.0"
OUTPUT_SCHEMA_VERSION = "standard_rag_output_schema_v1.0"
INDEX_VERSION = "ExactFlatCosineNumpyV1"
DECISION_CUTOFF = "2026-06-30"
EXPECTED_DATASET_SHA256 = "c73ad3e98575cb4093b1b3898f759d69c57a97840b4d39661b983e91692761d8"
EXPECTED_SOURCE_MANIFEST_SHA256 = "47080bebc76fcd8a6c12a0a307f80845d692674fe8089b80c1d40e8ac4769956"
EXPECTED_TEXT_MANIFEST_SHA256 = "8842865bd6e688f824a0b16450301fb547c62c4ba495099d605753ebaf2ff00d"
EXPECTED_DOCUMENT_COUNT = 155_391
EMBEDDING_INPUT_LIMIT = 8_192
K_GRID = (5, 10, 20, 40)
VALIDATION_MAX_K = 40
BOOTSTRAP_SEED = 20_260_809
BOOTSTRAP_RESAMPLES = 10_000


RECORD_TYPES: dict[str, str] = {
    "vendors": "VENDOR",
    "vendor_change_log": "VENDOR_CHANGE",
    "purchase_orders": "PURCHASE_ORDER",
    "po_lines": "PO_LINE",
    "invoices": "INVOICE",
    "invoice_lines": "INVOICE_LINE",
    "approval_events": "APPROVAL_EVENT",
    "payments": "PAYMENT",
    "payment_allocations": "PAYMENT_ALLOCATION",
    "gl_entries": "GL_ENTRY",
    "bank_transactions": "BANK_TRANSACTION",
    "bank_statements": "BANK_STATEMENT",
    "employees": "EMPLOYEE",
    "audit_log": "AUDIT_EVENT",
}

AVAILABILITY_FIELDS: dict[str, str | None] = {
    "vendors": "created_at",
    "vendor_change_log": "changed_at",
    "purchase_orders": "po_date",
    "po_lines": None,  # inherits purchase order eligibility
    "invoices": "created_at",
    "invoice_lines": None,  # inherits invoice eligibility
    "approval_events": "event_timestamp",
    "payments": "created_at",
    "payment_allocations": "allocation_date",
    "gl_entries": "posting_date",
    "bank_transactions": "posted_date",
    "bank_statements": "statement_date",
    "employees": None,  # delivered cutoff snapshot; source has no row timestamp
    "audit_log": "timestamp",
}

# Individual values make a combined-manifest failure locally diagnosable.
EXPECTED_SOURCE_FILES: dict[str, tuple[str, int]] = {
    "approval_events.csv": ("1b06ae818dd5db4e994ae33604996949c85bda4f09b1d5212d9b2918165060d6", 17_429),
    "audit_log.csv": ("df9672985bb829933c520f8070007351161f155e79c3ad75f310431bcc33fa38", 28_034),
    "bank_statements.csv": ("03ae8c7053d9f496ac1572e8935a3e7a90a932bb7174b06e8f5a1256ef8c2933", 57),
    "bank_transactions.csv": ("3692b353dda734eb89eb4f90c547493112852d90cff291f0b816719544fca513", 6_263),
    "employees.csv": ("1fa83c16c723e07c1f437869536a23d65bfe732123e18f83e5747e92e904e203", 120),
    "gl_entries.csv": ("fb3bb454d7a1c2278286fd9d71dbca579d893c94c49dc305659e34585fc8852a", 46_765),
    "invoice_lines.csv": ("630c357a611a99e7fd8b59d0ce9facfd1b5d8f7940907ba73e493b385b575d47", 18_299),
    "invoices.csv": ("49a529ab18e6b0d2373cbf9ab5352a5ab1df74580907ef96900af012e85416e8", 8_147),
    "payment_allocations.csv": ("0bff28018ce3053352ba3e41d084d931d6cede03bfa12ca05e5e4332b3b441aa", 7_180),
    "payments.csv": ("0289a1fe560edb8afc5f199d2dc6f485e08f14c805bffa532b4781f9e474c2f2", 6_200),
    "po_lines.csv": ("6a8edf1f626d4257000203fc59477b77be17c533b6e420f273e2e233b31f4b36", 11_231),
    "purchase_orders.csv": ("191886778cd6884a41ca69fc4f47760ad40077990ceb41d940e5642ba19845a0", 5_000),
    "vendor_change_log.csv": ("98218759f5e365219221a342dc559a2b2827106ead4d7685db9ae6cf7b1d9e6f", 186),
    "vendors.csv": ("75bebafe8fdec13bc9c52a8bf344a034d104088d034b137b537039cc732190c5", 500),
}

ROUTE_KEYS = frozenset({"case_id", "primary_entity_type", "primary_entity_id"})
FORBIDDEN_ARTIFACT_NAMES = frozenset({
    "case_entity_records.jsonl", "failure_manifest.csv", "rca_ground_truth.jsonl",
    "causal_edges.csv", "mutation_log.jsonl", "predictions.jsonl", "rule_traces.jsonl",
    "dataset_quality_report.json",
})
FORBIDDEN_KEYS = frozenset({
    "failure_type", "expected_failure_type", "has_reconciliation_failure", "is_anomaly",
    "anomaly_indicator", "evidence_ids", "evidence_required", "expected_answer",
    "expected_resolution", "root_cause", "root_cause_category", "observed_symptom",
    "affected_entities", "difficulty", "tier", "reasoning_hops", "hop_count", "split",
    "severity", "scenario_variant", "triggered_rule_id", "rules_status", "rules_prediction",
    "ml_prediction", "ml_probability", "correctness", "adjudication",
})

FAILURE_TYPES = (
    "F01_DUPLICATE_INVOICE", "F02_PO_INVOICE_AMOUNT_MISMATCH", "F03_QUANTITY_MISMATCH",
    "F04_INCORRECT_VENDOR_ASSOCIATION", "F05_PAYMENT_WITHOUT_VALID_INVOICE",
    "F06_INVOICE_PAID_TWICE", "F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE",
    "F08_APPROVAL_WORKFLOW_FAILURE", "F09_GL_POSTING_MISMATCH",
    "F10_WRONG_ACCOUNTING_PERIOD", "F11_VENDOR_MASTER_CHANGE_CONFLICT",
    "F12_ERP_PAYMENT_MISSING_FROM_BANK", "F13_BANK_TRANSACTION_MISSING_FROM_ERP",
    "F14_BANK_ERP_AMOUNT_MISMATCH", "F15_INCORRECT_PAYMENT_BANK_MATCH",
)
ALL_CLASSES = (*FAILURE_TYPES, "NO_FAILURE")


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "OpenAI"
    endpoint: str = "v1/embeddings"
    model_id: str = "text-embedding-3-small"
    dimensions: int = 1536
    encoding_format: str = "float"
    corpus_batch_size: int = 128
    query_batch_size: int = 1
    max_attempts: int = 4
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0)
    request_timeout_seconds: float = 120.0
    usd_per_million_input_tokens: float = 0.02
    pricing_reference_date: str = "2026-08-09"

    def serializable(self) -> dict[str, Any]:
        value = asdict(self)
        value["backoff_seconds"] = list(self.backoff_seconds)
        return value


@dataclass(frozen=True)
class ReasonerConfig:
    provider: str = "OpenAI"
    endpoint: str = "Responses API"
    model_id: str = "gpt-5.6-sol"
    reasoning_effort: str = "medium"
    max_output_tokens: int = 1000
    verbosity: str = "low"
    store: bool = False
    truncation: str = "disabled"
    service_tier: str = "default"
    concurrency: int = 1
    request_timeout_seconds: float = 120.0
    max_attempts: int = 4
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0)
    context_window_tokens: int = 1_050_000
    reserved_output_tokens: int = 1_000
    input_usd_per_million_tokens: float = 5.0
    cached_input_usd_per_million_tokens: float = 0.5
    output_usd_per_million_tokens: float = 30.0
    pricing_reference_date: str = "2026-08-09"

    def serializable(self) -> dict[str, Any]:
        value = asdict(self)
        value["backoff_seconds"] = list(self.backoff_seconds)
        return value


EMBEDDING_CONFIG = EmbeddingConfig()
REASONER_CONFIG = ReasonerConfig()
