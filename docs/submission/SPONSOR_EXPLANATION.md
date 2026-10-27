# Sponsor technology explanation

**Current, evidence-bounded draft.** This text describes the code and historical validation honestly. The final submission still needs real Nightshift acceptance; do not remove that status without new evidence. The team's target underlying model is OpenAI, routed through Nightshift.

## Zetaris — read-only financial evidence

FinTrace uses Zetaris as its evidence-query layer in `live` mode. The investigation controller selects from six typed tools; the tools construct bounded SELECT queries against nine registered `fintrace_source` PostgreSQL views in the configured Lightning namespace. The model cannot write arbitrary SQL or modify financial records.

Retrieved rows are checked against the immutable imported source snapshot before they support a finding. Source coverage, observation cutoffs and exact evidence references help distinguish an empty result from a failed query or incomplete extract. PostgreSQL also stores application state and imports directly; those writes do not go through Zetaris.

Historical integration tests connected PostgreSQL, Zetaris and direct OpenAI and completed 15 synthetic acceptance runs across nine scenarios, including repetitions. That demonstrates the tested local workflow, not real-customer accuracy. The current tested sources are multiple tables in one PostgreSQL database; we do not claim a demonstrated federation across multiple enterprise systems.

Code: `apps/api/src/integrations/zetaris.ts`, `apps/api/src/evidence.ts`, `apps/api/src/store.ts`.

## Meterless H-MEM — reviewed procedures with provenance

FinTrace integrates the pinned Meterless H-MEM reference engine in a working review-to-memory feature. After an investigation, a reviewer can request a model-generated procedural suggestion, edit it, select its scope and explicitly approve it. Only approved, active procedures are eligible for later contextual recall. The UI exposes their source investigation, approval, scope, match explanation and deactivation/restoration controls. Historical investigation snapshots remain unchanged.

The feature gives future investigations reusable evidence-gathering guidance, such as checking vendor-change history before other sources. Memory cannot replace financial records, expand the permitted tool set or override the independent verifier. The implementation uses deterministic hash embeddings and local keyword/bigram retrieval, not a production semantic embedding service. Automatic dreaming and sleep workflows are not part of the feature.

Validation combines the vendored engine's conformance suite, application lifecycle/API tests and a reproducible with/without-memory experiment. Historical OpenAI/local-data testing matched 12/12 expected outcomes and valid citations; it changed tool ordering in the vendor-change scenario but did not reduce total model requests and increased token use. It is not evidence of lower cost or statistically significant accuracy gains. Current test results are recorded in [VALIDATION.md](VALIDATION.md).

Code: `apps/api/src/integrations/memory.ts`, `apps/api/src/service.ts`, `third_party/meterless/engines/hmem/`. Commands: `npx tsx third_party/meterless/engines/hmem/conformance/runner.ts` and `npm run verify:hmem` in fixture mode.

## Meterless Nightshift — required primary inference provider

The implementation has a configurable Nightshift provider selected by `MODEL_PROVIDER=meterless`. It sends investigation planning, memory-suggestion and optional baseline requests to the configured Runtime's OpenAI-compatible `/chat/completions` endpoint using a Runtime token. The application validates output contracts and citations locally, records provider/model request metadata, and does not silently fall back to a direct cloud provider when Nightshift fails.

The intended final route is **FinTrace → Nightshift → OpenAI**. OpenAI credentials belong in the Runtime's provider configuration for this route; FinTrace uses the Nightshift credential. The underlying model and route must be confirmed in the installed Nightshift version rather than inferred from OpenAI-compatible protocol support.

**Unverified as of this preparation pass:** no real Nightshift request or complete Nightshift-routed investigation was executed. Automated adapter tests use mocked responses. Historical direct OpenAI validation cannot be relabeled as Nightshift validation. This is an outstanding submission requirement.

Code: `apps/api/src/integrations/model.ts`, `scripts/preflight.ts`, `tests/meterless-submission.test.ts`. Setup and required capture: [NIGHTSHIFT_SETUP.md](NIGHTSHIFT_SETUP.md).

After real acceptance, replace the status paragraph with a short factual record containing the test date, Runtime version, actual underlying model, cases run, result, and a reference to sanitized evidence. Do not fill these values speculatively.

## NVIDIA and development tooling

The code includes a direct NVIDIA model adapter for development, but no verified NVIDIA/Nemotron execution is claimed for this submission preparation. The team is not claiming the NVIDIA DGX Spark award. That award requires a working Nemotron feature routed through Nightshift and evidence of the model handling the request.

Cursor is optional in the supplied requirements. This preparation was performed with Codex; include a Cursor statement only if a team member can describe actual Cursor work. An unexecuted adapter, installed dependency or copied prompt is not evidence of sponsor use.

## What is distinctive

FinTrace connects governed evidence retrieval to an independently checked financial outcome, then retains human-approved investigation procedures with provenance. The model decides what evidence to retrieve; the verifier checks money, timing and coverage; the reviewer decides what knowledge can be reused. This separation makes both the findings and the agent's investigation process inspectable, while keeping unsupported conclusions unresolved.
