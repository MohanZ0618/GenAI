# FinRCA-Bench v1

FinRCA-Bench is a deterministic, synthetic benchmark for evaluating financial reconciliation and root-cause-analysis systems. It approximates selected enterprise accounts-payable, accounting, payment, and bank-reconciliation workflows while retaining exact causal lineage for every injected failure.

It is not a claim to represent every enterprise finance environment. All organizations, people, identifiers, transactions, and amounts are generated; bank and routing values are tokens rather than usable financial identifiers.

## Research motivation

Many reconciliation tests reduce the task to finding unequal amounts. FinRCA-Bench instead evaluates whether a system can identify a discrepancy, link records across systems, retrieve decisive evidence, reconstruct event order, distinguish a failure from a legitimate exception, identify the true cause, and recommend a financially coherent resolution.

The benchmark supports anomaly detection, record linkage, reconciliation, evidence retrieval, temporal and multi-table reasoning, accounting reasoning, explanation evaluation, and resistance to misleading evidence.

## Simulated financial workflow

```text
Vendor master and history
        ↓
Purchase order → Invoice → Approval events → Payment and allocations
                                ↓                 ↓
                           General ledger     Bank transaction
                                                  ↓
                                           Bank statement
```

ERP, procurement, workflow, vendor-management, payment-processor, GL, reconciliation-platform, and bank observations use different identifiers and event times. `audit_log.csv` and `causal_edges.csv` preserve the cross-system history needed for difficult investigations.

## Quick start

Python 3.11 or newer is required.

```bash
python -m pip install -r requirements.txt
python generate_finrca_bench.py --config config.yaml
```

The smaller development build exercises the complete pipeline and every failure class:

```bash
python generate_finrca_bench.py --config config.yaml --seed 42 --scale small
```

To generate and validate without writing output:

```bash
python generate_finrca_bench.py --config config.yaml --scale small --validate-only
```

The command exits nonzero if the quality gate fails and prints the deterministic dataset hash.

## Default scale

`config.yaml` produces 500 vendors, 5,000 purchase orders, 8,000 invoices, 6,000 baseline payments, 100 cases for each of 15 failure categories, and 750 legitimate/no-failure cases across 18 months. Counts, date ranges, distributions, tolerances, clearing windows, split proportions, and the seed are configurable.

Generation starts with a completely valid financial world. The clean world is validated before the benchmark copy is mutated. Monetary arithmetic uses `Decimal` and currency-specific quantization.

## Tables

The model-visible data includes:

- `vendors.csv` and `vendor_change_log.csv`
- `purchase_orders.csv` and `po_lines.csv`
- `invoices.csv` and `invoice_lines.csv`
- `approval_events.csv`
- `payments.csv` and `payment_allocations.csv`
- `gl_entries.csv`
- `bank_transactions.csv` and `bank_statements.csv`
- `employees.csv` and `audit_log.csv`

`payment_allocations.csv` supports batched payments, split payments, and partial settlement. GL output uses balanced double-entry journals. Bank statements are chained by account and satisfy opening balance + credits − debits = closing balance. See [schema](docs/schema.md) and the [data dictionary](docs/data_dictionary.md).

## Failure taxonomy

Exactly 15 primary categories are implemented as independent deterministic injectors:

1. F01 duplicate invoice
2. F02 PO/invoice amount mismatch
3. F03 quantity mismatch
4. F04 incorrect vendor association
5. F05 payment without a valid invoice
6. F06 invoice paid twice
7. F07 partial payment/residual balance
8. F08 approval workflow failure
9. F09 GL posting mismatch
10. F10 wrong accounting period
11. F11 vendor master change conflict
12. F12 ERP payment missing from bank
13. F13 bank transaction missing from ERP
14. F14 bank/ERP amount mismatch
15. F15 incorrect payment-to-bank matching

The same surface symptom can have different causes. For example, no bank settlement can mean a transmission failure, a stale vendor account, or a legitimate pending clearing window. The full precondition, mutation, propagation, evidence, resolution, hard-negative, and test design is in [failure_taxonomy.md](docs/failure_taxonomy.md).

## Legitimate exceptions and hard negatives

No-failure cases include weekend ACH clearing, normal check delays, allowed PO tolerances, scheduled split payments, multi-invoice batches, paid-on-due-date activity, separately accounted bank fees, recent pending settlements, net-settlement differences with fee accounting, credit memos, invoice cancellations, payment reversals, documented FX conversion, pre-invoice terms changes, and cost-center splits. These cases intentionally resemble failures so amount inequality or missing-one-day rules do not perform well by construction.

## Ground truth and questions

`rca_ground_truth.jsonl` stores the primary and affected entities, symptom, exact root cause and category, required evidence tables and IDs, expected resolution, systems, severity, difficulty, reasoning hops, scenario variant, and split.

`causal_edges.csv` stores graph-level lineage. `benchmark_questions.jsonl` provides five styles per case: detection, root cause, evidence, resolution, and full investigation. Expected answers are evaluation labels and should not be supplied to the system being evaluated.

`internal/mutation_log.jsonl` contains before/after provenance for every mutation or inserted/deleted record. It must remain hidden during normal model evaluation.

## Output layout

```text
data/
├── raw_clean/                  # Valid pre-injection tables
└── benchmark/
    ├── full/                   # Complete corrupted model-visible tables
    ├── train/
    ├── validation/
    ├── test/
    ├── challenge_test/
    ├── rca_ground_truth.jsonl
    ├── benchmark_questions.jsonl
    ├── causal_edges.csv
    ├── failure_manifest.csv
    ├── dataset_quality_report.json
    ├── dataset_statistics.md
    ├── resolved_config.yaml
    └── internal/mutation_log.jsonl
```

Each split directory contains split labels, questions, a failure manifest, case IDs, and `case_entity_records.jsonl`, a model-visible evidence package containing only records relevant to those cases.

## Dataset splits and leakage control

Cases are never split by individual row. A stable seed-dependent hash assigns the case's vendor group to train, validation, test, or challenge test, so a primary vendor group cannot cross split boundaries. Challenge test uses separately held-out vendor groups. The quality report records pairwise case-ID and primary-vendor overlap checks.

Researchers should tune prompts, thresholds, and retrieval on train/validation only. Test and challenge labels, expected answers, causal edges, and mutation logs should be withheld during inference.

## Validation and tests

The clean-data gate checks schemas and IDs, PO and invoice arithmetic, payment allocations, paid balances, double-entry journals, bank statement math and continuity, causal chronology, operational-to-GL agreement, and ERP-to-bank matching.

After injection, separate checks require all journals and statements to remain valid, every label and evidence ID to resolve, all 15 failure signatures to be observable, primary-vendor split leakage to be zero, and duplicate primary keys to be absent. Expected reconciliation findings in the corrupted data are reported rather than mistaken for generator defects.

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```

The suite also checks same-seed identity and different-seed divergence.

## Recommended experimental use

Report detection and RCA performance separately. At minimum stratify results by failure category, difficulty, reasoning hops, and split. Evidence evaluation should require both appropriate tables and supporting IDs; RCA evaluation should distinguish the observed symptom from the underlying causal category. Score no-failure cases explicitly to measure false positives.

Avoid placing `rca_ground_truth.jsonl`, expected answers, causal edges, or `internal/mutation_log.jsonl` in the inference context. Use `case_entity_records.jsonl` or an equivalent retrieval layer as model input.

## Reproducibility

The seed controls Python and NumPy random sources, identifier offsets, distributions, mutations, cases, and splits. No wall-clock timestamps or network data enter generation. The quality report contains a SHA-256 hash of canonical tables and cases.

### Frozen Rules/SQL Phase 2 baseline

Install the declared dependencies, then run the complete frozen-baseline workflow from the repository root with one command:

```bash
python3 -m src.rules_sql.cli run --data-root data/benchmark --output-root results/rules_sql --run-id <new_unique_run_id>
```

The command verifies the frozen-spec checksum, runs the baseline unit/integration tests, evaluates all 12 frozen F01 validation configurations, locks the selected parameters, writes a pre-test audit, performs inference on test routing fields, saves immutable raw predictions, and only then opens evaluator-only test labels to compute the reports. Run IDs must be unique; existing result directories and raw prediction files are never overwritten.

The baseline-specific tests can be run without evaluation using:

```bash
python3 -m pytest tests/rules_sql -q
```

### Frozen classical ML Phase 3 baseline

The Phase 3 runner verifies the frozen ML specification and feature-registry checksums, runs the leakage and feature-pipeline tests, creates train/validation matrices, evaluates the exact 22-configuration validation grid, serializes and hashes the winner, saves held-out predictions before opening test labels, and produces the complete Rules/SQL comparison and evaluation report:

```bash
python3 -m src.classical_ml.cli run --data-root data/benchmark --output-root results/classical_ml --run-id <new_unique_run_id>
```

Run IDs are immutable and must be unique. To independently recreate predictions from a locked run without opening evaluator labels:

```bash
python3 -m src.classical_ml.cli verify --data-root data/benchmark --run-dir results/classical_ml/<run_id>
```

The Phase 3 feature-pipeline tests can be run separately with:

```bash
python3 -m pytest tests/classical_ml -q
```

### Frozen Direct LLM Phase 4 baseline

Phase 4 is a direct-context reasoning baseline. Its packet builder reads the 14 operational tables and whitelisted case/primary routing fields only. It deliberately does not use the repository's ground-truth-derived `case_entity_records.jsonl`, retrieval, embeddings, tools, Rules/SQL outputs, or classical-ML outputs.

Install the declared dependencies and build/audit all 439 held-out packets without making an API call:

```bash
python3 -m src.direct_llm.cli prepare \
  --data-root data/benchmark \
  --output-root results/direct_llm \
  --run-id phase4_direct_llm_preflight_v1_0_<timestamp>
```

The single prompt is locked a priori. Before held-out execution, run the pre-registered 32-case validation stability protocol (96 paid calls) with the API key supplied only through the environment:

```bash
export OPENAI_API_KEY='<set outside the repository>'
python3 -m src.direct_llm.cli stability \
  --preflight-dir results/direct_llm/<preflight_run_id> \
  --output-root results/direct_llm \
  --run-id phase4_direct_llm_stability_v1_0_<timestamp> \
  --execute-api
python3 -m src.direct_llm.cli audit \
  --preflight-dir results/direct_llm/<preflight_run_id> \
  --stability-dir results/direct_llm/<stability_run_id>
```

Only a passing final audit authorizes the one held-out run. This command is sequential, checkpoints every case, and resumes an interrupted run without rerunning terminal responses:

```bash
python3 -m src.direct_llm.cli run \
  --preflight-dir results/direct_llm/<preflight_run_id> \
  --output-root results/direct_llm \
  --run-id phase4_direct_llm_v1_0_<timestamp> \
  --execute-api
```

Evaluate preserved outputs offline with no additional API call:

```bash
python3 -m src.direct_llm.cli evaluate \
  --data-root data/benchmark \
  --preflight-dir results/direct_llm/<preflight_run_id> \
  --run-dir results/direct_llm/<held_out_run_id>
```

Run the Phase 4 non-API tests separately with:

```bash
python3 -m pytest tests/direct_llm -q
```

## Known limitations

- The benchmark models a selected AP-to-bank lifecycle, not payroll, receivables, treasury trading, tax filing, or every ERP configuration.
- Currency values are represented at native precision, but v1 does not maintain a full market-rate ledger or consolidation book.
- Approval policies and accounting accounts are representative synthetic policies, not advice or a universal standard.
- Case-scoped split packages favor controlled evaluation over reconstructing an entire production data lake.
- Synthetic distributions approximate realistic skew but are not calibrated from private enterprise records.

Implementation and design assumptions are detailed in [generation_methodology.md](docs/generation_methodology.md).
