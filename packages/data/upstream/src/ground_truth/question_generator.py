"""Generate five benchmark question styles for every case."""

from __future__ import annotations

from typing import Any


def _answer(case: dict[str, Any], style: str) -> dict[str, Any]:
    has_failure = case["failure_type"] != "NO_FAILURE"
    no_failure = "No reconciliation failure exists."
    if style == "detection":
        return {"has_reconciliation_failure": has_failure, "answer": case["observed_symptom"] if has_failure else no_failure}
    if style == "root_cause":
        return {
            "failure_type": case["failure_type"] if has_failure else "NO_FAILURE",
            "root_cause": case["root_cause"] if has_failure else no_failure,
            "root_cause_category": case["root_cause_category"],
        }
    if style == "evidence":
        return {"evidence_required": case["evidence_required"], "evidence_ids": case["evidence_ids"]}
    if style == "resolution":
        return {"expected_resolution": case["expected_resolution"]}
    return {
        "has_reconciliation_failure": has_failure,
        "failure_type": case["failure_type"],
        "root_cause": case["root_cause"] if has_failure else no_failure,
        "evidence_ids": case["evidence_ids"],
        "expected_resolution": case["expected_resolution"],
    }


def generate_questions(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for case in cases:
        entity = case["primary_entity"]
        identity = entity["id"]
        prompts = {
            "detection": f"Is there a reconciliation issue associated with {entity['type']} {identity}?",
            "root_cause": f"What is the root cause of the reconciliation result involving {identity}?",
            "evidence": f"Which records provide the decisive evidence for reconciliation case {case['case_id']}?",
            "resolution": f"What action, if any, should be taken to resolve reconciliation case {case['case_id']}?",
            "full_investigation": (
                f"Investigate reconciliation case {case['case_id']}. Identify whether a failure exists and provide "
                "the failure type, root cause, supporting evidence, and recommended resolution."
            ),
        }
        for short, (style, prompt) in enumerate(prompts.items(), 1):
            questions.append(
                {
                    "question_id": f"Q_{case['case_id'][4:]}_{short}",
                    "case_id": case["case_id"],
                    "question_style": style,
                    "question": prompt,
                    "expected_answer": _answer(case, style),
                    "primary_entity": entity,
                    "difficulty": case["difficulty"],
                    "split": case["split"],
                }
            )
    return questions

