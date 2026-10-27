# Submission-form copy

This file contains English draft text for the actual HackOS form. Field names/limits may differ. Fill team and link placeholders locally. **Do not submit a statement that Nightshift is working until its live acceptance is complete.**

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

TypeScript; React/Vite; Fastify; Zod; Decimal.js; PostgreSQL; Zetaris; Meterless H-MEM; a configurable Nightshift-compatible model provider; Vitest and Playwright. The final planned inference path is Nightshift with an OpenAI cloud model. Actual Runtime compatibility and execution are still awaiting verification.

## Sponsor explanation

Use [SPONSOR_EXPLANATION.md](SPONSOR_EXPLANATION.md). Do not replace it with a generic list of sponsor logos. It distinguishes the working H-MEM feature, historical Zetaris integration, and the outstanding Nightshift requirement.

## What is new / distinctive

FinTrace combines inspectable evidence retrieval, an independent financial verifier and a human-approved memory loop in one review workspace. Remembered procedures can change which evidence is checked first, but cannot change financial facts or override the verifier. The contribution is the application workflow, typed integration boundaries, evidence validation, review controls and traceability; upstream data generation and H-MEM algorithms are credited separately.

## Validation and limitations

The project uses synthetic financial records. Historical live PostgreSQL/Zetaris/direct-OpenAI acceptance matched expected results in 15 runs across nine scenarios, including repeated cases. A separate historical H-MEM/OpenAI local-data experiment matched 12/12 expected outcomes and citation checks. Current offline regression results are in `docs/submission/VALIDATION.md`. These checks demonstrate supported workflow behavior, not real-customer accuracy, statistically significant model advantages or cost savings. Nightshift live validation remains open; production authentication and multi-instance operation are outside the demonstrated prototype.

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
| Public repository | `[PUBLIC GITHUB URL — USER WILL CREATE]` |
| Demo video | `[ACCESSIBLE 1–4 MINUTE VIDEO LINK]` |
| Slide deck | `[ACCESSIBLE DECK LINK]` |
| Colab | Not applicable: local TypeScript application |
| Nightshift evidence | `[PENDING: ACTUAL RUNTIME VERSION, MODEL AND VERIFIED RUN]` |
| Pre-existing original work | `[TEAM-VERIFIED INVENTORY AND DATES]` |

Check all links signed out. Replace placeholders before submitting. The copy is not a substitute for completing the technical requirements.
