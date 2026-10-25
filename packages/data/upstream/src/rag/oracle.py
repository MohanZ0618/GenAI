"""Physically separate evaluation-only Oracle Evidence Context Diagnostic support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from src.rag.corpus import FrozenCorpus
from src.rag.evidence import resolve_evidence
from src.rag.reasoner import ReasoningCase, build_reasoning_case


@dataclass(frozen=True)
class OracleCase:
    reasoning_case: ReasoningCase
    required_record_ids: tuple[str, ...]
    absence_only_tables: tuple[str, ...]


def build_oracle_cases(
    routes: Sequence[dict[str, str]],
    truth: Sequence[dict[str, Any]],
    corpus: FrozenCorpus,
) -> list[OracleCase]:
    """Resolve G_i after primary immutability and expose only exact operational documents."""
    route_by_id = {str(row["case_id"]): row for row in routes}
    truth_by_id = {str(row["case_id"]): row for row in truth}
    if set(route_by_id) != set(truth_by_id):
        raise RuntimeError("oracle routes and ground-truth case IDs disagree")
    document_by_id = corpus.by_record_id()
    output = []
    for case_id in route_by_id:
        evidence = resolve_evidence(truth_by_id[case_id], corpus.documents)
        ids = tuple(sorted(evidence.required_record_ids))
        if not ids:
            raise RuntimeError(f"oracle G_i has no observable document: {case_id}")
        context = build_reasoning_case(
            route_by_id[case_id], ids, [document_by_id[value].text for value in ids]
        )
        output.append(OracleCase(context, ids, tuple(sorted(evidence.absence_only_tables))))
    return output
