from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.direct_llm.audits import secret_audit, verify_frozen_artifacts
from src.direct_llm.config import FAILURE_TYPES, FORBIDDEN_PACKET_KEYS
from src.direct_llm.packet import (
    CasePacketBuilder,
    OperationalSnapshot,
    forbidden_key_paths,
    load_whitelisted_routes,
    select_stability_routes,
)
from src.direct_llm.normalization import norm_reference, norm_status, trim_id
from src.schema import TABLE_SCHEMAS


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/benchmark"


def test_frozen_spec_and_prompt_checksums() -> None:
    assert verify_frozen_artifacts(ROOT)["status"] == "PASS"


def test_phase4_local_structural_normalization() -> None:
    assert norm_reference(" inv-00 12/a ") == "INV0012A"
    assert norm_reference("００-12") == "0012"
    assert norm_status(" bank-transaction ") == "BANK_TRANSACTION"
    assert trim_id("  INV_1 ") == "INV_1"


def test_route_loader_whitelists_only_nonlabel_routing() -> None:
    routes = load_whitelisted_routes(DATA / "test")
    assert len(routes) == 439
    assert all(set(route) == {"case_id", "primary_entity_type", "primary_entity_id"} for route in routes)
    serialized = json.dumps(routes)
    assert not any(value in serialized for value in ("expected_answer", "failure_type", "difficulty", "split"))


def test_packet_is_deterministic_complete_schema_and_oracle_free() -> None:
    snapshot = OperationalSnapshot(DATA / "full")
    route = load_whitelisted_routes(DATA / "validation")[0]
    builder = CasePacketBuilder(snapshot)
    left = builder.build(route)
    right = builder.build(dict(route))
    assert left.serialized == right.serialized
    assert left.packet_sha256 == hashlib.sha256(left.serialized.encode()).hexdigest()
    assert set(left.value["records"]) == set(TABLE_SCHEMAS)
    for table, rows in left.value["records"].items():
        assert all(list(row) == ["record_id", *TABLE_SCHEMAS[table]] for row in rows)
    assert forbidden_key_paths(left.value) == []
    assert snapshot.audit()["status"] == "PASS"
    assert not any("case_entity_records" in path for path in snapshot.opened_paths)


def test_packet_rejects_route_metadata_and_forbidden_keys() -> None:
    snapshot = OperationalSnapshot(DATA / "full")
    route = {**load_whitelisted_routes(DATA / "validation")[0], "failure_type": "F01"}
    with pytest.raises(ValueError, match="non-whitelisted"):
        CasePacketBuilder(snapshot).build(route)
    assert forbidden_key_paths({"nested": {"ml_probability": 1.0}}) == ["$.nested.ml_probability"]
    assert "failure_type" in FORBIDDEN_PACKET_KEYS


def test_primary_entity_types_are_all_supported() -> None:
    snapshot = OperationalSnapshot(DATA / "full")
    builder = CasePacketBuilder(snapshot)
    routes = load_whitelisted_routes(DATA / "validation")
    selected = {}
    for route in routes:
        selected.setdefault(route["primary_entity_type"], route)
    assert set(selected) == {"invoice", "payment", "bank_transaction", "gl_journal"}
    for route in selected.values():
        packet = builder.build(route)
        assert packet.record_count > 0
        assert route["primary_entity_id"] in packet.serialized


def test_stability_subset_is_fixed_label_blind_and_unique() -> None:
    routes = load_whitelisted_routes(DATA / "validation")
    left = select_stability_routes(routes, 32, "phase4-direct-llm-stability-v1.0")
    right = select_stability_routes(reversed(routes), 32, "phase4-direct-llm-stability-v1.0")
    assert left == right
    assert len({route["case_id"] for route in left}) == 32


def test_prompt_has_taxonomy_injection_guard_and_no_answers() -> None:
    prompt = (ROOT / "prompts/direct_llm_v1.0.txt").read_text(encoding="utf-8")
    assert all(value in prompt for value in FAILURE_TYPES)
    assert "untrusted DATA" in prompt
    assert "do not reveal chain-of-thought" in prompt
    assert "Rules/SQL" not in prompt
    assert "RCA_" not in prompt


def test_secret_audit_and_env_example() -> None:
    audit = secret_audit(ROOT)
    assert audit["status"] == "PASS"
    assert (ROOT / ".env.example").read_text(encoding="utf-8") == "OPENAI_API_KEY=\n"
