# Nightshift live acceptance

Prepared on 27 October 2026. **The complete synthetic live workflow passed through Nightshift using Google `gemini-3.5-flash-lite`.** The checked route was:

```text
FinTrace → Meterless Nightshift → Google gemini-3.5-flash-lite → Nightshift → FinTrace
FinTrace evidence tools → Zetaris → PostgreSQL source views
```

The [sanitized result record](../../data/nightshift-acceptance/results.json) contains the case results, memory lifecycle and request-to-Runtime correlations. These are selected synthetic acceptance cases, not customer accuracy measurements or completed competition submission evidence.

## Actual run

The public [live verifier](../../scripts/verify_nightshift.ts) ran from 22:01:48 to 22:03:31 UTC on 27 October 2026 with `FINTRACE_MODE=live`, `MODEL_PROVIDER=meterless` and five-second application request spacing. The Runtime was the official Nightshift Mac M1-M4 application 0.92.7 on Apple M4 / 16 GB, exposing an authenticated API at `http://127.0.0.1:8088/v1`. The Google provider key stayed inside Nightshift; FinTrace used its local Runtime credential.

| Fresh synthetic scenario | Actual outcome | Category | Zetaris queries | Planning requests |
|---|---|---|---|---|
| Normal payment | `no_anomaly_supported` | `NO_FAILURE` | 5/5 succeeded | 4/4 succeeded |
| Partial source coverage | `insufficient_evidence` | `EVIDENCE_GAP` | 5/5 succeeded | 4/4 succeeded |
| Independent duplicate-payment lesson | `anomaly_supported` | `F06` | 5/5 succeeded | 4/4 succeeded |
| New duplicate-payment investigation after approved memory | `anomaly_supported` | `F06`; approved memory recalled | 5/5 succeeded | 4/4 succeeded |

All four investigations completed with their expected outcomes and valid finding/check citations. They made 20 successful evidence-tool queries through the application's snapshot-checked Zetaris adapter. The independent financial verifier continued to determine outcomes; the model selected evidence tools. The lesson dataset used different record IDs and amounts from the later target, rather than storing its answer.

The 16 planning requests and one additional memory-draft request succeeded without failed application attempts in this run. All 17 matched a Nightshift explanation with application context `fintrace`, winning provider `google` and winner `gemini-3.5-flash-lite`. A separate initial cloud probe also passed; it is not included in the 17 application calls.

## Memory lifecycle

After the independent lesson investigation, a real Nightshift-routed model request generated a ready procedural memory draft. A **scripted synthetic reviewer** edited it to an evidence-only procedure and accepted it through the real application review API. The approved procedure contains no target payment IDs, amounts or classification answer.

Review and active memory `mem-1` survived application-wrapper recreation. The later target investigation recalled that memory and gathered its own current evidence before producing the expected anomaly result. This demonstrates drafting, editing, explicit approval, persistence and later recall. It does not establish improved accuracy, fewer requests or token savings. Persistence was not tested by an operating-system or whole-platform restart.

## Request-to-Runtime evidence

Application traces retain known bounded scalar fields: requested and returned models, `meterlessDecisionId`, `meterlessRoutedModel` and `meterlessWinningProvider`. The verifier obtains authenticated `GET /v1/explain/{meterlessDecisionId}` and checks the exact decision, winner, route and `fintrace` context. It keeps the observed requested/returned/routed/winner fields distinct instead of assuming a routing alias equals the model identity. All those model fields happened to be `gemini-3.5-flash-lite` in this run.

Examples in the result record include planning decision `req_khdk1ley`, memory-draft decision `req_94mnt1wa` and later-recall investigation decision `req_q954p7bd`. Their explanations match their application traces. HTTP request IDs were absent; a Chat Completion ID was not substituted for a Runtime decision ID.

The tested Mac edition's receipt/explanation metadata is unsigned. No cryptographic receipt verification is claimed. Runtime cost/savings estimates are not measured FinTrace efficiency or billing evidence. Evidence query IDs remain application trace IDs, not Zetaris server-issued IDs.

## Earlier diagnostics and quota limits

Earlier attempts remain separate from the passing run:

- An OpenAI key reached Nightshift but returned `429` / `insufficient_quota`.
- A local Qwen 1.5B trial produced real completions and matching Runtime explanations, but two normal investigations stopped before gathering enough evidence and retained `insufficient_evidence`. The user stopped that route. Its model/cache was moved to Trash, and empty cached/resident-model lists were verified after Nightshift restarted. Other settings, history and credentials were retained.
- Google `gemini-3.6-flash` passed a small smoke and the first two business cases, then returned `google_429` through Nightshift. The authenticated account quota page showed a free tier with limits unsuitable for repeated full demonstrations. That evidence did not prove the daily cap was exhausted. A later probe also failed; no complete acceptance is claimed for that model.
- The final run selected the account's available `gemini-3.5-flash-lite` quota and used `METERLESS_MIN_REQUEST_INTERVAL_MS=5000`. No billing settings were changed. Quota can still change or be consumed by other clients; spacing within one application process is not a cross-process quota manager.

No further local-model download was needed for the passing cloud run. Direct DeepSeek/OpenAI results were not reused as Nightshift evidence.

## Reproduction and remaining delivery

Follow [NIGHTSHIFT_SETUP.md](NIGHTSHIFT_SETUP.md) for the private environment profile and explicit live command. `scripts/verify_nightshift.ts --connect` creates fresh synthetic records and scripted review/memory state; it makes real model calls and consumes quota. Its default namespace is isolated, while `--workspace` exposes the synthetic run in the demo workspace. The completed recorded run used `--workspace` on port 4316's profile.

The current regression pass reported 189/189 unit/API tests across 15 files, 13/13 H-MEM reference conformance checks, TypeScript checks and the production build passing. Mocked tests and reference conformance are separate from the real live run above. Earlier browser limitations remain recorded in [VALIDATION.md](VALIDATION.md); the entire browser suite is not claimed passing.

Raw environment profiles, credentials and private diagnostics remain local. The public result contains reviewed synthetic metadata. Final application/Runtime footage, slide deck, public repository access, disclosures, team/track details and HackOS submission confirmation remain separate delivery tasks. No NVIDIA/Nemotron execution, NVIDIA award qualification, production capacity or organizer acceptance is claimed.
