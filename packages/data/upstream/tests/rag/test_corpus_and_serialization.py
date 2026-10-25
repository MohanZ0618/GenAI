from __future__ import annotations

import hashlib

import pytest

from src.rag.config import (
    EMBEDDING_INPUT_LIMIT,
    EXPECTED_DOCUMENT_COUNT,
    EXPECTED_SOURCE_MANIFEST_SHA256,
    EXPECTED_TEXT_MANIFEST_SHA256,
)
from src.rag.corpus import corpus_token_audit
from src.rag.leakage import assert_payload_label_blind, assert_source_registry
from src.rag.serialization import canonical_record_id, serialize_record
from src.schema import TABLE_SCHEMAS


GOLDEN_SHA256 = {
    "vendors": "cb4e3106c35a175393075fa55ff593b291e9f90847a6df0eefa4ddfd1d213c9d",
    "vendor_change_log": "5fe98574f35199b8faf2024d5a62391c143e08de3d22e4b0b5302489bc8f4e64",
    "purchase_orders": "5823df017c0262ec936431609c0500423588bb824b602c1a4a0b36481dddcea2",
    "po_lines": "49eb7f019726fe4fadd21a8904d40b51d5f6737b226afb5950657a3ddcffbd24",
    "invoices": "f76035f7f7346a01680128326a42e2fbad506238469de7be931280eaea4fc47e",
    "invoice_lines": "9ffad5d0a33e9416d8dd3af22b9c3ccc5ca6253e360601e4fee4b3d0dcd75feb",
    "approval_events": "5b01f7de5003ec511f7268708fd98c212d542b4f3da790d109d06c28bb410b42",
    "payments": "9f07985e68979dfccca0d9b4e081e2b811aa57255584917733109afd8549e4f6",
    "payment_allocations": "24aa2043f946a826c96ae131dc05ed20f263af8d4d7e75264caefbf8334ca719",
    "gl_entries": "90fb4eca3095e0db968cd7e0f0b8dbddb0782bf293024801cf52e9eddf4bce23",
    "bank_transactions": "dfd04cc9db13924d1eb65b8ccd4eb6ce048508c123c263695ed0f65c16c66784",
    "bank_statements": "7ab978218e79af52cbd2245407cecc09d28b655321a9069524c1f22ee949656b",
    "employees": "6c7454c131c626e1f8854721dcfe8213587f0ba0f28bdb244b3a23777e13f8ad",
    "audit_log": "1837c9101904df73c6e035bd90a4bd3249825425c142f9550cfe14844510eddd",
}


@pytest.mark.parametrize("table", list(TABLE_SCHEMAS))
def test_golden_serialization_is_byte_stable_for_every_record_type(table: str) -> None:
    row = {field: f"{table}-{field}-é" for field in TABLE_SCHEMAS[table]}
    value = serialize_record(table, row)
    assert hashlib.sha256(value.encode("utf-8")).hexdigest() == GOLDEN_SHA256[table]
    assert not value.endswith("\n")
    assert "\\u00e9" not in value
    assert value.splitlines()[1] == f"RECORD_ID: {canonical_record_id(table, row)}"


def test_serialization_rejects_reordered_or_missing_fields() -> None:
    row = {field: field for field in reversed(TABLE_SCHEMAS["invoices"])}
    with pytest.raises(ValueError, match="field order"):
        serialize_record("invoices", row)


def test_frozen_real_corpus_identity_cutoff_and_field_registry(frozen_corpus) -> None:
    assert len(frozen_corpus.documents) == EXPECTED_DOCUMENT_COUNT
    assert frozen_corpus.text_manifest_sha256 == EXPECTED_TEXT_MANIFEST_SHA256
    assert frozen_corpus.source_audit["observed_manifest_sha256"] == EXPECTED_SOURCE_MANIFEST_SHA256
    excluded = {
        table: len(frozen_corpus.raw_tables[table]) - len(frozen_corpus.eligible_rows[table])
        for table in TABLE_SCHEMAS
    }
    assert {key: value for key, value in excluded.items() if value} == {
        "gl_entries": 10,
        "bank_transactions": 2,
        "bank_statements": 3,
        "audit_log": 5,
    }
    for table, rows in frozen_corpus.eligible_rows.items():
        if rows:
            assert_source_registry(table, list(rows[0]))


def test_frozen_real_corpus_token_safety(frozen_corpus) -> None:
    audit = corpus_token_audit(frozen_corpus.documents)
    assert audit["status"] == "PASS"
    assert audit["document_count"] == EXPECTED_DOCUMENT_COUNT
    assert audit["maximum_tokens"] <= EMBEDDING_INPUT_LIMIT
    assert audit["oversized_count"] == 0


def test_forbidden_keys_are_recursive_and_serialized() -> None:
    with pytest.raises(RuntimeError, match="forbidden"):
        assert_payload_label_blind({"nested": [{"failure_type": "F01"}]}, name="test")
    with pytest.raises(RuntimeError, match="forbidden"):
        assert_payload_label_blind("TIER: 3", name="test")
