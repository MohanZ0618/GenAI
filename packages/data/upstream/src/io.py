"""Stable CSV/JSONL serialization for benchmark releases."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import yaml

from src.ground_truth.causal_graph_builder import CAUSAL_EDGE_FIELDS
from src.ground_truth.rca_builder import build_evidence_index, evidence_records
from src.models import FinanceDataset
from src.schema import TABLE_SCHEMAS


def serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    return value


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: serializable(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(serializable(value), handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(serializable(row), sort_keys=True, separators=(",", ":")) + "\n")


def write_dataset(directory: Path, dataset: FinanceDataset) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for table, fields in TABLE_SCHEMAS.items():
        write_csv(directory / f"{table}.csv", dataset.rows(table), fields)


MANIFEST_FIELDS = [
    "case_id", "failure_type", "difficulty", "primary_entity_type", "primary_entity_id", "affected_systems",
    "reasoning_hops", "injected_timestamp", "root_cause_category", "split",
]


def manifest_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case["case_id"],
            "failure_type": case["failure_type"],
            "difficulty": case["difficulty"],
            "primary_entity_type": case["primary_entity"]["type"],
            "primary_entity_id": case["primary_entity"]["id"],
            "affected_systems": "|".join(case["affected_systems"]),
            "reasoning_hops": case["reasoning_hops"],
            "injected_timestamp": case["injected_timestamp"],
            "root_cause_category": case["root_cause_category"],
            "split": case["split"],
        }
        for case in cases
    ]


def write_benchmark(
    output_root: Path,
    clean: FinanceDataset,
    benchmark: FinanceDataset,
    cases: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    causal_edges: list[dict[str, str]],
    mutation_log: list[dict[str, Any]],
    quality_report: dict[str, Any],
    statistics_markdown: str,
    config: dict[str, Any],
) -> None:
    raw_dir = output_root / "raw_clean"
    benchmark_dir = output_root / "benchmark"
    write_dataset(raw_dir, clean)
    write_dataset(benchmark_dir / "full", benchmark)
    write_jsonl(benchmark_dir / "rca_ground_truth.jsonl", cases)
    write_jsonl(benchmark_dir / "benchmark_questions.jsonl", questions)
    write_csv(benchmark_dir / "causal_edges.csv", causal_edges, CAUSAL_EDGE_FIELDS)
    write_csv(benchmark_dir / "failure_manifest.csv", manifest_rows(cases), MANIFEST_FIELDS)
    write_json(benchmark_dir / "dataset_quality_report.json", quality_report)
    (benchmark_dir / "dataset_statistics.md").write_text(statistics_markdown, encoding="utf-8")
    with (benchmark_dir / "resolved_config.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(serializable(config), handle, sort_keys=True)
    write_jsonl(benchmark_dir / "internal" / "mutation_log.jsonl", mutation_log)

    evidence_index = build_evidence_index(benchmark)
    for split in ("train", "validation", "test", "challenge_test"):
        split_dir = benchmark_dir / split
        split_cases = [case for case in cases if case["split"] == split]
        split_questions = [question for question in questions if question["split"] == split]
        write_jsonl(split_dir / "rca_ground_truth.jsonl", split_cases)
        write_jsonl(split_dir / "benchmark_questions.jsonl", split_questions)
        write_csv(split_dir / "failure_manifest.csv", manifest_rows(split_cases), MANIFEST_FIELDS)
        records: list[dict[str, Any]] = []
        for case in split_cases:
            records.extend(evidence_records(benchmark, case, evidence_index))
        write_jsonl(split_dir / "case_entity_records.jsonl", records)
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "case_ids.txt").write_text("".join(f"{case['case_id']}\n" for case in split_cases), encoding="utf-8")
