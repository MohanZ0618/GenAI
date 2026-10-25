"""Isolated label-discarding route preparation for primary RAG inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.rag.artifacts import sha256_file, write_json, write_jsonl
from src.rag.leakage import OpenedPathAudit, assert_route


Route = dict[str, str]


def prepare_routes(split_dir: Path, output_path: Path) -> tuple[list[Route], dict[str, Any]]:
    audit = OpenedPathAudit("route_preparation")
    questions_path = split_dir / "benchmark_questions.jsonl"
    case_ids_path = split_dir / "case_ids.txt"
    audit.record(questions_path)
    audit.record(case_ids_path)
    routes: dict[str, Route] = {}
    discarded_top: set[str] = set()
    discarded_primary: set[str] = set()
    with questions_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            discarded_top.update(set(raw) - {"case_id", "primary_entity"})
            primary = raw.get("primary_entity", {})
            discarded_primary.update(set(primary) - {"type", "id"})
            route = {
                "case_id": str(raw["case_id"]),
                "primary_entity_type": str(primary["type"]),
                "primary_entity_id": str(primary["id"]),
            }
            assert_route(route)
            prior = routes.setdefault(route["case_id"], route)
            if prior != route:
                raise RuntimeError(f"inconsistent route across benchmark questions: {route['case_id']}")
    ordered_ids = [line.strip() for line in case_ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(routes):
        raise RuntimeError("case_ids and prepared question routes disagree")
    ordered = [routes[case_id] for case_id in ordered_ids]
    write_jsonl(output_path, ordered, exclusive=True)
    route_audit = {
        "status": "PASS",
        "route_count": len(ordered),
        "permitted_output_keys": ["case_id", "primary_entity_type", "primary_entity_id"],
        "discarded_question_keys": sorted(discarded_top),
        "discarded_primary_entity_keys": sorted(discarded_primary),
        "output_path": str(output_path.resolve()),
        "output_sha256": sha256_file(output_path),
        "opened_path_audit": audit.serializable(),
        "primary_runner_may_reopen_question_source": False,
    }
    write_json(output_path.with_suffix(".audit.json"), route_audit, exclusive=True)
    return ordered, route_audit


def load_routes(path: Path, audit: OpenedPathAudit | None = None) -> list[Route]:
    if audit:
        audit.record(path)
    rows: list[Route] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            route = {key: str(value) for key, value in json.loads(line).items()}
            assert_route(route)
            rows.append(route)
    if len({row["case_id"] for row in rows}) != len(rows):
        raise RuntimeError("duplicate case IDs in route artifact")
    return rows

