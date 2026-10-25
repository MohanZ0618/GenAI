"""Specification tests for the frozen classical ML baseline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.classical_ml.data import FinancialSnapshot, load_routes
from src.classical_ml.features import FeatureExtractor, extract_frame
from src.classical_ml.modeling import build_preprocessor, candidate_configurations, feature_columns
from src.classical_ml.normalization import (
    norm_reference,
    norm_text,
    parse_date,
    parse_decimal,
    parse_ts,
    reference_similarity,
)
from src.classical_ml.registry import (
    CATEGORICAL_FEATURE_NAMES,
    FEATURES,
    NUMERIC_FEATURE_NAMES,
)


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "benchmark"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_checksums_and_registry_mirror() -> None:
    for name in ("frozen_ml_baseline_spec_v1.0", "ml_feature_registry_v1.0"):
        expected, filename = (ROOT / "docs" / f"{name}.sha256").read_text(encoding="utf-8").split()
        assert expected == _sha(ROOT / "docs" / filename)
    with (ROOT / "docs" / "ml_feature_registry_v1.0.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 147 == len(FEATURES)
    assert [row["Name"] for row in rows] == [feature.name for feature in FEATURES]
    assert [row["Feature ID"] for row in rows] == [feature.feature_id for feature in FEATURES]


@pytest.mark.parametrize(("raw", "expected"), [
    ("  café\t services  ", "CAFÉ SERVICES"),
    ("ＡＢＣ 123", "ABC 123"),
    ("", None),
    (None, None),
])
def test_frozen_text_normalization(raw: str | None, expected: str | None) -> None:
    assert norm_text(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    (" inv-00 12/a ", "INV0012A"), ("００-12", "0012"), ("---", None), (None, None),
])
def test_frozen_reference_normalization(raw: str | None, expected: str | None) -> None:
    assert norm_reference(raw) == expected


def test_numeric_date_and_similarity_boundaries() -> None:
    assert parse_decimal("001.230") == parse_decimal("1.23")
    assert parse_decimal("NaN") is None
    assert parse_date("2026-06-30").isoformat() == "2026-06-30"
    assert parse_date("06/30/2026") is None
    assert parse_ts("2026-06-30T23:59:59").date() == parse_date("2026-06-30")
    assert reference_similarity("ABC", "ABC") == 1.0
    assert reference_similarity("ABC", "ABD") == pytest.approx(2 / 3)
    assert reference_similarity(None, "ABC") is None


def test_split_case_and_vendor_group_isolation() -> None:
    case_sets: dict[str, set[str]] = {}
    for split in ("train", "validation", "test"):
        routes = load_routes(DATA / split)
        case_sets[split] = {route["case_id"] for route in routes}
    names = list(case_sets)
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            assert case_sets[left].isdisjoint(case_sets[right])
    # Vendor grouping is generator metadata, not an inference feature. Verify the
    # persisted group-aware audit without exposing group IDs to the model matrix.
    quality = json.loads((DATA / "dataset_quality_report.json").read_text(encoding="utf-8"))
    leakage = quality["train_test_leakage_checks"]
    assert leakage["passed"]
    assert not any(leakage["case_id_overlaps"].values())
    assert not any(leakage["primary_vendor_group_overlaps"].values())


def test_extractor_exact_registry_missingness_and_forbidden_access() -> None:
    snapshot = FinancialSnapshot(DATA / "full")
    routes = load_routes(DATA / "train")
    frame = extract_frame(snapshot, routes[:8])
    assert frame.columns.tolist() == ["case_id", *[feature.name for feature in FEATURES]]
    assert frame.shape == (8, 148)
    assert not frame[list(CATEGORICAL_FEATURE_NAMES)].isna().any().any()
    assert snapshot.audit()["status"] == "PASS"
    invoice = snapshot.tables["invoices"][0]
    with pytest.raises(RuntimeError, match="forbidden"):
        snapshot.get("invoices", invoice, "duplicate_reference")


def test_as_of_boundary_excludes_future_bank() -> None:
    snapshot = FinancialSnapshot(DATA / "full")
    extractor = FeatureExtractor(snapshot)
    base = dict(snapshot.tables["bank_transactions"][0])
    base["posted_date"] = "2026-06-30"
    assert extractor._eligible_bank(base)
    base["posted_date"] = "2026-07-01"
    assert not extractor._eligible_bank(base)
    base["posted_date"] = ""
    assert not extractor._eligible_bank(base)


def test_route_loader_discards_expected_answers_and_labels() -> None:
    route = load_routes(DATA / "test")[0]
    assert set(route) == {"case_id", "primary_entity_type", "primary_entity_id"}
    assert not any(token in route for token in ("expected_answer", "failure_type", "difficulty", "split"))


def test_registered_amount_and_date_differences() -> None:
    snapshot = FinancialSnapshot(DATA / "full")
    extractor = FeatureExtractor(snapshot)
    for route in load_routes(DATA / "train"):
        scope = extractor._scope(route["primary_entity_type"], route["primary_entity_id"])
        if not scope["invoices"]:
            continue
        invoice = snapshot.row("invoices", sorted(scope["invoices"])[0])
        po = snapshot.row("purchase_orders", invoice.get("po_id") if invoice else None)
        if not invoice or not po:
            continue
        result = extractor.extract(route)
        invoice_total = parse_decimal(invoice["invoice_total"])
        po_total = parse_decimal(po["po_total"])
        assert result["invoice_po_total_abs_diff"] == float(abs(invoice_total - po_total))
        assert result["days_po_to_invoice"] == float((parse_date(invoice["invoice_date"]) - parse_date(po["po_date"])).days)
        return
    pytest.fail("no linked train invoice/PO found")


def test_missing_intermediate_po_is_explicit() -> None:
    snapshot = FinancialSnapshot(DATA / "full")
    extractor = FeatureExtractor(snapshot)
    route = next(
        route for route in load_routes(DATA / "train")
        if route["primary_entity_type"].lower() == "invoice"
        and snapshot.row("invoices", route["primary_entity_id"])
        and snapshot.row("invoices", route["primary_entity_id"]).get("po_id")
    )
    invoice = snapshot.row("invoices", route["primary_entity_id"])
    po_id = invoice["po_id"]
    original = snapshot.by_id["purchase_orders"].pop(po_id)
    try:
        result = extractor.extract(route)
        assert result["missing_po"] == 1.0
        assert result["po_found"] == 0.0
        assert result["invoice_po_vendor_match"] == -1.0
    finally:
        snapshot.by_id["purchase_orders"][po_id] = original


def test_missing_vendor_entity_attribute_remains_numeric_missing() -> None:
    snapshot = FinancialSnapshot(DATA / "full")
    extractor = FeatureExtractor(snapshot)
    result = next(
        result for route in load_routes(DATA / "test")
        if (result := extractor.extract(route))["missing_vendor"] == 1.0
    )
    assert math.isnan(result["vendor_name_length"])
    assert math.isnan(result["vendor_name_token_count"])


def test_post_payment_approval_event_is_excluded() -> None:
    snapshot = FinancialSnapshot(DATA / "full")
    extractor = FeatureExtractor(snapshot)
    route, scope = next(
        (route, scope) for route in load_routes(DATA / "train")
        if route["primary_entity_type"].lower() == "payment"
        and (scope := extractor._scope(route["primary_entity_type"], route["primary_entity_id"]))["invoices"]
    )
    invoice_id = sorted(scope["invoices"])[0]
    before = extractor.extract(route)["approval_event_count"]
    future = {
        "approval_event_id": "TEST_FUTURE_APPROVAL", "invoice_id": invoice_id,
        "approver_id": "EMP_TEST", "approver_role": "CONTROLLER", "approval_level": "99",
        "action": "APPROVED", "event_timestamp": "2099-01-01T00:00:00", "comments": "",
    }
    snapshot.approvals_by_invoice[invoice_id].append(future)
    try:
        assert extractor.extract(route)["approval_event_count"] == before
    finally:
        snapshot.approvals_by_invoice[invoice_id].pop()


def test_train_fit_preprocessing_and_unseen_category_behavior() -> None:
    rows = []
    for case_id, category, value in (("A", "USD", 1.0), ("B", "EUR", np.nan), ("C", "USD", 3.0)):
        row = {"case_id": case_id}
        row.update({name: "__MISSING__" for name in CATEGORICAL_FEATURE_NAMES})
        row.update({name: np.nan for name in NUMERIC_FEATURE_NAMES})
        row["invoice_currency"] = category
        row["invoice_total"] = value
        rows.append(row)
    train = pd.DataFrame(rows)
    validation = train.iloc[[0]].copy()
    validation.loc[:, "invoice_currency"] = "ZZ_UNSEEN"
    validation.loc[:, "invoice_total"] = 999999.0
    preprocessor = build_preprocessor()
    transformed_train = preprocessor.fit_transform(feature_columns(train))
    train_mean = preprocessor.named_transformers_["numeric"].named_steps["imputer"].statistics_[0]
    transformed_validation = preprocessor.transform(feature_columns(validation))
    assert train_mean == 2.0
    assert transformed_train.shape[1] == transformed_validation.shape[1]
    encoder = preprocessor.named_transformers_["categorical"].named_steps["one_hot"]
    currency_index = list(CATEGORICAL_FEATURE_NAMES).index("invoice_currency")
    assert "ZZ_UNSEEN" not in encoder.categories_[currency_index]


def test_frozen_model_grid_has_three_families_and_22_candidates() -> None:
    configurations = candidate_configurations()
    assert len(configurations) == 22
    assert {family for _, family, _ in configurations} == {
        "logistic_regression", "random_forest", "hist_gradient_boosting",
    }
