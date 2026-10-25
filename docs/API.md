# Local API

Investigations may include optional `modelRequests: ModelRequestTrace[]`. Each entry describes one HTTP attempt: provider, configured/returned model, status, attempt, duration, optional HTTP status/request ID, and available token counts. No key, prompt body, or raw error body is stored. Old runs without this field remain readable. The Activity log also shows evidence-query details, approved memory content, and context-budget events. New CSV imports accept at most 1000 rows per table; shipped historical packets retain their original loader limit.

All endpoints use `/api`. The local app has no authentication and must remain bound to localhost. Types and Zod request validators are shared in `packages/contracts`.

Execution modes are `fixture` (local data and deterministic planning), `local-model` (local data and the configured real model), and `live` (PostgreSQL, Zetaris and the configured model). `/health` reports the selected provider/model and configuration presence; it does not prove connectivity. Local-model marks Zetaris as not used. CSV evidence exports include `execution_mode`, `model_provider`, and `model` before the evidence columns.

| Method and route | Contract |
|---|---|
| GET `/health` | Execution mode and configured, unverified integration status; no keys |
| GET `/datasets` | `{datasets: Dataset[]}` |
| POST `/datasets` | `{manifest, files: Record<csvFilename,string>}`; returns `{dataset}` with 201 |
| GET `/templates` | Empty valid-header CSV template bundle and manifest |
| GET `/cases?datasetId=...` | `{cases: Case[]}`; `all` aggregates review packets |
| POST `/investigations` | `{datasetId,paymentId}`; returns an existing queued/running/completed investigation for the same immutable dataset, payment, mode and memory namespace, or creates one; 202 |
| GET `/investigations/:id` | Persisted state, findings, evidence, checks, queries and events |
| GET `/investigations/:id/events` | SSE events with monotonically increasing IDs; accepts Last-Event-ID |
| POST `/investigations/:id/cancel` | Cancels queued/running work and retains the trace |
| POST `/investigations/:id/review` | `{decision:accepted|needs_changes,notes,approveMemory,memoryContent?}` |
| GET `/investigations/:id/export?format=html|json|csv` | Downloadable standalone report or evidence records |

An investigation has a lifecycle status and a separate business outcome. `failed` and `cancelled` runs have no financial outcome. Outcomes for completed runs are `anomaly_supported`, `no_anomaly_supported`, or `insufficient_evidence`.

Findings refer to evidence IDs, and evidence identifies its source table, record, dataset version and successful query ID. Empty successful queries retain coverage in their query trace; the app does not fabricate a source row to represent absence.

`actions[].verified` means the proposal's evidence basis passed the applicable verifier path. It does not approve execution, complete the listed human prerequisites, or signify that any action happened. Review is recorded separately. The UI labels these as proposal checks, not executed actions.

The frontend reconnects by persisted run ID and polls state. SSE is also exposed for other local clients. An interrupted server marks unfinished runs failed rather than restarting model work without notice.

Case responses include `investigationId` for reopening the saved result. `updateAvailable` marks a newly imported version (same dataset name and payment) with a completed result in an earlier version. Reopening, reviewing, or updating approved memory does not invalidate a completed result or call the model. A new data snapshot requires an explicit Update investigation action. Failed/cancelled attempts can be retried. Data changes are detected from imported immutable snapshots; this local mode does not watch external source files.
