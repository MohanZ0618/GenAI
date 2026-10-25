"""Strict frozen Standard RAG structured-output schema and harness validation."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.rag.config import FAILURE_TYPES


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


class RAGPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    method: Literal["rag"]
    status: Literal["MATCH", "ANOMALY", "INSUFFICIENT_EVIDENCE"]
    is_anomaly: bool | None
    predicted_failure_type: FailureType | None
    evidence_record_ids: list[str]
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    retrieved_record_ids: list[str]

    @model_validator(mode="after")
    def enforce_contract(self) -> "RAGPrediction":
        if len(self.retrieved_record_ids) != len(set(self.retrieved_record_ids)):
            raise ValueError("retrieved_record_ids must not contain duplicates")
        if len(self.evidence_record_ids) != len(set(self.evidence_record_ids)):
            raise ValueError("evidence_record_ids must not contain duplicates")
        invented = sorted(set(self.evidence_record_ids) - set(self.retrieved_record_ids))
        if invented:
            raise ValueError(f"nonretrieved evidence record ID(s): {invented}")
        if self.status == "MATCH":
            if self.is_anomaly is not False or self.predicted_failure_type != "NO_FAILURE":
                raise ValueError("MATCH requires is_anomaly=false and predicted_failure_type=NO_FAILURE")
            if not self.evidence_record_ids:
                raise ValueError("MATCH requires at least one retrieved evidence record ID")
        elif self.status == "ANOMALY":
            if self.is_anomaly is not True or self.predicted_failure_type not in FAILURE_TYPES:
                raise ValueError("ANOMALY requires is_anomaly=true and one F01-F15 class")
            if not self.evidence_record_ids:
                raise ValueError("ANOMALY requires at least one retrieved evidence record ID")
        else:
            if self.is_anomaly is not None or self.predicted_failure_type is not None:
                raise ValueError("INSUFFICIENT_EVIDENCE requires null anomaly and class fields")
            if self.evidence_record_ids:
                raise ValueError("INSUFFICIENT_EVIDENCE requires no evidence IDs")
        return self


def validate_prediction(
    value: RAGPrediction | dict[str, object] | str,
    *,
    expected_case_id: str,
    expected_retrieved_record_ids: list[str],
) -> RAGPrediction:
    if isinstance(value, RAGPrediction):
        prediction = value
    elif isinstance(value, str):
        prediction = RAGPrediction.model_validate_json(value)
    else:
        prediction = RAGPrediction.model_validate(value)
    if prediction.case_id != expected_case_id:
        raise ValueError(
            f"response case_id mismatch: expected {expected_case_id}, got {prediction.case_id}"
        )
    if prediction.retrieved_record_ids != expected_retrieved_record_ids:
        raise ValueError("response retrieved_record_ids differs from frozen request rank order")
    return prediction


def canonical_output_schema() -> str:
    return json.dumps(RAGPrediction.model_json_schema(), sort_keys=True, separators=(",", ":"))
