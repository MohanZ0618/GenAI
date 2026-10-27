# Submission preparation validation

Date: 27 October 2026. This record distinguishes successive preparation passes, the current complete Nightshift live acceptance and earlier experiments.

## Earlier submission preparation pass

The Nightshift adapter now supplies an explicit JSON output contract in its system prompts while retaining local validation. Submission preflight rejects fixture/local-model profiles and direct model providers before contacting services. Model preflight reports the returned model when supplied. No business outcome logic was changed.

| Check | Result |
|---|---|
| Focused provider, preflight and regression tests | 56/56 passed, including eight new Nightshift/submission tests; all model calls mocked |
| Full unit/API regression | 172/172 passed across 15 test files; fixture/mock execution |
| TypeScript checks | `npm run typecheck` passed |
| Production build | `npm run build` passed |
| H-MEM reference conformance | 13/13 passed |
| Application H-MEM fixture acceptance | 12/12 comparisons passed; lifecycle checks passed |
| Browser regression | 59/70 passed; 11 failures detailed below |
| Release allowlist and local links | 367 files checked; no missing or unsafe manifest paths, broken submission-document links, tracked source omissions or matches in the bounded credential/host-identifier scan |
| Fresh allowlisted source copy | `npm ci --offline --no-audit --no-fund`, `npm run typecheck` and `npm run build` passed |
| Source ZIP | Built from the allowlist only; dependencies, build output, runtime reports, credentials and Git history are excluded |
| Real Nightshift/OpenAI route | Not run in this earlier pass; later Google/Nightshift acceptance is recorded below |
| Full live Zetaris + Nightshift investigation | Not run in this earlier pass; completed in the later acceptance below |
| Public GitHub, final slides, video and HackOS | Team actions pending |

An HTTP/JSON trace marked succeeded reports transport/JSON parsing; operation-level schema and citation checks must also pass. A returned model name is provider-reported metadata. Confirm the actual route/model with Nightshift activity rather than assuming a routing alias is the underlying model.

## Local Nightshift preparation follow-up — 27 October 2026

- Installed and started the official Nightshift M1-M4 0.92.7 application on Apple M4. `/healthz` responded and authenticated `/v1/models` returned 14 routing IDs. This confirms endpoint availability and authentication, not successful model inference.
- A subsequent real preflight reached Nightshift after the user saved an OpenAI key. The Runtime's explanation identified OpenAI `429` / `insufficient_quota`; no route completed, so no successful Nightshift inference is claimed. Additional inference requests were stopped pending usable API credit.
- Added the required `meterless-app: fintrace` and `meterless-scope: user` chat headers; Nightshift requests and model preflight allow 180 seconds for cold loads. Other providers retain their existing timeout and headers.
- Full unit/API checks passed 174/174 across 15 files, including 10 mocked Nightshift/submission checks. TypeScript checks and the production build passed.
- Repeated H-MEM reference conformance: 13/13 passed. Application fixture acceptance: 12/12 comparisons and persistence/approval/deactivation checks passed in isolated storage with scripted synthetic reviewer actions.
- Prepared an isolated local PostgreSQL 17.5 instance with three application schemas, nine source views and 70 built-in synthetic datasets. A dedicated read-only Zetaris connector login could query all nine source views; a separate test container could reach the database. The existing unrelated database was not changed.
- The initial cloud attempt remained blocked by API credit. Subsequent local Runtime diagnostics produced real completions and exact decision/explanation correlations, but two fresh normal investigations stopped before gathering required evidence and correctly retained `insufficient_evidence`. The user stopped that route and its model/cache was removed to Trash; empty cached/resident lists were verified after restart. The later Google/Nightshift acceptance below resolves the technical workflow that was still pending at this stage. Direct Zetaris/DeepSeek results remain separate.

## Complete Nightshift + Google + Zetaris live acceptance — 27 October 2026

The complete fresh synthetic run passed using the official Nightshift M1-M4 0.92.7 Runtime, Google `gemini-3.5-flash-lite`, PostgreSQL persistence and the application's snapshot-checked Zetaris evidence adapter. The [sanitized results](../../data/nightshift-acceptance/results.json) and [acceptance explanation](NIGHTSHIFT_ACCEPTANCE.md) record its scope and request correlations. The public reproduction script is `scripts/verify_nightshift.ts`; it requires explicit `--connect` and real live configuration.

| Scenario | Actual outcome | Evidence and planning |
|---|---|---|
| Normal payment | `no_anomaly_supported`, `NO_FAILURE` | 5 successful Zetaris queries; 4 successful planning calls |
| Partial coverage | `insufficient_evidence`, `EVIDENCE_GAP` | 5 successful Zetaris queries; 4 successful planning calls |
| Independent duplicate-payment lesson | `anomaly_supported`, `F06` | 5 successful Zetaris queries; 4 successful planning calls |
| New duplicate-payment investigation after approval | `anomaly_supported`, `F06`; approved memory recalled | 5 successful Zetaris queries; 4 successful planning calls |

All four cases and finding/check citations passed. One additional Nightshift call produced a real memory draft. A **scripted synthetic reviewer** edited it to an evidence-only procedure and approved it through the real review API. Review and active memory persisted after application-wrapper recreation, and the later target investigation recalled it while retrieving its own evidence. This is not a full operating-system/platform restart or a customer review decision.

All 17 application model calls (16 planning and one draft) matched read-only Nightshift explanations with exact decision IDs, application context `fintrace`, winning provider `google` and underlying winner `gemini-3.5-flash-lite`. A separate initial probe also passed. No failed application attempt occurred in this completed run. Requested/returned/routed/winner model labels were checked separately; missing HTTP request IDs were not replaced with Chat Completion IDs. The Mac Runtime's metadata is unsigned, and no signature or measured cost saving is claimed.

The account's first Google `gemini-3.6-flash` attempt passed normal and partial-coverage cases before returning `google_429`. A later probe also failed; that model has no complete acceptance result. Its free account quota was inspected, but the evidence did not establish daily-cap exhaustion. The final run used available `gemini-3.5-flash-lite` quota with five-second application request spacing and no billing change. This pacing is per process/Runtime URL and cannot coordinate other clients or guarantee future quota.

After the route-metadata and request-spacing changes, all 189 unit/API tests across 15 files, 13 H-MEM reference conformance checks, TypeScript checks and the production build passed. These automated checks are distinct from the live synthetic cases. Browser results below remain the latest complete browser-suite record.

This establishes the selected local sponsor-backed workflow. It does not establish real-customer accuracy, measured memory-efficiency improvement, production capacity, NVIDIA/Nemotron use or completed event submission. Final footage, slides and publication/submission actions remain pending.

## Local Zetaris and DeepSeek live acceptance — 27 October 2026

Installed the official Zetaris local platform on Apple M4 using its vendor Docker bundle. The vendor's nine checks passed, including healthy PostgreSQL/driver/API/UI services, completed initialization/bootstrap, authentication and a real UI → API → driver → Spark query. Published host ports are bound to loopback.

Registered an isolated `FINTRACE` PostgreSQL datasource with nine native datasource views using a dedicated source account restricted to reading `fintrace_source`. A second registration pass reused the same objects. Actual responses from the existing `/api/proxy/sql-editor/sqls/run-query` route match the application's matrix parser; no query-adapter change was necessary. Existing application retrieval verified all six evidence tools, plus `bank_statements`, against canonical snapshot hashes for one small built-in packet; all nine tables matched.

The isolated `live` profile uses PostgreSQL storage, Zetaris evidence retrieval and direct `deepseek-flash` inference. Connectivity preflight passed for all three services. Four fresh synthetic investigations passed:

| Scenario | Result |
|---|---|
| Normal payment | `no_anomaly_supported`, `NO_FAILURE` |
| Partial source coverage | `insufficient_evidence`, `EVIDENCE_GAP` |
| Independent duplicate-payment lesson | `anomaly_supported`, `F06` |
| New duplicate-payment investigation after approved memory | `anomaly_supported`, `F06`; approved memory recalled |

Each investigation completed five evidence-tool queries through Zetaris and four successful DeepSeek planning requests. All finding/check citations resolved. One additional real DeepSeek request generated a memory draft. A scripted synthetic reviewer edited it to an evidence-only procedure and approved it through the application's review API. Review and active memory survived application-wrapper recreation, then the new investigation recalled the approved memory. The lesson uses different record IDs and amounts from the target.

Reports and credentials remain in ignored local storage. The local reports are `verification-report.json`, `fintrace-source-verification.json`, `live-preflight.json` and `live-acceptance-XpHsHs/summary.json` under `.local/zetaris-runtime/`. These selected synthetic cases establish this local workflow only; they are not customer accuracy evidence, a measured memory-efficiency improvement, Nightshift validation, or completion of the separate three-source/USL/DQ submission materials. Query IDs remain application trace IDs.

After explicit user authorization, a seven-day API token was created for the local demo and stored only in the ignored private profile. Following the live server restart, both a constant query and actual overview retrieval with snapshot checks passed using that credential. The original local-model workspace remains separate from the live instance on port 4314. The token inherits the local account's permissions and expires on 3 November 2026; it is not a permanent credential.

The fresh-copy check used the local npm cache and the locked dependencies. It is not a clone from a published GitHub repository; the team must still verify the eventual public repository. Initial sandbox attempts blocked workspace symlinks and local test sockets; reruns with the required local permissions completed. Automated content scans are bounded checks, not a guarantee that every possible sensitive value has been identified.

## Browser limitations

The complete fixture browser suite ran against an isolated local server. Eleven checks failed in the existing UI; this preparation did not change UI code. The suite is not fully passing:

- Four mobile overflow assertions: all-results, inbox-layout, version-copy and workflow.
- Three mobile sidebar-position assertions: H-MEM and two removal flows.
- One dataset-ID font-size assertion (12 px versus the test's minimum of 16 px).
- One button-hover assertion (no transform versus the test's expected upward movement).
- One H-MEM checkbox/title alignment assertion.
- One removal-flow assertion expecting a historical dataset name in the workspace footer. This does not establish that the dataset is missing elsewhere in the interface.

Passing checks include desktop investigations, activity dialogs, polling, cancellation, reload, memory approval and ordinary exports. Use a desktop viewport for the demo, rehearse the exact sequence, and inspect all visible results. Mobile support and the failed UI expectations need follow-up; do not describe all browser tests as passing.

## Historical evidence — not repeated as live checks here

| Evidence | Reported result | Scope |
|---|---|---|
| PostgreSQL + Zetaris + direct OpenAI business acceptance, 26 October | 15/15 runs across nine synthetic scenarios, including repetitions | Live services, synthetic records; not Nightshift and not independent customer samples |
| H-MEM + OpenAI local-model experiment, 26 October | 12/12 expected outcomes and valid citations | Real model, local synthetic evidence; no Zetaris/Nightshift proof |
| H-MEM comparison | Same 28 requests per group; more tokens with memory; vendor-history tool moved earlier in the relevant case | No established token savings or statistical superiority |
| Earlier fixture reference evaluation | 39/40 development, 20/20 held-out, 10/10 derived stress | Deterministic rules over small synthetic sets; not evidence of AI advantage |

Earlier detailed reports remain in `docs/EVALUATION.md`, `docs/RELEASE_VALIDATION.md` and the historical Chinese acceptance notes. Their old competition-rule interpretations are superseded by [REQUIREMENTS.md](REQUIREMENTS.md).

## Three-feed USL and native data-quality scoring package — 27 October 2026

The separate [Zetaris scoring package](ZETARIS_USL.md) is implemented and exercised on the local Zetaris 2.4.3.1 platform. Its independent scoring snapshot is `ds-f9be2f5bab44f603`; original datasets and investigation evidence bindings were retained.

- Three separately connected simulated feeds: PostgreSQL ERP payment facts, a persistent bank CSV source and a loopback read-only supplier-policy HTTP API. ERP and bank records share a synthetic scenario generator; these are not three real enterprise systems.
- Deployed and activated `lightning.metastore.fintrace_scoring.payment_review` with three tables, three primary keys and two foreign keys. The exported multi-table DDL and activation SELECTs are included. A second provisioning pass reused the same objects without recreating or rebinding them.
- Six source-exploration queries passed, two per feed. Three USL queries passed. The nine scoped payments joined to seven bank observations and eight policy records without losing or multiplying a payment; every payment had one effective policy. Six bank observations were posted, one was returned, and two payments had no bank observation. Returned/missing variances remained `NULL`.
- A hand-written source-normalization/join query returned the same rows as the corresponding USL query. That consumer query uses 2,406 characters versus 1,002 for the USL consumer; shared DDL/activation is excluded. No development-time saving was measured.
- Seven native Zetaris rules were actually executed: three primary-key constraints, two foreign-key constraints and two custom amount/policy rules. Every evaluated row passed; the payment amount rule evaluated 9 rows and the policy rule evaluated 8. Invalid-record queries returned zero rows. These overlapping populations are not aggregated into a financial-accuracy rate.
- The policy server's eight GET/HEAD/404/405 smoke checks passed and it listens only on `127.0.0.1:4315`. TypeScript checks and all 174 existing unit/API tests passed after the new scripts were added. No model calls were made for the USL/DQ work.

Source contracts, synthetic assets, setup/verification scripts, actual query/result pairs, DQ counts and reflections are included in the allowlisted source package. Full results are in `data/zetaris-scoring/results.json`; first-run and idempotent setup receipts are in its `evidence/` directory. This work completes the local evidence package against the supplied Zetaris scoring summary. The separate complete Nightshift acceptance is recorded above; the USL exercise itself does not prove Nightshift use or organizer acceptance.

## Required final evidence

The complete technical workflow is recorded in [NIGHTSHIFT_ACCEPTANCE.md](NIGHTSHIFT_ACCEPTANCE.md). Use [NIGHTSHIFT_SETUP.md](NIGHTSHIFT_SETUP.md) to rehearse the actual configured route, then capture application, Zetaris/Nightshift and H-MEM activity for the final video/deck. Preserve earlier failures separately from the passing run. The sanitized synthetic result is public; keep credentials and raw private diagnostics outside the source package. Repository access, final media, disclosures and HackOS confirmation still require delivery checks.
