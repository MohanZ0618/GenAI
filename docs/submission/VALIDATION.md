# Submission preparation validation

Date: 27 October 2026. This record separates the checks performed during English submission preparation from earlier experiments.

## Current preparation pass

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
| Real Nightshift/OpenAI route | Not run; requires installed/configured Runtime and real request evidence |
| Full live Zetaris + Nightshift investigation | Not run in this preparation pass |
| Public GitHub, final slides, video and HackOS | Team actions pending |

An HTTP/JSON trace marked succeeded reports transport/JSON parsing; operation-level schema and citation checks must also pass. A returned model name is provider-reported metadata. Confirm the actual route/model with Nightshift activity rather than assuming a routing alias is the underlying model.

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

## Required final evidence

Complete [NIGHTSHIFT_SETUP.md](NIGHTSHIFT_SETUP.md), capture real Zetaris/Nightshift activity, demonstrate H-MEM, and rerun fresh synthetic scenarios. Record failures as well as successes. Publish only a sanitized summary and reviewed media; keep credentials and raw runtime reports outside the source package.
