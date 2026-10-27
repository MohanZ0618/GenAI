# Nightshift setup and acceptance

**Status: adapter implemented; real Runtime validation pending.** This guide does not assert the Runtime is installed or that OpenAI routing works on this machine. Use the official [Nightshift site](https://meterless.ai/) and the Participant Setup Guide in HackOS for the current edition and installation steps.

## Target route

`FinTrace → Meterless Nightshift → configured OpenAI model → Nightshift → FinTrace`

Use a Runtime edition that exposes a local/server OpenAI-compatible endpoint. A browser job page alone is not evidence that an application API endpoint is available. Configure an actual OpenAI cloud provider/model in Nightshift if supported by that installed version. If unsupported, report the exact limitation and agree a different underlying model before proceeding; do not silently bypass the Runtime.

## Configuration

Keep cloud credentials inside Nightshift's provider settings for this route. Copy its actual Runtime endpoint, Runtime credential and available model ID into the ignored FinTrace `.env.local`:

```dotenv
FINTRACE_MODE=local-model
MODEL_PROVIDER=meterless
METERLESS_BASE_URL=http://127.0.0.1:8088/v1
METERLESS_RUNTIME_TOKEN=<runtime credential>
METERLESS_MODEL=<actual runtime model ID>
FINTRACE_STORAGE_DIR=.local/nightshift-check
```

The address is this application's adapter default, shown as an example; replace it with the endpoint exposed by your installed Runtime. Do not paste the OpenAI API key into `METERLESS_RUNTIME_TOKEN`. Do not assume that an OpenAI model ID and a Nightshift routing alias are interchangeable.

1. Remove conflicting shell environment overrides, then run `npm run preflight -- --live` in the configured `local-model` profile. This makes a real, potentially billable request; no PostgreSQL/Zetaris connection is needed for this isolated check.
2. Confirm `checks.model.provider` is `meterless`. Inspect `returnedModel`; if it is absent or only a routing alias, use the Runtime's own record to identify the actual model. Never invent that identity.
3. Run one fresh local-model investigation. Confirm valid typed output, supported financial findings and resolved citations. Verify the request exists in Nightshift's own activity/receipt view.
4. Request a memory draft from a completed investigation and confirm that this second model operation also passes through Nightshift.

## Full sponsor-connected run

Configure PostgreSQL and Zetaris using [INTEGRATIONS.md](../INTEGRATIONS.md). Set `FINTRACE_MODE=live`, retain `MODEL_PROVIDER=meterless`, and restart the app. Existing stopped containers/data can be reused; do not delete volumes. Then run:

```powershell
npm run preflight:submission
npm run preflight:submission -- --live
npm run verify:business -- --connect --repeat=1
```

The first command makes no network calls. A wrong mode or direct provider is rejected even with `--live`, before contacting services. Configuration success does not prove the endpoint belongs to Nightshift; manually correlate its Runtime record. The business script includes anomaly, normal and evidence-gap cases and stores reports under ignored `.local/` directories.

Then perform the UI sequence in [TEAM_HANDOFF.md](TEAM_HANDOFF.md). Fresh run IDs, runtime receipts and actual source query activity are required; do not reuse a completed direct-OpenAI investigation as a Nightshift example.

## Evidence to retain locally

- Runtime version and endpoint origin (no token); configured model and actual answering model.
- A successful preflight result, fresh investigation ID and timestamps that match Runtime activity.
- Successful evidence-tool queries through Zetaris and final source citations.
- Anomaly, normal and insufficient-evidence results, including failures encountered during validation.
- A memory suggestion request followed by explicit human approval and later recall.
- A sanitized screenshot or recorded segment showing the Runtime request and result.

Publish a short sanitized summary only after review. Raw exports can include source data or identifiers and remain local by default. Do not show provider settings or keys during recording.

## Failure handling and interpretation

| Symptom | Required response |
|---|---|
| Runtime refuses authentication | Check the Runtime token; do not substitute a cloud key. |
| Model ID not recognized | Use a model exposed by the actual Runtime; do not guess an alias. |
| Empty or malformed output | Inspect sanitized request status; the adapter has a bounded retry and then fails. |
| Unknown tool or invalid citation | Treat as a failed model contract; never accept a repaired financial answer silently. |
| Runtime offline or timeout | Fail visibly; do not redirect to direct OpenAI or fixture. |
| Preflight succeeds but investigation fails | Fix and rerun the actual workflow; preflight is not end-to-end acceptance. |
| Models hidden behind an alias | Obtain the actual model from the Runtime record; mark unknown if unavailable. |

The provider sends the output schema in the system prompt and validates results locally without assuming strict JSON-schema parameter support on every gateway model. Contract tests are in `tests/meterless-submission.test.ts`. These tests prove adapter behavior under mocks, not third-party compatibility.
