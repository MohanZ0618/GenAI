# Sponsor technology explanation

**Current evidence: 27 October 2026.** The tested route is PostgreSQL + Zetaris + Meterless Nightshift + Google `gemini-3.5-flash-lite`. Four fresh synthetic investigations and the review-to-memory lifecycle passed. The [acceptance record](NIGHTSHIFT_ACCEPTANCE.md) links the sanitized results; final video, slides and submission remain separate tasks.

## Zetaris — read-only financial evidence

FinTrace uses Zetaris as its evidence-query layer in `live` mode. The investigation controller selects from six typed tools; the tools construct bounded SELECT queries against nine registered `fintrace_source` PostgreSQL views in the configured Lightning namespace. The model cannot write arbitrary SQL or modify financial records.

Retrieved rows are checked against the immutable imported source snapshot before they support a finding. Source coverage, observation cutoffs and exact evidence references help distinguish an empty result from a failed query or incomplete extract. PostgreSQL also stores application state and imports directly; those writes do not go through Zetaris.

Historical integration tests connected PostgreSQL, Zetaris and direct OpenAI and completed 15 synthetic acceptance runs across nine scenarios, including repetitions. The current Mac also completed four fresh PostgreSQL/Zetaris/DeepSeek investigations with valid citations and memory approval/persistence/recall. These selected synthetic cases demonstrate the tested local workflow, not real-customer accuracy.

The [USL scoring package](ZETARIS_USL.md) separately deploys a typed, related model across PostgreSQL payment facts, a bank CSV and a supplier-policy HTTP API. It includes six source-exploration queries, three USL queries, executed native data-quality checks and a hand-written source-query comparison. These are three separately connected simulated feeds; ERP and bank records share a synthetic scenario generator. No connection to three real enterprise systems is claimed. The original investigation tools retain their immutable-snapshot evidence contract.

Code: `apps/api/src/integrations/zetaris.ts`, `apps/api/src/evidence.ts`, `apps/api/src/store.ts`.

## Meterless H-MEM — reviewed procedures with provenance

FinTrace integrates the pinned Meterless H-MEM reference engine in a working review-to-memory feature. After an investigation, a reviewer can request a model-generated procedural suggestion, edit it, select its scope and explicitly approve it. Only approved, active procedures are eligible for later contextual recall. The UI exposes their source investigation, approval, scope, match explanation and deactivation/restoration controls. Historical investigation snapshots remain unchanged.

The feature gives future investigations reusable evidence-gathering guidance, such as checking vendor-change history before other sources. Memory cannot replace financial records, expand the permitted tool set or override the independent verifier. The implementation uses deterministic hash embeddings and local keyword/bigram retrieval, not a production semantic embedding service. Automatic dreaming and sleep workflows are not part of the feature.

Validation combines the vendored engine's conformance suite, application lifecycle/API tests and a reproducible with/without-memory experiment. Historical OpenAI/local-data testing matched 12/12 expected outcomes and valid citations; it changed tool ordering in the vendor-change scenario but did not reduce total model requests and increased token use. It is not evidence of lower cost or statistically significant accuracy gains. Current test results are recorded in [VALIDATION.md](VALIDATION.md).

Code: `apps/api/src/integrations/memory.ts`, `apps/api/src/service.ts`, `third_party/meterless/engines/hmem/`. Commands: `npx tsx third_party/meterless/engines/hmem/conformance/runner.ts` and `npm run verify:hmem` in fixture mode.

## Meterless Nightshift — required primary inference provider

The implementation has a configurable Nightshift provider selected by `MODEL_PROVIDER=meterless`. It sends investigation planning, memory-suggestion and optional baseline requests to the configured Runtime's OpenAI-compatible `/chat/completions` endpoint using a Runtime token. The application validates output contracts and citations locally, records provider/model request metadata, and does not silently fall back to a direct cloud provider when Nightshift fails.

The verified route is **FinTrace → Nightshift → Google `gemini-3.5-flash-lite`**. Provider credentials belong in the Runtime's settings; FinTrace uses the Nightshift credential. The installed official Mac M1-M4 application is version 0.92.7. Exact Runtime decisions and actual model/provider metadata establish the tested route independently of the protocol's OpenAI compatibility.

The completed acceptance covered normal payment, partial evidence coverage, an independent duplicate-payment lesson and a later duplicate-payment investigation recalling the approved procedure. All 20 Zetaris evidence queries succeeded and all finding/check references resolved. Sixteen planning calls and one model-generated memory draft matched authenticated Runtime explanations, including decision ID, model, Google provider and `fintrace` context. The scripted synthetic reviewer edited and approved the procedure through the real review API; review and memory survived application-wrapper recreation, then the later case recalled that exact memory. This is a working feature test rather than a customer decision, held-out accuracy experiment or measured efficiency gain.

Earlier OpenAI quota failures, two incomplete local Qwen attempts and a Google 3.6 Flash quota-limited attempt are preserved as diagnostics. They are not counted as successful cases. The completed route uses a five-second per-process request interval, with no direct-provider or fixture fallback. Runtime explanations are unsigned; no cryptographic receipt verification is claimed. See [the full record](NIGHTSHIFT_ACCEPTANCE.md).

Code: `apps/api/src/integrations/model.ts`, `scripts/preflight.ts`, `scripts/verify_nightshift.ts`, `tests/meterless-submission.test.ts`. Setup and required capture: [NIGHTSHIFT_SETUP.md](NIGHTSHIFT_SETUP.md).

## NVIDIA and development tooling

The code includes a direct NVIDIA model adapter for development, but no verified NVIDIA/Nemotron execution is claimed for this submission preparation. The team is not claiming the NVIDIA DGX Spark award. That award requires a working Nemotron feature routed through Nightshift and evidence of the model handling the request.

Cursor is optional in the supplied requirements. This preparation was performed with Codex; include a Cursor statement only if a team member can describe actual Cursor work. An unexecuted adapter, installed dependency or copied prompt is not evidence of sponsor use.

## What is distinctive

FinTrace connects governed evidence retrieval to an independently checked financial outcome, then retains human-approved investigation procedures with provenance. The model decides what evidence to retrieve; the verifier checks money, timing and coverage; the reviewer decides what knowledge can be reused. This separation makes both the findings and the agent's investigation process inspectable, while keeping unsupported conclusions unresolved.
