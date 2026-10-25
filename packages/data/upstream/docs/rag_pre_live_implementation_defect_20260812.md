# Phase 5B Pre-Live Implementation Defect — Ineligible Anchor Handling

## Original failed attempt

- Run directory: `results/rag/phase5_rag_prelive_v1_0_20260812T042513Z`
- Failure occurred during local query-size estimation, before construction of an OpenAI client or any API request.
- Preserved artifact: the checksum-frozen reasoning prompt only.
- Exception: `missing/ineligible GL journal anchor: JE_0430730`.

## Frozen-spec evidence

The two `gl_entries.csv` lines for journal `JE_0430730` have `posting_date=2026-07-01`. A complete local audit found one additional affected test route: `RCA_000955` anchors journal `JE_0433894`, whose two GL rows also have `posting_date=2026-07-01`. Section 5.2 excludes every GL row after the frozen `2026-06-30` cutoff. Section 12.1 states that a missing or ineligible anchor is a `TECHNICAL_FAILURE` and must not be repaired with ground truth. The corpus and index therefore behaved correctly.

## Root cause

The primary CLI called `build_query` for all routes inside an unguarded workload-estimation expression. Although the frozen protocol defines an ineligible anchor as a terminal per-case technical outcome, this implementation path raised the anchor exception at run scope and aborted all cases.

## Correction

- Added a typed `AnchorResolutionError` without changing query construction.
- The retrieval runner now checkpoints an ineligible anchor as `ANCHOR_TECHNICAL_FAILURE`, with zero query-embedding and retrieval operations, and continues other routes.
- The primary runner creates a terminal technical prediction for each affected route and excludes those routes only from context-size/generation calls.
- Pre-live artifacts report the technical case explicitly and verify that all 439 routes are accounted for.
- The anchor is not substituted, repaired, embedded, retrieved, or supplied to the reasoner.

This is an implementation-defect correction under frozen specification Section 33, not a methodology change or protocol deviation. The original failed attempt remains preserved. A new run ID is required for reproduction.

## Verification

The added regression test proves that an ineligible anchor produces a checkpointed terminal technical result, makes zero API-client calls for that route, and does not prevent a valid peer route from completing retrieval. A complete local audit accounts for 439 test routes: 437 have eligible query anchors and two (`RCA_000902`, `RCA_000955`) have the frozen terminal anchor outcome. After correction, 60 Phase 5 tests and all 169 repository tests pass.
