# Nightshift setup and acceptance

**Current status: the complete synthetic live acceptance passed on 27 October 2026 using Google `gemini-3.5-flash-lite` through Nightshift.** Normal, evidence-gap and anomaly investigations, memory drafting, scripted review/approval, persistence after application-wrapper recreation and later recall passed. See [NIGHTSHIFT_ACCEPTANCE.md](NIGHTSHIFT_ACCEPTANCE.md) and the [sanitized results](../../data/nightshift-acceptance/results.json). Final recording and submission remain separate tasks.

## Current target route

```text
FinTrace → Meterless Nightshift → Google gemini-3.5-flash-lite → Nightshift → FinTrace
FinTrace evidence tools → Zetaris → PostgreSQL source views
```

The official Mac M1-M4 application, version 0.92.7, exposes an authenticated API at `http://127.0.0.1:8088/v1` on the tested Apple M4 / 16 GB Mac. Actual application calls and their Runtime explanations identified Google as the winning provider and `gemini-3.5-flash-lite` as the underlying model.

Obtain Nightshift from its [official site](https://meterless.ai/) and the [Mac M1+ download](https://meterless.ai/Nightshift/M1%2B/). The installed Mac edition exposes an API despite older help pages describing this edition as having no endpoint. Verify other editions and machines directly.

## Provider and model selection

The verified profile uses the Google AI key saved in Nightshift's provider settings. Keep the provider key inside Nightshift; FinTrace authenticates with the local Runtime credential. On another machine, configure an actually supported provider with usable model access and quota, then verify the route again. OpenAI is an option, not a mandatory underlying model.

Earlier OpenAI calls failed with `429` / `insufficient_quota`. An initial Google `gemini-3.6-flash` smoke and two business cases succeeded, but a later call returned `google_429` and stopped that acceptance run. The final complete run used the account's available `gemini-3.5-flash-lite` quota with request spacing. No billing change was made. A working direct DeepSeek key does not establish that Nightshift accepts that key directly.

After configuring the provider, choose a model or routing ID actually advertised by that Runtime. If using a routing alias, record the underlying winning model from the Runtime's explanation rather than treating the alias as the model identity. Do not reuse the retired local Qwen model ID or describe an untested cloud route as successful.

## Isolated live application configuration

Reuse the existing PostgreSQL/Zetaris setup in [INTEGRATIONS.md](../INTEGRATIONS.md). The separate ignored `.env.nightshift-live.local` profile uses port 4316 and storage `.local/nightshift-live`; the original workspace on 4310 and direct-DeepSeek/Zetaris profile on 4314 remain independent. The verified local configuration is:

```dotenv
FINTRACE_MODE=live
MODEL_PROVIDER=meterless
METERLESS_BASE_URL=http://127.0.0.1:8088/v1
METERLESS_RUNTIME_TOKEN=<local Runtime credential>
METERLESS_MODEL=gemini-3.5-flash-lite
METERLESS_MIN_REQUEST_INTERVAL_MS=5000
DATABASE_URL=<application PostgreSQL connection>
ZETARIS_BASE_URL=http://127.0.0.1:3000
ZETARIS_ORG_ID=<numeric organisation ID>
ZETARIS_API_KEY=<existing Zetaris API credential>
ZETARIS_TABLE_PREFIX=FINTRACE.
FINTRACE_STORAGE_DIR=.local/nightshift-live
HOST=127.0.0.1
PORT=4316
```

Choose a free port on another machine. Do not overwrite a working `.env.local` to try a different provider. The Runtime token is not the cloud provider's key. Keep private profiles and credentials outside Git and the recording frame.

`METERLESS_MIN_REQUEST_INTERVAL_MS` is optional, defaults to zero, and accepts integer values from 0 to 60000. The verified demo spaces application request starts by at least five seconds within one process and Runtime base URL, including bounded retries. This accommodates the tested account's free quota; it does not coordinate multiple processes or guarantee quota availability. Do not run simultaneous demo servers against the same limited quota.

An isolated `local-model` profile can diagnose inference over local evidence without PostgreSQL/Zetaris, but final technical acceptance uses `live` + `meterless`. Select context/output limits appropriate to the actual cloud route and verify complete planning and memory operations; the retired local model's limits are not cloud-model capacity evidence.

The adapter sends `meterless-app: fintrace` and `meterless-scope: user`, with a 180-second Nightshift request/preflight timeout. It supplies the JSON output contract in the prompt and validates the result locally without assuming every routed model supports OpenAI's strict JSON-schema request parameters. The headers follow the [official provider contract](https://meterless.ai/engines.html).

## Request-to-Runtime correlation

The application retains known, bounded scalar route labels:

| Application trace field | Source and meaning |
|---|---|
| `requestId` | HTTP `x-request-id`, or `x-meterless-request-id` when present; it may be absent |
| `meterlessDecisionId` | `meterless.decision_id`; use this for the Runtime explanation lookup |
| `meterlessWinningProvider` | `meterless.winning_route.provider` |
| `meterlessRoutedModel` | `meterless.routed_model` |
| `returnedModel` | The response's model field; compare it with the Runtime explanation |

For each successful planning and memory-draft call, look up authenticated `GET /v1/explain/{meterlessDecisionId}` and match the decision ID, actual winner/model, provider route and `fintrace` application context. A Chat Completion ID, whether exposed as `id` or `completion.id`, is not the Runtime decision ID. An absent HTTP request ID does not invalidate a separately matched Runtime decision.

The tested Mac edition's in-app receipt and explanation metadata are unsigned. Its daemon signed-receipt endpoint is unavailable; no cryptographic receipt verification is claimed. Provider-reported savings/cost metadata is not evidence of measured FinTrace efficiency.

## Reproduce the acceptance

From the repository root, use the actual private profile:

```sh
node --env-file=.env.nightshift-live.local --import tsx scripts/preflight.ts --submission
node --env-file=.env.nightshift-live.local --import tsx scripts/preflight.ts --submission --live
node --env-file=.env.nightshift-live.local --import tsx scripts/verify_nightshift.ts --connect
node --env-file=.env.nightshift-live.local --import tsx apps/api/src/server.ts
```

The first command is configuration-only. The second contacts required services and makes a small real model request, consuming provider quota and potentially credit. Passing preflight is not full acceptance: it still reports `submissionReady: false`. The third command is the explicit live acceptance; it makes real calls and writes fresh synthetic datasets, a scripted review and approved memory. Its default namespace is isolated. Add `--workspace` only when those synthetic records should be visible in the demo workspace. `npm run verify:nightshift -- --connect` is the equivalent shortcut when the required variables are already loaded into the environment. The last command starts the demo server.

The verifier first checks a real cloud completion and its matching Runtime explanation, then pins the observed requested/returned/routed/winner/provider fields separately. It checks fresh normal, anomaly and evidence-gap investigations; a real model-generated memory draft; scripted edit/approval; application-wrapper recreation; and later H-MEM recall. Every successful model operation must have a matching Runtime explanation. It rejects local-device/mock routes, route drift and wrong business outcomes without a direct-provider fallback. Its local report contains bounded metadata; review any exported report before publishing.

The completed run had four passing investigations, 20 successful Zetaris queries and 17 successful application model calls (16 planning and one memory draft), all correlated with Nightshift. A separate initial probe also passed. All finding/check citations resolved. Automated review actions are labeled **scripted synthetic reviewer**, not customer or user decisions. Persistence was checked by recreating the application wrapper, not restarting the operating system or the full platform.

Capture the actual application and Runtime views without credentials, then follow [TEAM_HANDOFF.md](TEAM_HANDOFF.md). Video, slides, public repository access, disclosures, team details and HackOS confirmation remain separate submission tasks.

## Historical local-model diagnosis

The retired trial used `webllm/Qwen2.5-1.5B-Instruct-q4f16_1-MLC` through Nightshift on this Mac. A small request returned HTTP 200; initial download/load plus that request took about 26.7 seconds. It used a 4,096-token context and 1,024-token output ceiling. Those are historical local-test settings and one first-use observation, not recommended cloud settings or a latency benchmark.

Real Runtime explanations confirmed the `webllm` winner. However, two fresh normal-case attempts both stopped after overview and produced the safe `insufficient_evidence` outcome instead of the expected normal conclusion. Clarifying the planner prompt to continue while allowed evidence tools remained did not make the second attempt pass. The independent financial verifier and output validation were unchanged. The user then stopped this local route and requested model removal; it is not a completed Nightshift business integration.

| Symptom | Required response |
|---|---|
| Runtime authentication fails | Check its actual local credential; do not substitute a cloud key |
| Cloud key has no credit/model access | Resolve the selected provider account or configure another supported provider, then explicitly retest |
| Requested model is unavailable | Select an actually advertised route/model; do not guess an alias |
| Context/output limit, malformed JSON or invalid tool | Retain the failure and inspect the contract; no silent answer repair or direct-provider fallback |
| Preflight passes but the case returns the wrong outcome | Keep business acceptance failed until the full workflow passes |
| Runtime is offline or times out | Fail visibly; no automatic direct-provider or fixture fallback |
| Runtime explanation is absent or identifies a different winner | Mark provenance unverified instead of inferring it from a label |

Contract tests in `tests/meterless-submission.test.ts` prove behavior under mocks. Real inference, business outcomes and lifecycle evidence are separate in [NIGHTSHIFT_ACCEPTANCE.md](NIGHTSHIFT_ACCEPTANCE.md).
