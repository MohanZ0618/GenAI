"""Frozen preprocessing, candidate search, and model locking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from time import perf_counter_ns
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.classical_ml.registry import (
    CATEGORICAL_FEATURE_NAMES,
    CLASSES,
    MODEL_SEARCH_SPACE,
    NUMERIC_FEATURE_NAMES,
)


FAMILY_COMPLEXITY = {
    "logistic_regression": 0,
    "random_forest": 1,
    "hist_gradient_boosting": 2,
}


@dataclass
class CandidateResult:
    candidate_id: str
    model_family: str
    parameters: dict[str, Any]
    estimator: Any
    fit_seconds: float
    mean_validation_inference_latency_ns: float
    metrics: dict[str, float]
    selected: bool = False

    def serializable(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "model_family": self.model_family,
            "parameters_json": canonical_parameters(self.parameters),
            "fit_seconds": self.fit_seconds,
            "mean_validation_inference_latency_ns": self.mean_validation_inference_latency_ns,
            **self.metrics,
            "selected": self.selected,
        }


def canonical_parameters(parameters: dict[str, Any]) -> str:
    return json.dumps(parameters, sort_keys=True, separators=(",", ":"))


def build_preprocessor() -> ColumnTransformer:
    numeric = Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
    ])
    categorical = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value="__MISSING__", keep_empty_features=True)),
        ("one_hot", OneHotEncoder(handle_unknown="ignore", sparse_output=False, drop=None)),
    ])
    return ColumnTransformer(
        [("numeric", numeric, list(NUMERIC_FEATURE_NAMES)), ("categorical", categorical, list(CATEGORICAL_FEATURE_NAMES))],
        remainder="drop",
        sparse_threshold=0.0,
        verbose_feature_names_out=True,
    )


def candidate_configurations() -> list[tuple[str, str, dict[str, Any]]]:
    configurations: list[tuple[str, str, dict[str, Any]]] = []
    for family in ("logistic_regression", "random_forest", "hist_gradient_boosting"):
        definition = MODEL_SEARCH_SPACE[family]
        grid = definition["grid"]
        keys = list(grid)
        for index, values in enumerate(product(*(grid[key] for key in keys)), start=1):
            parameters = {**definition["fixed"], **dict(zip(keys, values))}
            configurations.append((f"{family}_{index:02d}", family, parameters))
    if len(configurations) != 22:
        raise AssertionError(f"frozen search must contain 22 configurations, got {len(configurations)}")
    return configurations


def construct_estimator(family: str, parameters: dict[str, Any]) -> Any:
    if family == "logistic_regression":
        return LogisticRegression(**parameters)
    if family == "random_forest":
        return RandomForestClassifier(**parameters)
    if family == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(**parameters)
    raise KeyError(family)


def score_predictions(actual: Iterable[str], predicted: Iterable[str]) -> dict[str, float]:
    actual_values = np.asarray(list(actual), dtype=object)
    predicted_values = np.asarray(list(predicted), dtype=object)
    actual_anomaly = actual_values != "NO_FAILURE"
    predicted_anomaly = predicted_values != "NO_FAILURE"
    tp = int(np.sum(actual_anomaly & predicted_anomaly))
    fp = int(np.sum(~actual_anomaly & predicted_anomaly))
    fn = int(np.sum(actual_anomaly & ~predicted_anomaly))
    tn = int(np.sum(~actual_anomaly & ~predicted_anomaly))
    binary_precision, binary_recall, binary_f1, _ = precision_recall_fscore_support(
        actual_anomaly, predicted_anomaly, average="binary", zero_division=0,
    )
    return {
        "exact_accuracy": float(accuracy_score(actual_values, predicted_values)),
        "macro_f1": float(f1_score(actual_values, predicted_values, labels=list(CLASSES), average="macro", zero_division=0)),
        "micro_f1": float(f1_score(actual_values, predicted_values, labels=list(CLASSES), average="micro", zero_division=0)),
        "weighted_f1": float(f1_score(actual_values, predicted_values, labels=list(CLASSES), average="weighted", zero_division=0)),
        "binary_accuracy": float((tp + tn) / len(actual_values)),
        "binary_precision": float(binary_precision),
        "binary_recall": float(binary_recall),
        "binary_f1": float(binary_f1),
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "false_negative_rate": float(fn / (fn + tp)) if fn + tp else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def run_validation_search(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_validation: np.ndarray,
    y_validation: np.ndarray,
) -> tuple[CandidateResult, list[CandidateResult]]:
    results: list[CandidateResult] = []
    for candidate_id, family, parameters in candidate_configurations():
        estimator = construct_estimator(family, parameters)
        started = perf_counter_ns()
        estimator.fit(x_train, y_train)
        fit_seconds = (perf_counter_ns() - started) / 1e9
        # Warm the estimator once; the timed call still covers the complete validation batch.
        estimator.predict(x_validation[:1])
        started = perf_counter_ns()
        predicted = estimator.predict(x_validation)
        latency = (perf_counter_ns() - started) / len(y_validation)
        results.append(CandidateResult(
            candidate_id=candidate_id,
            model_family=family,
            parameters=parameters,
            estimator=estimator,
            fit_seconds=fit_seconds,
            mean_validation_inference_latency_ns=float(latency),
            metrics=score_predictions(y_validation, predicted),
        ))
    ranked = sorted(results, key=lambda result: (
        -result.metrics["macro_f1"],
        -result.metrics["weighted_f1"],
        result.metrics["false_positive_rate"],
        result.mean_validation_inference_latency_ns,
        FAMILY_COMPLEXITY[result.model_family],
        canonical_parameters(result.parameters),
    ))
    ranked[0].selected = True
    return ranked[0], results


def feature_columns(frame: pd.DataFrame) -> pd.DataFrame:
    expected = list(CATEGORICAL_FEATURE_NAMES) + list(NUMERIC_FEATURE_NAMES)
    # ColumnTransformer uses its own frozen numeric/categorical order; this check guards content.
    if set(frame.columns) != {"case_id", *expected}:
        raise ValueError("feature frame does not equal frozen registry")
    return frame.drop(columns=["case_id"])
