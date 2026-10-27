# Live integration setup

> **Submission update (27 October 2026):** the supplied HackOS Submission Requirements explicitly require a working Meterless Engine **and Nightshift as the primary AI provider**. Direct cloud adapters below remain development options. Use [Nightshift setup](submission/NIGHTSHIFT_SETUP.md), [the current checklist](submission/REQUIREMENTS.md), and `npm run preflight:submission`. Historical direct-OpenAI results are not Nightshift proof.

## What is already implemented

The app has PostgreSQL storage, a bounded read-only Zetaris query adapter, configurable model inference, and the pinned Meterless H-MEM reference. The original release checks were offline. A later local Docker validation on 2026-10-26 connected PostgreSQL, Zetaris, and OpenAI and completed two selected synthetic live investigations. Credentials and raw runtime traces are not part of the repository.

## PostgreSQL

Install Docker Desktop from its official source, or use an existing PostgreSQL instance. The included Compose file provides PostgreSQL bound to `127.0.0.1:5432`. Its password is a development-only example, not a secret.

1. Copy `.env.example` to `.env.local`; set `DATABASE_URL` for your instance.
2. Run `docker compose up -d`, then `npm run db:init`.
3. `fintrace_app` stores datasets and runs. `fintrace_finance` stores immutable JSONB financial records. `fintrace_source` exposes `dataset_id`, `record_id`, and a text `payload` column for each of the nine source tables.
4. Use a dedicated read-only PostgreSQL account for the Zetaris connector, with SELECT access only to the source views. The importer uses the application connection.

## Zetaris

Obtain and start your own instance using the official [installation and connection materials](https://github.com/zetaris/getting-started). On a Docker deployment, PostgreSQL must be reachable from the Zetaris container; the container's `localhost` is not the Windows host. Verify the address for your deployment before registering the connector.

Register the nine `fintrace_source` PostgreSQL views with the Zetaris PostgreSQL connector in a Lightning database named `FINTRACE`, preserving their lowercase table names. The app's default prefix is `FINTRACE.`; change `ZETARIS_TABLE_PREFIX` to the actual registered namespace if necessary. This registration was exercised in the 2026-10-26 local Docker validation using a dedicated read-only PostgreSQL role. Connector credentials and host details remain instance-specific. Do not register evaluation labels, mutation logs, or benchmark answer files.

Configure:

```dotenv
FINTRACE_MODE=live
ZETARIS_BASE_URL=<Zetaris UI HTTP(S) origin, with no path>
ZETARIS_ORG_ID=<numeric organisation ID>
ZETARIS_API_KEY=<local credential>
ZETARIS_TABLE_PREFIX=FINTRACE.
```

The adapter follows the official UI-proxy helper at commit `98a2d30603c6e2c001ce3e6e1d43798f1d6c75c9`: POST `/api/proxy/sql-editor/sqls/run-query`, bearer authorization, `X-Org-ID`, UUID `X-Request-ID`, and body `{sql,limit,engineId?}`. `ZETARIS_BASE_URL` is the UI origin, not the direct REST port. This implementation deliberately supports that one route; it does not guess a direct REST alternative.

Only application-constructed SELECTs are accepted. Queries request 1001 rows and reject evidence tables above the verified 1000-row bound instead of silently treating truncated output as complete. Every returned financial table is checked against a canonical checksum of the immutable imported snapshot, preventing silently truncated or mismatched sources from supporting a conclusion. Errors and unrecognised response shapes throw; a successful empty response is different from a failed request.

On 27 October 2026, the current official local Docker bundle was also verified on Apple M4. Its legacy `run-query` route returned the supported `headers`/`data` matrix. The newer `/api/proxy/query/sql/start` route returned a different `records` envelope and is not used by this adapter. Nine `FINTRACE` native datasource views, snapshot-integrity checks, four synthetic live investigations and H-MEM approval/persistence/recall passed with direct DeepSeek; see [the current validation record](submission/VALIDATION.md). This does not establish a Nightshift route. The separate [three-feed USL and native DQ demonstration](submission/ZETARIS_USL.md) records its own deployment, source SQL, results and reproduction commands; it does not replace the application's snapshot-checked evidence path.

For an isolated local profile, put the database, Zetaris and selected model settings in an ignored `.env.zetaris.local`, with a separate `FINTRACE_STORAGE_DIR` and free `PORT`. Start it with `node --env-file=.env.zetaris.local --import tsx apps/api/src/server.ts`; run `node --env-file=.env.zetaris.local --import tsx scripts/preflight.ts --live` for a real connection check. Ordinary login JWTs in the tested bundle expire after approximately 15 minutes. The UI's Management → API Tokens flow supplies expiring API credentials; treat them as secrets and check the account permissions they inherit. The application does not refresh login JWTs automatically.

## Model provider

Choose one explicit provider. Configuration changes require a server restart.

**OpenAI:** set `MODEL_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-4.1-mini`), and optionally `OPENAI_BASE_URL` (default `https://api.openai.com/v1`). Keys belong only in the backend environment or ignored `.env.local`. The adapter uses Chat Completions with strict JSON Schema output, `max_completion_tokens`, and `store=false`. It checks refusal, truncated output, schema validity, and evidence citations. Authentication/model-access errors fail immediately; transient network/429/5xx failures get one retry. Defaults are tested with mocked responses, not a real account.

**DeepSeek:** set `MODEL_PROVIDER=deepseek`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` (default `deepseek-flash`), and optionally `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`). Use `FINTRACE_MODE=local-model` for real model planning over the current imported data. This is a separate adapter: it sends `max_tokens`, `response_format={"type":"json_object"}`, and `thinking={"type":"disabled"}`, supplies the output contract in the prompt, and validates the returned JSON and evidence citations locally. OpenAI-only strict JSON Schema, `store`, and `max_completion_tokens` parameters are omitted. The internal `reasoning_content` field is neither displayed nor persisted. See the official [API setup](https://api-docs.deepseek.com/), [JSON output](https://api-docs.deepseek.com/guides/json_mode/), and [thinking-mode parameters](https://api-docs.deepseek.com/guides/thinking_mode/). A real synthetic normal-case investigation completed on 2026-10-27 with four successful DeepSeek requests; this validates connectivity and workflow only. Private credentials and runtime records are excluded from source control.

For OpenAI with local evidence, use `FINTRACE_MODE=local-model`. This uses local file storage, imported/built-in snapshots, real model planning and the independent verifier. PostgreSQL and Zetaris are not required or contacted. The UI and exports identify this mode separately from full live integration. Leave `FINTRACE_STORAGE_DIR` blank for the isolated default `.local/manual-openai`, or choose your own directory.

**NVIDIA:** set `MODEL_PROVIDER=nvidia`, `NVIDIA_API_KEY`, and `NVIDIA_MODEL`. The initial model is `nvidia/llama-3.3-nemotron-super-49b-v1.5` at `https://integrate.api.nvidia.com/v1`. Availability and trial limits are account-dependent.

**Meterless Runtime:** start the official Runtime, enable its OpenAI-compatible endpoint, and set `MODEL_PROVIDER=meterless`, `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`, and `METERLESS_MODEL` to the values actually provided by that Runtime. No provider switch is automatic.

The Meterless adapter supplies each operation's JSON schema in the system prompt and validates returned values locally. It does not assume all Runtime models support strict JSON-schema request parameters. Planning, memory suggestions and baseline calls share the selected provider. Authentication errors fail immediately; bounded retries remain on the same endpoint. The preflight reports requested and returned models, when available, but the actual underlying route must also be verified in Nightshift. Cloud keys belong in Nightshift's provider settings for this route; FinTrace uses its Runtime token.

The 27 October 2026 acceptance used the official Mac M1-M4 Runtime 0.92.7 and Google `gemini-3.5-flash-lite`. Four fresh synthetic live investigations, a real memory draft, scripted approval, application-wrapper recreation and later recall passed. All 17 business model calls matched their Runtime decision, Google provider and model; see [the results and reproduction steps](submission/NIGHTSHIFT_ACCEPTANCE.md).

Optional `METERLESS_MIN_REQUEST_INTERVAL_MS` sets request-start spacing from 0 to 60000 milliseconds; the default is 0. The tested demo uses 5000. Planning, drafts, concurrent calls and retries share this gate for the same Runtime endpoint within one FinTrace process, and cancelled waiting calls are not sent. It does not coordinate other processes or increase the provider's daily quota. Check the selected provider's actual account limits before a demonstration.

The planner emits a strict typed tool request. Transient model HTTP errors receive one retry. Output that chooses an unknown tool or fails schema validation terminates as a technical failure. Financial outcomes are determined by independent rules, not the model's self-assessment.

Run `npm run preflight` for configuration presence only, or `npm run preflight -- --live` for connection checks. Fixture mode requires and contacts no external services; local-model checks only the selected model; live requires database, Zetaris and the selected model. Model checks consume a small API call. Missing required configuration or failed checks set a nonzero exit code. Preflight never prints credentials or raw provider error bodies. A successful generic query/model call is only an initial check: complete a real investigation to prove the evidence contract.

## H-MEM

The application wrapper supplements the reference retrieval with local bilingual concept keywords and Chinese character bigrams. Approved original text and provenance are retained; no embedding API is added. This remains a lightweight local retrieval implementation, not a production semantic embedding service.

Source: [Meterless H-MEM reference](https://github.com/Meterless/Meterless/tree/1742dec56a66e58eef9dda2d2b865823758ca8cd/engines/hmem/reference). Its source and Apache-2.0 license are retained under `third_party/meterless`.

Each namespace has its own persistent engine directory and trust ledger. The wrapper records human approval provenance and source run ID. Memory is limited to approved playbooks/preferences and is treated as untrusted context; rules and financial source facts cannot be overridden by it. The mock embedder is deterministic. Do not describe it as a production embedding model or as evidence of semantic retrieval performance.

## Required live release evidence

After setup, record three successful runs each for an anomaly, a normal exception, and an evidence-deficient case. This project acceptance target was met on 2026-10-26 using `npm run verify:business -- --connect --repeat=3` in live mode: duplicate payment, normal payment and partial coverage each passed three fresh runs, alongside six additional scenarios. This is a project validation target, not a claimed competition rule.

Preserve provider/model IDs, source coverage and run exports locally. Current query IDs are application-generated trace IDs; server-issued Zetaris query IDs are not captured. Run `npm run evaluate -- heldout` in live mode for the still-outstanding full reference-set tool-planning and same-model one-pass comparison. Live evaluation consumes model calls and may take several minutes per case.
