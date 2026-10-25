"""Render the frozen Phase 4 evaluation report from offline metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _table(rows: list[dict[str, Any]], fields: list[str]) -> str:
    header = "| " + " | ".join(fields) + " |"
    divider = "| " + " | ".join("---" for _ in fields) + " |"
    body = ["| " + " | ".join(str(row.get(field, "")) for field in fields) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def render_evaluation_report(result: dict[str, Any], run_dir: Path) -> str:
    metrics = result["overall"]
    evidence = result["evidence"]
    latency = result["latency"]
    tokens = result["tokens"]
    cost = result["cost"]
    weak = {row["failure_type"]: row for row in result["per_failure"]}
    complete = metrics["total_cases"] == 439
    decision = "PHASE 4 COMPLETE — DIRECT LLM BASELINE LOCKED" if complete else "PHASE 4 NOT COMPLETE"
    return f"""# Direct LLM Baseline Evaluation — Version 1.0

## 1. Executive Summary

The frozen Direct LLM baseline accounted for {metrics['total_cases']} held-out cases with {metrics['successfully_parsed_cases']} successfully parsed model decisions. Exact 16-class accuracy was {metrics['exact_16_class_accuracy']:.6f}; binary F1 was {metrics['binary_f1']:.6f}; macro F1 was {metrics['macro_f1_16_classes']:.6f}. Classification and evidence results are reported separately.

## 2. Research Question

This experiment measures reconciliation reasoning when the complete legitimate structural case packet is supplied directly, without retrieval, embeddings, RAG, GraphRAG, tools, Rules/SQL predictions, or classical-ML predictions.

## 3. Frozen Specification Provenance

See `docs/frozen_direct_llm_baseline_spec_v1.0.md`, its checksum, the preserved run manifest, and the ready pre-live audit. Held-out inference used the locked artifacts recorded in `{run_dir}`.

## 4. Model and API Configuration

The primary model was `gpt-5.6-sol` through the OpenAI Responses API, reasoning effort `medium`, verbosity `low`, strict structured output, 1,000 maximum output tokens, `store=false`, no tools, and sequential concurrency 1.

## 5. Case-Packet Construction

Packets used label-blind operational closure and unranked same-vendor peers. The ground-truth-derived repository `case_entity_records.jsonl` was not used. Packets were deterministic and untruncated.

## 6. Leakage Audit

The pre-live field/path audit passed before held-out inference. Test labels and prior baseline outputs were unavailable to the inference process.

## 7. Prompt Design

One instruction-only, evidence-first prompt was pre-registered. It includes the global F01-F15 taxonomy, data-as-data injection protection, exact evidence-ID restrictions, and concise-justification policy.

## 8. Validation-Only Prompt Selection

Not applicable: a single prompt was locked a priori and was not tuned on validation or test results.

## 9. Stability Analysis

The pre-registered 32-case, three-repetition validation stability analysis is preserved in the stability run referenced by the ready pre-live manifest. It did not alter the locked prompt/model.

## 10. Held-Out Evaluation

- Cases accounted for: {metrics['total_cases']}
- Successfully parsed: {metrics['successfully_parsed_cases']}
- INSUFFICIENT_EVIDENCE: {metrics['insufficient_evidence_count']}
- Malformed/schema-invalid: {metrics['malformed_output_count']}
- Refusals: {metrics['refusal_count']}
- API failures: {metrics['api_failure_count']}

## 11. Overall Metrics

| Metric | Value |
|---|---:|
| Exact 16-class accuracy | {metrics['exact_16_class_accuracy']:.6f} |
| Binary accuracy | {metrics['binary_accuracy_strict']:.6f} |
| Binary precision | {metrics['binary_precision']:.6f} |
| Binary recall | {metrics['binary_recall']:.6f} |
| Binary F1 | {metrics['binary_f1']:.6f} |
| Macro F1 | {metrics['macro_f1_16_classes']:.6f} |
| Micro F1 | {metrics['micro_f1_16_classes']:.6f} |
| Weighted F1 | {metrics['weighted_f1_16_classes']:.6f} |
| FPR | {metrics['false_positive_rate']:.6f} |
| FNR | {metrics['false_negative_rate']:.6f} |

## 12. Per-Failure Metrics

{_table(result['per_failure'], ['failure_type', 'N', 'precision', 'recall', 'f1', 'FP', 'FN'])}

## 13. Tier Analysis

{_table(result['tier'], ['tier', 'N', 'accuracy', 'precision', 'recall', 'f1', 'false_positive_rate', 'false_negative_rate', 'insufficient_evidence_rate', 'evidence_accuracy'])}

## 14. Hop-Count Analysis

{_table(result['hop'], ['hop_count', 'N', 'accuracy', 'precision', 'recall', 'f1', 'evidence_accuracy'])}

## 15. Evidence Accuracy

```json
{json.dumps(evidence, indent=2, sort_keys=True)}
```

## 16. Hallucinated-Evidence Analysis

The hallucinated-evidence rate was {evidence['hallucinated_evidence_rate']:.6f}. Validity, contract coverage, completeness, and ID precision/recall are separate artifacts.

## 17. Explanation Faithfulness

```json
{json.dumps(result['faithfulness'], indent=2, sort_keys=True)}
```

## 18. Insufficient-Evidence Analysis

For the exact prior Rules/SQL insufficient set:

```json
{json.dumps(result['rules_insufficient'], indent=2, sort_keys=True)}
```

## 19. Rules/SQL Comparison

```json
{json.dumps(result['rules_comparison'], indent=2, sort_keys=True)}
```

## 20. Classical ML Comparison

```json
{json.dumps(result['ml_comparison'], indent=2, sort_keys=True)}
```

## 21. Three-Way Error Intersection

```json
{json.dumps(result['three_way'], indent=2, sort_keys=True)}
```

## 22. Statistical Comparisons

```json
{json.dumps(result['statistics'], indent=2, sort_keys=True)}
```

## 23. Latency

Mean/median/p95/p99 remote request latency was {latency['mean_api_latency_ms']:.3f}/{latency['median_api_latency_ms']:.3f}/{latency['p95_api_latency_ms']:.3f}/{latency['p99_api_latency_ms']:.3f} ms. Remote API latency is not architecturally identical to local Rules/SQL (9.83 ms mean) or classical ML (70.94 ms mean).

## 24. Token Usage

Total input/output tokens were {tokens['total_input_tokens']}/{tokens['total_output_tokens']}. Mean, median, and p95 total tokens per case were {tokens['mean_total_tokens_per_case']:.2f}, {tokens['median_total_tokens_per_case']:.2f}, and {tokens['p95_total_tokens_per_case']:.2f}.

## 25. Cost

Estimated cost was USD {cost['total_estimated_cost_usd']:.6f} total and USD {cost['mean_estimated_cost_usd']:.6f} mean per case under the run-level {cost['pricing_reference_date']} pricing inputs. Raw token counts are preserved for recomputation.

## 26. API Reliability

Status and parse-state counts are `{json.dumps(metrics['status_counts'], sort_keys=True)}` and `{json.dumps(metrics['parse_status_counts'], sort_keys=True)}`. Technical failures are not silently converted into model classes.

## 27. Error Analysis

There were {result['error_count']} strict exact-label errors. Deterministic primary/secondary categories are stored in `error_analysis.csv`; deeper semantic adjudication remains separate manual review.

## 28. Known Limitations

The benchmark is synthetic; packets can be large and highly skewed; self-reported confidence is uncalibrated; one provider/model/configuration was tested; evidence contracts depend on benchmark annotations; remote latency/cost vary; and this result does not establish any RAG or GraphRAG claim.

The earlier weak deterministic classes had Direct LLM F1 values: F06 {weak['F06_INVOICE_PAID_TWICE']['f1']:.6f}, F07 {weak['F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE']['f1']:.6f}, and F11 {weak['F11_VENDOR_MASTER_CHANGE_CONFLICT']['f1']:.6f}.

## 29. Protocol Deviations

See the preserved `protocol_deviations.md` in the run directory. No undocumented valid-response regeneration or model substitution is permitted.

## 30. Reproducibility

All metrics can be recomputed offline from the preserved predictions, prepared packet artifact, test labels, and locked prior-baseline predictions. No LLM call is made by evaluation.

## 31. Conclusion

This report characterizes only reasoning under complete direct context. Retrieval-system conclusions require later experiments.

**{decision}**
"""
