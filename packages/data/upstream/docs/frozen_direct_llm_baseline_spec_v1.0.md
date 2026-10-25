# Frozen Direct LLM Baseline Specification — Version 1.0

## 1. Status and scientific objective

This document freezes Phase 4 before any Direct LLM API inference. The baseline isolates model reasoning from retrieval: one model receives one deterministic, label-blind packet containing the complete frozen operational scope for one reconciliation case and returns one structured decision. There is no semantic retrieval, embedding, vector database, RAG, GraphRAG, graph search, web/file search, SQL lookup initiated by the model, function/tool call, agent loop, Rules/SQL output, or classical-ML output.

The primary question is: when all legitimately available case evidence is provided directly, how accurately can an LLM classify reconciliation outcomes and identify source evidence? Phase 4 makes no claim about RAG or GraphRAG.

Prior baselines remain immutable. The authoritative Rules/SQL run is `phase2_rules_sql_v1_0_20260808T185000Z_auditfix1`; its frozen specification SHA-256 is `0ee3192dd760dd2521791ef46543c9c7337cc6d8eff0f3cd4a7cba9e5d645675`. The authoritative corrected classical-ML run is `phase3_classical_ml_v1_0_20260808T213000Z_auditfix1`; its frozen specification SHA-256 is `0d220564335a85e6fe3a193e212d68aec2abbf7744a23f267ba4390b428d6897`.

## 2. Evaluation unit, routing, and decision time

The evaluation unit is one benchmark case. The only harness routing fields are `case_id`, `primary_entity_type`, and `primary_entity_id`, taken from the benchmark question and whitelisted exactly as in the locked earlier baselines. The primary entity is legitimate case-routing metadata, not evidence or a target.

The delivered model-visible snapshot is `data/benchmark/full`, and the frozen analytical cutoff is `2026-06-30`. The packet uses the delivered snapshot rather than treating future business dates as ingestion timestamps. Operational `audit_log.timestamp` is a genuine event timestamp and events after the cutoff are excluded. No unavailable historical snapshot is invented.

The route preparation boundary discards every question key except the three routing values and writes an unlabeled route artifact. The paid inference process reads prepared packet artifacts and does not open `benchmark_questions.jsonl`, `failure_manifest.csv`, `rca_ground_truth.jsonl`, or any other test-label artifact.

## 3. Frozen case-packet construction

- Packet version: `direct_llm_case_packet_v1.0`.
- Executable builder: `src/direct_llm/packet.py`.
- Serialization: compact UTF-8 JSON with deterministic table, field, and row order.
- Table order and field order: insertion order in `src/schema.py::TABLE_SCHEMAS`.
- Row order: lexical tuple of the canonical primary-key fields in `src/schema.py::PRIMARY_KEYS`.
- Source-record identifier: `table_name:primary_key`; composite keys join components with `|`.
- Empty sections: retained for all 14 operational tables so absence within the frozen scope is explicit.
- Truncation: prohibited.

The builder first computes an exact, bidirectional core closure from the routed primary entity:

1. `invoice -> payment_allocations -> payment` and the inverse relationship;
2. `payment.reference_number <-> bank_transaction.payment_reference` after the benchmark's fixed reference normalization;
3. `gl_journal -> gl_entries -> source_transaction_id` according to operational transaction type;
4. the closure iterates to a fixed point and fails if it does not converge.

The core establishes linked purchase orders and operational vendor IDs. The builder then includes every same-vendor invoice, payment, and bank-counterparty peer without ranking, similarity, anomaly thresholds, labels, or annotated evidence. These unranked peer sets are necessary for duplicate and cross-match evaluation and their legitimate hard negatives. Peers do not recursively expand into unrelated journals or workflows. For the resulting frozen scope the packet includes:

- vendor rows and vendor change history;
- invoice headers, every invoice line, and approval events;
- linked PO headers and every PO line;
- payment headers and every allocation for included payments;
- exact core-source GL journals/lines and exact core bank-fee sources;
- structurally linked and same-counterparty bank transactions;
- bank statements for included company bank accounts;
- operational audit events attached to included identifiers through the cutoff;
- employee records referenced by included PO, approval, change, or audit records.

No record is selected because it resembles a query, supports a label, was cited by ground truth, or was returned by another baseline. In particular, the repository's `case_entity_records.jsonl` is forbidden because the authoritative generator constructed it from ground-truth `evidence_ids` and `evidence_required`; using it would create an oracle-retrieval condition.

## 4. Permitted and forbidden input

Permitted fields are the canonical operational fields of `vendors`, `vendor_change_log`, `purchase_orders`, `po_lines`, `invoices`, `invoice_lines`, `approval_events`, `payments`, `payment_allocations`, `gl_entries`, `bank_transactions`, `bank_statements`, `employees`, and `audit_log` in `src/schema.py`, plus the derived stable `record_id`, packet metadata, the three routing values, and `decision_as_of_date`.

Forbidden artifacts and fields include ground-truth labels, failure manifests, expected answers, expected failure type, anomaly flags, ground-truth evidence IDs/tables, root causes, expected resolution, difficulty/tier/hop/split metadata, causal edges, mutation logs, clean pre-mutation data, correctness/adjudication fields, failure signatures, dataset quality reports, Rules/SQL statuses/rules/reasons/predictions/traces/evidence, classical-ML predictions/probabilities/features, and any target-derived proxy. `case_entity_records.jsonl` is forbidden even though its row payloads are operational, because its selection policy is ground-truth-derived.

The packet builder accepts only the three whitelisted route keys and only opens the 14 `full/*.csv` operational files. The packet leakage audit enumerates all fields separately in `docs/direct_llm_case_packet_leakage_audit_v1.0.md`.

## 5. Prompt and prompt development

- Frozen prompt version: `direct_llm_v1.0`.
- Frozen prompt artifact: `prompts/direct_llm_v1.0.txt`.
- Prompt SHA-256: `e4fb908829f412eb0a3015a4d05f29c0603b12cac84ade166aff92b76c78278c`.
- Prompt style: instruction-only, evidence-first; no demonstrations.

One prompt was pre-registered a priori. Therefore validation prompt selection is `NOT APPLICABLE — SINGLE PROMPT LOCKED BEFORE API USE`; there is no held-out or validation-driven wording choice. This avoids exemplar and candidate-selection confounds. The prompt contains the concise canonical definitions for `NO_FAILURE` and F01-F15, evidence restrictions, abstention behavior, and output contract.

Financial text is untrusted data. The prompt explicitly requires the model to ignore instruction-like content inside any record field and to follow only experiment-level instructions. Source data is not sanitized or rewritten merely because it resembles an instruction.

The model is asked for only a concise, auditable justification, not private chain-of-thought. It internally checks evidence before committing but returns only the final structured result.

## 6. Frozen model and provider configuration

| Setting | Frozen value |
|---|---|
| Provider | OpenAI |
| API | Responses API through official Python SDK |
| Model ID | `gpt-5.6-sol` |
| Model alias substitution | prohibited |
| Reasoning effort | `medium` |
| Temperature | NOT SUPPORTED / NOT SET |
| Top-p | NOT SUPPORTED / NOT SET |
| Maximum output tokens | 1,000 |
| Verbosity | `low` |
| Structured output | strict Pydantic/JSON Schema |
| Store | `false` |
| Truncation | `disabled` |
| Service tier | `default` |
| Tools | omitted; none |
| Concurrency | 1, fixed for the complete primary run |
| Request timeout | 120 seconds |
| Context window | 1,050,000 tokens |

`gpt-5.6-sol` is the exact documented model ID rather than the `gpt-5.6` alias. If it is unavailable, the runner fails; it must not substitute another model. The returned model identifier and execution timestamp are recorded for every response. The official model page and structured-output guide used at freeze time are <https://developers.openai.com/api/docs/models/gpt-5.6-sol> and <https://developers.openai.com/api/docs/guides/structured-outputs>.

## 7. Structured output schema

- Schema version: `direct_llm_output_schema_v1.0`.
- Executable schema: `src/direct_llm/output.py::DirectLLMPrediction`.

Required fields are `case_id`, `status`, `is_anomaly`, `predicted_failure_type`, `evidence_record_ids`, `reason`, and `confidence`. Extra properties are forbidden. Confidence is a number in `[0,1]` and means only self-reported confidence in the final class; it is not assumed calibrated.

- `MATCH` requires `is_anomaly=false` and `predicted_failure_type=NO_FAILURE`.
- `ANOMALY` requires `is_anomaly=true`, exactly one canonical F01-F15 label, and at least one evidence ID.
- `INSUFFICIENT_EVIDENCE` requires null anomaly and failure fields.

Response `case_id` must equal the request case. Evidence IDs must be unique and must exactly match `record_id` values in the supplied packet. An invented ID is a hallucinated-evidence error and makes the valid API response terminally schema-invalid; it is not regenerated.

## 8. API client, request identity, and raw preservation

Each request contains only the frozen instructions and taxonomy, the deterministic packet, and the strict response schema. No tool declaration is sent. `store=false` is set.

The request SHA-256 covers the prompt version, complete frozen model/configuration dictionary, exact serialized packet, schema version, and canonical JSON schema. It never includes a credential. A resume refuses any case whose stored request hash differs.

For every received response the append-only raw ledger stores case ID, request hash, response ID, returned model, UTC timestamp, raw structured response, raw output text if any, refusal if any, usage details, latency, and attempt number. The parsed prediction is stored separately. Successful or valid-but-malformed/refused responses are terminal and never rerun for a different answer.

## 9. Retry, malformed-response, refusal, and API-error policy

- Retry policy version: `direct_llm_retry_v1.0`.
- Maximum attempts: 4 total.
- Backoff after retryable attempts: fixed 1, 2, and 4 seconds.
- Retryable: timeout, connection interruption, rate limit, HTTP 408/409/429, and HTTP 5xx.
- Permanent: authentication, permission, invalid request, unsupported model/configuration, and other non-transient API failures.
- No SDK-internal retry: the harness owns and records every retry.

Malformed JSON, schema inconsistency, wrong case ID, hallucinated evidence, refusal, low confidence, weak reasoning, or an apparently wrong class does not trigger regeneration. Technical failures remain technical outcomes and are reported separately. An interrupted run resumes only cases without a terminal ledger state and preserves the cumulative attempt count.

## 10. Live-run and credential safety

The default `prepare` command performs no external API call. API use requires the literal `--execute-api` flag and `OPENAI_API_KEY` in the process environment. Before the first request the CLI prints the model, case count, specification and prompt checksums, packet version, credential-presence boolean, output directory, and held-out status. The key value is never printed, hashed, persisted, or passed into a manifest.

`.env.example` contains only `OPENAI_API_KEY=`. `.env` and `.env.*` are ignored except `.env.example`. The harness does not create a real `.env`.

## 11. Context-size policy

All 439 test packets are serialized before live inference. The frozen preflight estimate is `ceil(total Unicode characters / 3)` over prompt, canonical schema, and packet. This conservative, provider-independent estimate is not a billing count. Every request plus 1,000 reserved output tokens must fit the 1,050,000-token context. Exact API-reported input tokens remain the primary post-run artifact.

No packet is truncated. On overflow, the run stops. Any deterministic compaction amendment must remain label-blind, preserve all records under its new policy, receive a new packet version and specification amendment, regenerate every packet, and rerun preflight. Semantic retrieval is prohibited.

## 12. Validation-only stability protocol

Stability is measured before held-out inference on 32 validation cases. The subset is fixed without labels by sorting SHA-256 of `phase4-direct-llm-stability-v1.0|case_id` and selecting the first 32. The exact frozen request is executed three times per selected validation case. This deliberate repeated-validation protocol does not permit changing the prompt/model.

Report exact structured-class agreement, class disagreement, exact evidence-list agreement and pairwise evidence Jaccard, and confidence mean/standard deviation/range. Raw responses and token/cost/latency data are preserved. No held-out case is repeated except documented transport retries.

## 13. Pre-live locking and authorization

Before held-out inference, the harness verifies the specification and prompt checksums, packet-builder source checksum, 439 test packet hashes, leakage audit, context audit, route/label isolation, schema tests, retry/resume/mock tests, secret audit, and completed stability report. It then writes the selected configuration and hashes to a pre-live manifest and the required audit document.

Held-out execution is unauthorized unless the audit decision is exactly `PHASE 4 READY FOR LIVE RUN`. Specification, prompt, model configuration, schema, packet version, retry policy, concurrency, and pricing inputs may not change after the first held-out request.

## 14. Inference/evaluation separation

The inference process reads only prepared unlabeled packets, the prompt/schema/configuration, and the ready pre-live manifest. It writes request ledgers, raw responses, and predictions. It does not open test labels, ground truth, Rules/SQL results, or ML results.

The offline evaluator runs only after inference artifacts exist. It may then read test labels/metadata and locked baseline predictions. It never calls an LLM.

## 15. Evaluation metrics and strict failure treatment

Primary metrics over all 439 cases are exact 16-class accuracy; binary anomaly accuracy, precision, recall, and F1; macro, micro, and weighted F1; FPR; and FNR. Report the confusion matrix, per-class support, output-state counts, insufficient evidence, malformed output, refusal, and API failure. Technical/unparsed outcomes are incorrect in strict end-to-end accuracy and remain separately identified; model-only metrics are also reported for successfully parsed cases.

Report per F01-F15 precision/recall/F1/FP/FN, explicitly including F06/F07/F11. Tier is the frozen Rules registry tier associated with the actual failure type, and hop count is the exact benchmark ground-truth annotation; neither is sent to the model. No-failure cases are excluded from failure-tier tables, matching earlier baseline convention.

Evidence evaluation separates:

- validity: every cited ID occurs in the packet;
- contract correctness: cited rows cover every ground-truth-required table that has an observable annotated record and are packet-valid;
- completeness: every annotated evidence identifier is represented by the cited rows under canonical identifier fields;
- hallucination rate;
- correct class with incorrect/incomplete evidence;
- fully evidence-grounded reconciliation: correct class plus contract-correct complete evidence.

Explanation faithfulness uses deterministic packet checks for record IDs, ID-like values, decimal amounts, and ISO dates. Unsupported assertions requiring judgment are flagged for separate manual review; no second LLM is the sole primary judge.

The exact 50 Rules/SQL insufficient cases are reported separately. Classification recovery and evidence-grounded resolution are distinct. Complete case-level exact and binary partitions are produced versus Rules/SQL and classical ML, plus the eight-way three-method correctness intersection. Exact paired McNemar tests and deterministic paired bootstrap confidence intervals are reported for major metric differences without subgroup significance overclaiming.

## 16. Latency, token, reliability, and cost accounting

Per case measure end-to-end remote request latency and local parsing/serialization overhead where available. Report mean, median, p95, p99, min, max, sequential throughput, retry/failure rates, and architectural caveats versus local baselines.

Record API-reported input, output, cached input, cache-write, and reasoning tokens where present. Pricing is a run-level manifest input, not embedded in evaluator logic. Frozen initial pricing reference dated 2026-08-08 for `gpt-5.6-sol` is USD 5.00 per million input tokens, USD 0.50 per million cached-input tokens, and USD 30.00 per million output tokens. Raw counts permit recomputation if pricing changes.

## 17. Pre-registered hypotheses

- LLM-H1: complete legitimate context will permit strong reconciliation classification without retrieval.
- LLM-H2: relational performance may remain strong at Tier 2/3 when related records are explicit.
- LLM-H3: the model can identify explicit source evidence more effectively than evidence-free classical ML.
- LLM-H4: unsupported values, relationships, or IDs may still occur and must be measured separately.
- LLM-H5: incomplete source data may cause appropriate abstention or unsupported statistical inference; only evidence-grounded correctness resolves a case.
- LLM-H6: remote Direct LLM inference will likely cost more and take longer than local frozen baselines.
- LLM-H7: error intersections may reveal complementarity; no hybrid is built in Phase 4.

## 18. Protocol deviations and immutability

Any post-start change is documented in `protocol_deviations.md`. If an implementation defect violates this specification, preserve the original run, prove the violation, create a new run ID, correct only the defect, and preserve both runs. Prompt optimization, model substitution, or retrying an unfavorable valid answer is not a bug fix.

Run directories are immutable by ID. The primary held-out run ID is `phase4_direct_llm_v1_0_<UTC timestamp>`. Raw responses and successful predictions are append-only and are never overwritten.

## 19. Reproduction commands

No-cost preflight:

```bash
python3 -m src.direct_llm.cli prepare --data-root data/benchmark --output-root results/direct_llm --run-id phase4_direct_llm_preflight_v1_0_<timestamp>
```

Validation-only stability (paid API calls; explicit authorization):

```bash
python3 -m src.direct_llm.cli stability --preflight-dir results/direct_llm/<preflight_run_id> --output-root results/direct_llm --run-id phase4_direct_llm_stability_v1_0_<timestamp> --execute-api
```

Final readiness audit, held-out inference, and offline evaluation commands are documented by the CLI help and repository README. The held-out command requires both the ready audit and `--execute-api`.

## 20. Freeze declaration

This specification, the prompt, output schema, case-packet policy, model configuration, retry policy, concurrency, stability protocol, evaluation protocol, and initial pricing inputs are frozen before API use. Held-out inference has not occurred at specification freeze time.
