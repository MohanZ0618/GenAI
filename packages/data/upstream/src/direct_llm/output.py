"""Strict structured-output model and packet-aware validation."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.direct_llm.config import FAILURE_TYPES


FailureType = Literal[
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
    "NO_FAILURE",
]


class DirectLLMPrediction(BaseModel):
    """One auditable reconciliation decision."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=64)
    status: Literal["MATCH", "ANOMALY", "INSUFFICIENT_EVIDENCE"]
    is_anomaly: bool | None
    predicted_failure_type: FailureType | None
    evidence_record_ids: list[str] = Field(max_length=128)
    reason: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def enforce_state_contract(self) -> "DirectLLMPrediction":
        if self.status == "MATCH":
            if self.is_anomaly is not False or self.predicted_failure_type != "NO_FAILURE":
                raise ValueError("MATCH requires is_anomaly=false and predicted_failure_type=NO_FAILURE")
        elif self.status == "ANOMALY":
            if self.is_anomaly is not True or self.predicted_failure_type not in FAILURE_TYPES:
                raise ValueError("ANOMALY requires is_anomaly=true and one F01-F15 class")
            if not self.evidence_record_ids:
                raise ValueError("ANOMALY requires at least one observed evidence record ID")
        else:
            if self.is_anomaly is not None or self.predicted_failure_type is not None:
                raise ValueError("INSUFFICIENT_EVIDENCE requires null anomaly and failure fields")
        if len(self.evidence_record_ids) != len(set(self.evidence_record_ids)):
            raise ValueError("evidence_record_ids must not contain duplicates")
        return self


def validate_prediction(
    value: DirectLLMPrediction | dict[str, object] | str,
    *,
    expected_case_id: str,
    permitted_evidence_ids: set[str],
) -> DirectLLMPrediction:
    """Parse and enforce case/evidence constraints not expressible in JSON Schema."""
    if isinstance(value, DirectLLMPrediction):
        prediction = value
    elif isinstance(value, str):
        prediction = DirectLLMPrediction.model_validate_json(value)
    else:
        prediction = DirectLLMPrediction.model_validate(value)
    if prediction.case_id != expected_case_id:
        raise ValueError(
            f"response case_id mismatch: expected {expected_case_id}, got {prediction.case_id}"
        )
    invented = sorted(set(prediction.evidence_record_ids) - permitted_evidence_ids)
    if invented:
        raise ValueError(f"hallucinated evidence record ID(s): {invented}")
    return prediction


def canonical_output_schema() -> str:
    """Canonical JSON used in request hashes."""
    return json.dumps(
        DirectLLMPrediction.model_json_schema(), sort_keys=True, separators=(",", ":")
    )
