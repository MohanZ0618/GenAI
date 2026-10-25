# Data contract and provenance

The shipped examples are synthetic. FinRCA source is pinned to `76c93ec32536e29826e2ab9e68b58e0351410bc7`; its original license is retained in `packages/data/upstream/LICENSE`. The upstream generator's quality gate passed before packet extraction. Its source, generation seed and quality report are recorded in `data/PROVENANCE.json`.

Preparation selects 12 cases from each of F06, F11, F12, F14 and NO_FAILURE: eight per group for development and four for the held-out reference set. Selected original cases use disjoint vendor groups. Ten additional coverage stress packets derive from two development packets; they are not independent random samples and must not be counted as independent financial scenarios.

The application sees only the nine financial tables and an observation manifest. Evaluation labels live under `evaluation/labels`; the server serves only the web build, not the repository root. Case names and identifiers do not contain ground-truth failure labels. Payment queue symptoms are snapshot triage indicators, not verified findings.

## Reproduce preparation

Prepared packets are included, so generation is optional. With Python 3.11+ and the generator's compatible data dependencies available:

```powershell
python scripts/prepare_data.py
```

The script executes the pinned generator, checks its quality gate, extracts review packets and writes schema metadata and evaluator labels. It uses `.local/prepared-upstream` as build output. `scripts/fetch_upstream.py` downloads the fixed source only into a previously absent upstream directory; it refuses to overwrite an existing checkout.

## Import

Download the template bundle from the app. Supply one JSON object `{manifest, files}`, or select a manifest JSON with these CSVs:

`vendors.csv`, `vendor_change_log.csv`, `invoices.csv`, `payments.csv`, `payment_allocations.csv`, `gl_entries.csv`, `bank_transactions.csv`, `bank_statements.csv`, `audit_log.csv`.

Headers are the exact upstream columns recorded in `packages/data/src/schema.json`. Header order may differ; missing, duplicate or extra columns are rejected. Empty tables retain their headers. Monetary strings use plain decimal notation with at most two fractional digits. Currency values use uppercase three-letter codes. Naive source timestamps are interpreted as UTC; dates are displayed in UTC to avoid host-timezone shifts. Source IDs are preserved; payment allocations use their composite upstream key.

The manifest supplies `name`, `asOf`, `currency`, `clearingDays`, coverage for each table (`status`, `from`, `to`), and optionally `focusPaymentIds` for a review queue. Clearing days count weekdays, excluding weekends; holidays are not modelled. This is a simplified declared policy, not a universal bank rule. The prepared packets use a conservative ten-business-day window.

Coverage must be honest. Use `partial` or `unavailable` when extracts are incomplete. A successful empty bank lookup alone cannot establish absence. Complete coverage must include the payment date through the observation cutoff. Each packet retains source statement aggregates for the relevant accounts; those statements can include other vendors, so the extracted vendor subset is not asserted to balance a whole bank statement.

All nine tables are validated before import activation. Corrected imports are new content hashes, and source snapshots remain immutable. Unknown FX conditions and mismatched currencies remain unresolved; FinTrace does not infer exchange rates.
