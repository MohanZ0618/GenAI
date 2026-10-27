# Submission-form copy

This file contains English draft text for the actual HackOS form. Field names/limits may differ. Fill team and media-link placeholders locally. Nightshift live acceptance passed on 27 October 2026; its source and materials were published and the public source passed fresh-clone verification.

## Project name

FinTrace

## Tagline

Investigate payment exceptions with traceable evidence, independent checks and human-approved memory.

## Primary track

Track 02 — The Agent That Can Explain Why

## Short description

FinTrace helps accounts-payable teams investigate payment exceptions across invoices, payments, bank records, vendor changes and ledger entries. A bounded agent retrieves evidence, an independent verifier checks financial claims, and a reviewer approves findings and reusable investigation procedures. Every result exposes its supporting records and evidence gaps.

## Problem and intended users

Accounts-payable analysts often need to reconcile conflicting records before deciding why a payment failed or whether an apparent exception is actually normal. A missing bank match alone is not enough: settlement timing, source coverage, vendor instructions and ledger entries can change the explanation. FinTrace gives finance-operations reviewers one workspace to investigate those relationships and retain a reviewable evidence trail.

## Solution and workflow

The user selects a payment from an immutable data snapshot. The model planner chooses among six read-only evidence tools, guided by verification feedback and relevant approved procedures. In live mode, evidence is retrieved through Zetaris. A separate deterministic verifier checks amounts, relationships, timing and source coverage, then returns a supported anomaly, a supported normal result, or insufficient evidence. The reviewer inspects citations, records a decision, optionally approves a reusable procedure in Meterless H-MEM, and exports the investigation.

## Key features

- Immutable data versions with validated imports and source coverage.
- Bounded tool selection and feedback-driven investigation.
- Evidence-linked financial checks and explicit abstention when evidence is insufficient.
- Human review, model-proposed memory drafts, approval, scoped recall and deactivation.
- Recorded model/evidence activity and HTML, JSON and CSV exports.
- Offline fixture mode for reproducible evaluation without credentials.

## Technical stack

TypeScript; React/Vite; Fastify; Zod; Decimal.js; PostgreSQL; Zetaris; Meterless H-MEM; Meterless Nightshift; Vitest and Playwright. The verified live inference path is FinTrace → Nightshift → Google `gemini-3.5-flash-lite`. Evidence queries pass through Zetaris to PostgreSQL source views, with immutable-snapshot checks.

## Sponsor explanation

Use [SPONSOR_EXPLANATION.md](SPONSOR_EXPLANATION.md). It describes the verified Zetaris evidence queries, H-MEM review-to-memory feature, Nightshift inference route and separate three-feed USL/data-quality demonstration, with links to actual results.

## What is new / distinctive

FinTrace combines inspectable evidence retrieval, an independent financial verifier and a human-approved memory loop in one review workspace. Remembered procedures can change which evidence is checked first, but cannot change financial facts or override the verifier. The contribution is the application workflow, typed integration boundaries, evidence validation, review controls and traceability; upstream data generation and H-MEM algorithms are credited separately.

## Validation and limitations

The project uses synthetic financial records. Four fresh live investigations through PostgreSQL, Zetaris, Nightshift and Google `gemini-3.5-flash-lite` matched expected normal, anomaly and insufficient-evidence outcomes. All 20 evidence queries succeeded and all 17 business model calls matched Runtime explanations. Model-generated memory drafting, scripted synthetic review/approval, application-wrapper persistence and later recall passed. The current unit/API suite passed 189 tests and H-MEM reference conformance passed 13 checks; the complete browser suite still has 11 known layout/UI failures. See [VALIDATION.md](VALIDATION.md). These checks demonstrate the selected workflow, not real-customer accuracy, model superiority, cryptographically signed receipts or cost savings. Production authentication and multi-instance operation remain outside the demonstrated prototype.

## Pre-existing components disclosure — team must review

The project includes FinRCA-AI-Bench source/data-generation components pinned to commit `76c93ec32536e29826e2ab9e68b58e0351410bc7` under MIT, and the Meterless H-MEM reference engine pinned to commit `1742dec56a66e58eef9dda2d2b865823758ca8cd` under Apache-2.0. Their notices and licenses are preserved. The demonstration data is synthetic; the team adapted/generated review packets and application-specific examples.

Before submission, append a truthful inventory of **FinTrace code, product work and prepared data that existed before 22 October 2026, 00:00 UTC**. Some project research/setup dates precede the build window; do not claim all work began during the event without reviewing the actual history. List the new work performed during the build window separately. Do not guess dates or omit an existing component merely because it was copied to a new repository.

## Future enhancements

Validate with authorized finance reviewers and appropriately permissioned real datasets; expand supported workflows and source integrations; evaluate calibrated semantic retrieval; add production authentication and deployment controls; run independent held-out comparisons against simpler baselines.

## Fields the team must complete

| Field | Value |
|---|---|
| Team name | `[TEAM NAME]` |
| Team members | `[CONFIRMED ROSTER — CHECK BEFORE FIRST SUBMISSION]` |
| Public repository | https://github.com/MohanZ0618/GenAI — source published and fresh-clone installation, build, tests and example workflows verified; see [VALIDATION.md](VALIDATION.md) |
| Demo video | `[ACCESSIBLE 1–4 MINUTE VIDEO LINK]` |
| Slide deck | `[ACCESSIBLE DECK LINK]` |
| Colab | Not applicable: local TypeScript application |
| Nightshift evidence | Official Mac M1-M4 0.92.7 → Google `gemini-3.5-flash-lite`; four synthetic cases and memory lifecycle passed; see [NIGHTSHIFT_ACCEPTANCE.md](NIGHTSHIFT_ACCEPTANCE.md) |
| Pre-existing original work | `[TEAM-VERIFIED INVENTORY AND DATES]` |

Check all links signed out. Replace placeholders before submitting. The copy is not a substitute for completing the technical requirements.
