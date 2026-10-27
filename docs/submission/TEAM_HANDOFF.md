# Slides and demo handoff

Audience: teammates producing the English presentation and demo video. Use the README for the product overview, [SPONSOR_EXPLANATION.md](SPONSOR_EXPLANATION.md) for sponsor details and [VALIDATION.md](VALIDATION.md) for defensible results.

**Nightshift live acceptance passed using Google `gemini-3.5-flash-lite`.** Use the current live application and matching Runtime records for the sponsor segment. UI footage in fixture mode demonstrates interface behavior separately. Source, evidence and narration are prepared; no final video or deck has been produced.

## Core story

**Problem:** an apparent payment exception can be a duplicate, outdated bank instruction, delayed settlement, unrecorded fee, or simply insufficient evidence.

**User:** an accounts-payable analyst who must explain a finding and hand it to a reviewer.

**Product:** a bounded investigator that retrieves records, an independent verifier that checks the claim, and a human-controlled memory loop that retains useful procedures.

**One-line narration:** “FinTrace explains payment exceptions through traceable evidence, independent financial checks and human-approved investigation memory.”

## Eight-slide outline

| Slide | Heading and content | Visual / presenter evidence |
|---|---|---|
| 1 | **Why this payment does not reconcile** — AP analysts compare invoice, payment, bank, vendor and ledger records; a missing match is not enough to conclude failure. | A simple record-to-review workflow; no invented market size or time-saving statistic. |
| 2 | **From exception to reviewed explanation** — select payment, investigate, inspect sources, review and export. | Real workspace screenshot showing one investigation. Label synthetic data. |
| 3 | **A bounded agent with an independent verifier** — model selects tools; verifier checks financial claims; reviewer approves findings and reusable procedures. | Adapt the README architecture; mark the Nightshift route according to its actual verified status. |
| 4 | **Technical stack and data contract** — React/Vite, Fastify/TypeScript, Zod/Decimal.js, immutable snapshots, PostgreSQL and six typed tools. | Show three example records linked by IDs and an evidence citation. |
| 5 | **Sponsor technologies doing actual work** — Zetaris queries; H-MEM approved recall; Nightshift inference gateway and actual underlying model. | Capture one verifiable artifact per integration. No unsupported NVIDIA/Cursor claims. |
| 6 | **What makes the approach distinctive** — procedures guide evidence order without changing financial truth; failed queries differ from missing records; coverage gaps lead to abstention. | Side-by-side normal, anomaly and insufficient-evidence outputs. |
| 7 | **Validation and product evidence** — four fresh Nightshift-backed synthetic cases, the working memory lifecycle and current automated checks; keep historical provider results separate. | Use exact results from VALIDATION.md. Do not add percentages suggesting real-world accuracy. |
| 8 | **Next steps and limitations** — authorized reviewer feedback, broader sources, independent evaluations, authentication and deployment controls. | Public repository and demo links; acknowledge prototype scope. |

This covers all eight required deck topics: problem/users, solution, workflow/architecture, technical stack, sponsor use, unique sponsor contribution, product visuals and future enhancements. Do not use an old offline deck as evidence of a new live integration.

## Recording preparation

Use a desktop viewport (for example, 1440 × 1000). The browser suite currently passes 59/70 checks, with mobile layout and several UI expectations still failing; see VALIDATION.md. Rehearse the exact recording path before capture.

1. Start the configured live application with Zetaris/PostgreSQL and Nightshift, using `MODEL_PROVIDER=meterless`. Complete NIGHTSHIFT_SETUP.md first.
2. Run `npm run prepare:hmem-demo` to create three immutable synthetic versions in `.local/hmem-demo/`. This preparation does not call a model.
3. Import `01-version.json`, investigate `PAY_DEMO_STALE`, and prepare a real completed investigation for the memory segment. Avoid an already cached direct-provider run.
4. Prepare the normal and insufficient-evidence examples from the README. Keep their actual mode/provider visible.
5. Prepare a Runtime activity view that exposes request/model evidence but no credentials. Keep provider settings, private paths, notifications and personal tabs out of the recording frame.
6. Record application activity and Nightshift activity for the same request. Preserve original recordings privately; editing may shorten waiting periods but must not fabricate an execution.

## Demo script — target 3 minutes 40 seconds

| Time | On-screen action | Suggested narration |
|---|---|---|
| 0:00–0:20 | Title, inbox and one payment | “When a payment does not reconcile, finance teams need to know which records support the explanation. FinTrace investigates synthetic payment records and keeps the evidence inspectable.” |
| 0:20–0:40 | Brief architecture graphic | “Our model selects read-only evidence tools. Zetaris supplies the records, an independent verifier checks the financial claims, and a person reviews the result.” |
| 0:40–1:25 | Start a fresh investigation; show an evidence query and record details | “The investigator checks the relevant sources and responds to missing-evidence feedback. Each finding links back to retrieved records. These are synthetic records, and this run uses the live integration.” Use that last sentence only for a verified live run. |
| 1:25–1:50 | Matching Nightshift Runtime request and app request metadata | “This request passed through Meterless Nightshift and was answered by Google Gemini 3.5 Flash Lite. We match the application's Runtime decision ID with the actual model and provider.” Show matching evidence from the recorded run. |
| 1:50–2:40 | Review findings → Suggest memory → edit and explicitly approve; import version 02 and Update investigation; show recalled memory | “The model proposes a reusable investigation procedure. A reviewer must approve it. On a later version, H-MEM supplies the approved procedure with its provenance. It can guide tool priority, but cannot override the financial verifier.” Shorten waiting time transparently. |
| 2:40–3:05 | Switch to a normal and a coverage-deficient result | “FinTrace distinguishes supported anomalies from normal outcomes and insufficient evidence. A missing record does not automatically become an anomaly.” |
| 3:05–3:25 | Human review and export | “The reviewer keeps control. The exported report retains findings, checks, citations and the memory context used for that investigation.” |
| 3:25–3:40 | Validation/limitations and links | “Our tests exercise synthetic cases and workflow behavior. We have not established real-customer accuracy or cost savings. The source and reproduction steps are available in the public repository.” |

If the lifecycle sequence takes too long, use clearly labeled consecutive clips from the real run. Preserve the visible transition between approval and later recall. Do not imply that background model calls occurred during a fixture run.

## Screenshots and facts to collect

- One useful completed finding with a resolvable citation and source provenance.
- One Zetaris query from the actual live run. App trace IDs are application-generated, not necessarily Zetaris-issued IDs.
- One Nightshift request/result and actual model identity.
- One approved H-MEM procedure plus later contextual recall.
- Normal and insufficient-evidence results, and an exported report.
- Passing current tests with their scope; historical results must retain their original provider and date.

## Claims that must not appear

- “Fully submission compliant” before all checklist gates are complete.
- “Nightshift verified” based on mocked tests, a provider label or a direct OpenAI run.
- “Multi-agent swarm”; the current design is one bounded controller with a planner and independent verifier.
- “Production ready,” “100% financial accuracy,” “real customer data” or invented user/time-saving metrics.
- “H-MEM reduces tokens”; the historical comparison used more tokens and the same request count.
- “NVIDIA-powered” or “built with Cursor” without actual team evidence.

## Delivery to the team lead

Provide the accessible video link, deck link/export, public source link and the exact actual model used. Check the video is 1–4 minutes and all links work signed out. The team lead confirms the roster before the first submission, selects Track 02, reviews pre-existing work, submits in HackOS and retains the success confirmation. Use 6:45 PM Chicago on 27 October as the conservative deadline from the supplied document.
