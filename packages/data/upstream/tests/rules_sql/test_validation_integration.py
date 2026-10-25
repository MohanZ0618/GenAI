from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from src.rules_sql.engine import F01Parameters
from src.rules_sql.evaluation import run_inference
from src.rules_sql.registry import RULES


@pytest.fixture(scope="module")
def validation_run() -> tuple[list[dict], dict[str, str]]:
    predictions, _, _ = run_inference(
        Path("data/benchmark/full"),
        Path("data/benchmark/validation"),
        F01Parameters(),
    )
    with Path("data/benchmark/validation/failure_manifest.csv").open("r", encoding="utf-8", newline="") as handle:
        labels = {row["case_id"]: row["failure_type"] for row in csv.DictReader(handle)}
    return predictions, labels


def test_clear_positive_for_every_frozen_rule(validation_run) -> None:
    predictions, labels = validation_run
    correct = {
        labels[row["case_id"]]
        for row in predictions
        if row["predicted_failure_type"] == labels[row["case_id"]]
    }
    assert {rule.failure_type for rule in RULES} <= correct


def test_clear_negative_match_for_every_frozen_rule(validation_run) -> None:
    predictions, labels = validation_run
    matched_rules = {
        trace["rule_id"]
        for row in predictions
        if labels[row["case_id"]] == "NO_FAILURE"
        for trace in row["rule_traces"]
        if trace["status"] == "MATCH"
    }
    assert {rule.rule_id for rule in RULES} <= matched_rules


def test_all_selected_anomaly_evidence_contracts_pass(validation_run) -> None:
    predictions, _ = validation_run
    for row in predictions:
        if row["status"] != "ANOMALY":
            continue
        selected = next(trace for trace in row["rule_traces"] if trace["rule_id"] == row["triggered_rule_id"])
        assert selected["evidence_contract_pass"], row["case_id"]


def test_tier3_join_paths_and_evidence_propagation(validation_run) -> None:
    predictions, labels = validation_run
    tier3 = {rule.failure_type: rule for rule in RULES if rule.tier == 3}
    seen = defaultdict(int)
    for row in predictions:
        actual = labels[row["case_id"]]
        if actual in tier3 and row["predicted_failure_type"] == actual:
            seen[actual] += 1
            assert row["hop_count"] == tier3[actual].hop_count
            assert row["evidence_record_ids"]
    assert set(seen) == set(tier3)


def test_frozen_collision_precedence_f03_over_f02_and_f15_over_f14(validation_run) -> None:
    predictions, labels = validation_run
    f03 = next(row for row in predictions if labels[row["case_id"]] == "F03_QUANTITY_MISMATCH" and "RSQL_F02_V1" in row["collision"]["all_triggered_rules"])
    assert f03["triggered_rule_id"] == "RSQL_F03_V1"
    f15 = next(row for row in predictions if labels[row["case_id"]] == "F15_INCORRECT_PAYMENT_BANK_MATCH" and "RSQL_F14_V1" in row["collision"]["all_triggered_rules"])
    assert f15["triggered_rule_id"] == "RSQL_F15_V1"
    assert f03["collision"]["matches_frozen_precedence"]
    assert f15["collision"]["matches_frozen_precedence"]
