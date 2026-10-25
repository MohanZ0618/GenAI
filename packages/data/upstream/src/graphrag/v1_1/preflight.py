"""Gold-blind compatibility audit for frozen Graph v1 ranking semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .typed_grammar_loader import FrozenGrammarBundle


@dataclass(frozen=True)
class RankingCompatibility:
    status: str
    selection_implementation_authorized: bool
    gold_evaluation_authorized: bool
    findings: tuple[dict[str, Any], ...]
    blocking_decision: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selection_implementation_authorized": self.selection_implementation_authorized,
            "gold_evaluation_authorized": self.gold_evaluation_authorized,
            "findings": list(self.findings),
            "blocking_decision": self.blocking_decision,
        }


def assess_ranking_compatibility(bundle: FrozenGrammarBundle) -> RankingCompatibility:
    ranking = bundle.ranking
    grammar = bundle.grammar
    framework = grammar["candidate_path_priority_framework_for_future_review"]
    clear = [
        {
            "requirement": "exact anchor priority",
            "status": "SPECIFIED",
            "evidence": "Frozen v1 priority 1 is exact anchor.",
        },
        {
            "requirement": "record budget",
            "status": "SPECIFIED",
            "evidence": "Frozen v1 maximum_raw_source_records is 40 and applies after traversal.",
        },
        {
            "requirement": "record deduplication and path provenance",
            "status": "SPECIFIED",
            "evidence": "Graph v1.1 freezes case_id+record_id deduplication and preservation of sorted supporting path IDs.",
        },
        {
            "requirement": "disabled future methods",
            "status": "SPECIFIED",
            "evidence": "Tier B, semantic fallback, embeddings, learned ranking, and generic BFS remain disabled.",
        },
    ]
    ambiguous = [
        {
            "requirement": "BACKBONE priority",
            "status": "AMBIGUOUS",
            "evidence": "The v1 policy distinguishes direct Tier A from complete Tier A multi-hop, but it does not map Graph v1.1 BACKBONE prefixes and complete lifecycle paths to those classes.",
        },
        {
            "requirement": "SUPPORTING handling",
            "status": "AMBIGUOUS",
            "evidence": "The frozen v1 policy has no SUPPORTING transition class and does not decide whether the direct Payment↔Invoice projection ranks as direct Tier A or below a provenance-complete allocation path.",
        },
        {
            "requirement": "CONTEXT and TERMINAL_CONTEXT handling",
            "status": "AMBIGUOUS",
            "evidence": "Approved event/audit context is priority 5, but mixed context-anchor-exit plus lifecycle paths and terminal-context prefixes have no frozen class-assignment rule.",
        },
        {
            "requirement": "complete multi-hop path admission",
            "status": "AMBIGUOUS",
            "evidence": "The policy does not define which emitted prefixes constitute a complete path or whether selecting a path requires admitting every record on that path.",
        },
        {
            "requirement": "tie breaking over typed paths",
            "status": "AMBIGUOUS",
            "evidence": "Fewer hops, relation order, and canonical record_id are listed, but no frozen rule defines canonical-record ordering for multiple roots, multi-record paths, or equal-priority paths sharing endpoints.",
        },
        {
            "requirement": "more-than-40 path/record competition",
            "status": "AMBIGUOUS",
            "evidence": "The registry forbids silent truncation but does not freeze whole-path admission, partial-path admission, or skip/fill behavior when the next ranked path exceeds the remaining record budget.",
        },
    ]
    explicit_future_review = (
        framework.get("implemented") is False
        and "future review" in framework.get("note", "").lower()
        and grammar["multiplicity_and_budget_policy"].get("source_record_selection_implemented_here") is False
    )
    if not explicit_future_review:
        ambiguous.append({
            "requirement": "v1.1 selection authorization",
            "status": "AMBIGUOUS",
            "evidence": "Graph v1.1 does not contain an affirmative executable-selection freeze.",
        })
    if ranking.get("trained_reranker") or ranking.get("scoring_weights") is not None:
        raise RuntimeError("Frozen ranking registry unexpectedly enables learned or weighted selection")
    decision = "BLOCKED — GRAPH v1.1 EVIDENCE-SELECTION POLICY REQUIRES SEPARATE FREEZE"
    return RankingCompatibility(
        status="BLOCKED_AMBIGUOUS",
        selection_implementation_authorized=False,
        gold_evaluation_authorized=False,
        findings=tuple([*clear, *ambiguous]),
        blocking_decision=decision,
    )


class EvidenceSelectionBlocked(RuntimeError):
    pass


def select_top40(*_: Any, **__: Any) -> None:
    """Fail closed: no Graph v1.1 selector exists without a separate freeze."""
    raise EvidenceSelectionBlocked(
        "BLOCKED — GRAPH v1.1 EVIDENCE-SELECTION POLICY REQUIRES SEPARATE FREEZE"
    )
