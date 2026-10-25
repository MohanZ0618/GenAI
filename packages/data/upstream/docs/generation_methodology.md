# Generation methodology

## Design sequence

Generation is deliberately two-stage. First, modular generators create a valid financial world in lifecycle order: employees and vendors, vendor history, purchase orders and lines, invoices and lines, approval events, payments and allocations, double-entry GL journals, bank transactions, and bank statements. The clean validators must pass before a clone is made.

Second, one deterministic primary injector mutates an eligible entity group for each failure case. The injector propagates consequences to the systems that would realistically observe them, records before/after provenance, and emits exact RCA metadata. Hard negatives are then added, statements are rebuilt, cases are assigned by vendor group, questions and evidence packages are generated, and the final quality gate runs.

## Reproducibility

Python's seeded random source drives categorical choices and dates. NumPy's seeded generator drives continuous skewed distributions. ID counters use a seed-derived neutral offset. Stable SHA-256 hashing assigns vendor groups to splits. The implementation does not use Python's process-randomized `hash()`, the network, or wall-clock time.

## Financial population assumptions

- Vendor transaction concentration uses Pareto weights: a small vendor set receives much of the activity.
- PO and invoice line values use department-dependent, bounded log-normal draws.
- Invoice and payment amounts are consequently right-skewed, while very large transactions remain rare.
- Vendor type, terms, currency, method, line counts, taxes, and shipping use weighted categorical draws.
- Default currency mix is 78% USD, 10% EUR, 6% GBP, 4% CAD, and 2% JPY.
- Default payment mix is 66% ACH, 17% wire, 12% check, and 5% virtual card.
- Approximately 62% of invoices are PO-backed. Non-PO invoices include recurring same-vendor/same-amount activity that is legitimate.
- Approval depth rises from auto approval to manager, director, controller, or treasury review as invoice value rises.
- Payment planning intentionally creates both multi-invoice batches and multi-payment invoices. The baseline settles every selected invoice exactly.

These are documented modeling defaults, not estimates learned from private company data.

## Temporal model

PO dates precede linked invoice dates. Receipt follows invoice issuance. Approval events are ordered after receipt. Payment occurs after the final required approval. Bank transaction date is not before payment initiation, and bank posting follows method-specific business-day windows. GL invoice dates follow receipt; payment journals use payment dates.

The default range is 2025-01-01 through 2026-06-30. Vendor creation may predate the activity range. Bank posting can extend beyond a payment date according to clearing rules.

## Accounting model

PO and invoice header totals are derived from line amounts plus tax and shipping. Invoice journals debit expense/tax/freight and credit accounts payable. Payment journals debit accounts payable and credit cash. Bank-fee journals debit fee expense and credit cash. Every journal remains double-entry balanced, including F09, which deliberately posts the wrong amount to both sides.

Bank statements are recalculated after all bank-side mutations. For each account and month:

```text
opening balance + total credits - total debits = closing balance
```

The next statement's opening balance equals the prior statement's closing balance.

## Failure isolation and provenance

Injectors claim primary entity groups so later injectors do not reuse them. Some surface effects intentionally overlap taxonomy symptoms—for example F11 can produce a failed settlement and F15 can produce amount mismatches—but each case has one primary causal mechanism. `mutation_log.jsonl` stores original and mutated values or full row insertion/deletion snapshots. The log is evaluation-private.

Every failure case has an independent signature validator. The quality gate also confirms evidence IDs and affected entities exist. Clean and corrupted versions make any mutation reconstructible.

## Hard negatives

Legitimate cases are drawn or constructed from the same amount, vendor, method, and timing distributions as failures. Examples include a one-percent invoice variance inside a two-percent PO tolerance, a recent submitted ACH without a bank posting, and a net amount difference paired with a balanced fee journal. No-failure cases receive the same question formats and difficulty labels as failures.

## Splitting and challenge test

Cases are grouped by their causal vendor, then a stable hash assigns the whole group. `challenge_fraction` first reserves held-out vendor groups for `challenge_test`; remaining vendor groups follow the configured 60/20/20 train/validation/test proportions. Pairwise overlap statistics are emitted. The full benchmark remains available for graph and data-engineering research, while split case packages support controlled evaluation.

## Quality gate

The release gate requires:

1. all clean structural, financial, temporal, operational-to-GL, and ERP-to-bank rules to pass;
2. all post-injection journals and bank statements to remain balanced;
3. all labels, primary entities, affected entities, and evidence IDs to resolve;
4. every configured failure signature to be observable;
5. zero case and primary-vendor overlap between splits;
6. zero duplicate primary keys.

Post-injection reconciliation findings are expected and reported by rule. They do not fail the release when their fundamental accounting invariants and case signatures are valid.

## Privacy

No source records or external data are used. Vendor names begin with `Synthetic`; employees have role-only synthetic IDs; tax identifiers are one-way hashes of synthetic strings; account and routing values are visibly tokenized. The output must not be treated as real financial data.

