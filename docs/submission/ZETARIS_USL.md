# Zetaris USL and data-quality evidence

Prepared on 27 October 2026 for FinTrace's separate Zetaris scoring demonstration. This document follows the team's supplied scoring-summary checklist: a use case with at least three sources, two or three exploration queries per source, one deployed USL with DDL, two or three USL queries, an executed Zetaris data-quality rule, and three reflections. It is an evidence package, not an organizer eligibility decision.

**Verified:** three registered simulated feeds, one deployed three-table USL, six source-exploration queries, three USL queries, a matching hand-written comparison and seven executed native data-quality rules. The exact SQL and returned records are included below.

## Use case and scope

An accounts-payable analyst needs to compare a recorded payment with its observed bank settlement and identify the applicable supplier review policy. Those feeds can differ in identifiers, field names, types and timing. A shared semantic contract makes their relationships inspectable before a reviewer relies on a combined result. This compact exercise does not replace the application's wider invoice, allocation and ledger investigation.

All records in this demonstration are synthetic. The sources model different operational feeds; they do not establish connections to real ERP, bank or supplier systems. Evaluation answers, benchmark labels and mutation logs are excluded from the semantic inputs.

This demonstration complements the working FinTrace application. The application's existing investigation tools continue to retrieve immutable payloads through the `FINTRACE` datasource and verify their snapshot hashes. The scoring USL is a separate integration exercise; it is not silently substituted for that evidence contract. A passing data-quality rule is also separate from a finding that a payment is financially correct.

The platform setup and direct-DeepSeek investigation checks are recorded in [VALIDATION.md](VALIDATION.md). The separate [Nightshift acceptance](NIGHTSHIFT_ACCEPTANCE.md) passed through Google `gemini-3.5-flash-lite`; the USL work itself does not exercise that inference route.

## Source contracts and provenance

The deterministic assets and their hashes are recorded in the [source manifest](../../data/zetaris-scoring/source-manifest.json); field meanings and quality expectations are in the [data dictionary](../../data/zetaris-scoring/data-dictionary.json). The scoring dataset is named **FinTrace USL scoring synthetic sample**, with ID `ds-f9be2f5bab44f603` and observation cutoff `2026-10-22T23:59:59Z`.

| Feed | Registered transport and input | Sample grain | Actual rows queried |
|---|---|---|---:|
| ERP payment facts | `FINTRACE.payments`, the existing PostgreSQL connector over the separate scoring dataset; the [ERP preview](../../data/zetaris-scoring/erp_payments_preview.csv) is for inspection only and is not another registered source | `dataset_id` + `payment_id` | 9 |
| Bank settlement observations | `FINTRACE_BANK.bank_settlements`, a separately registered [CSV feed](../../data/zetaris-scoring/bank_settlements.csv) | `bank_transaction_id`; reference/currency is unique in this sample | 7 |
| Supplier control policies | `FINTRACE_POLICY.vendor_policy`, a REST table reading the local HTTP service's [policy JSON](../../data/zetaris-scoring/vendor_policy.json) as `{data: policies}` | One active policy per vendor/currency/effective interval in the sample | 8 |

These are three different connector/feed paths, not three independent real-world datasets. The ERP and bank mock records share a synthetic scenario generator. The supplier policies are new, uniform demonstration assumptions rather than learned financial targets or evaluation answers. The local service simulates a supplier-control API; it does not contact an external supplier. No additional source is counted for the ERP preview file, the nine existing PostgreSQL views, or the policy's JSON file behind its HTTP service.

The bank join uses payment reference **and currency**. The policy join uses vendor, currency and the payment date within the inclusive effective interval. Both are left joins: absent bank observations remain `NULL`, and a returned bank transaction remains different from a posted settlement. The sample's unique bank-reference/currency pairs and non-overlapping policies avoid multiplying payment rows. A larger feed would need explicit handling of partial settlements and historical policy versions.

Amount strings are converted to `DECIMAL(18,2)` for arithmetic. Thresholds are currency amounts; the example does not convert exchange rates. The policy's ten-day grace value is an illustrative calendar-day parameter and is not a replacement for the application's existing business-day clearing logic. An amount difference alone does not prove a bank fee, and a missing bank row alone does not establish a failed payment.

## Deployed USL and its DDL

The deployed model is **`lightning.metastore.fintrace_scoring.payment_review`**, with three activated tables. The local installation returned model ID `873`; object IDs are instance-specific. The [complete setup SQL](../../data/zetaris-scoring/01_setup.sql) contains the three-table `COMPILE USL ... DEPLOY NAMESPACE ... DDL` statement, source registrations, activation mappings and custom rule definitions. The [first-run response](../../data/zetaris-scoring/evidence/setup-first-run.json) records actual creation and activation; the [subsequent setup response](../../data/zetaris-scoring/evidence/setup-result.json) records reuse of the same owned deployment.

| USL table | Source mapping | Contract and relationship |
|---|---|---|
| `vendor_policy` | Explode the REST response's `data` array; cast amounts, dates, integer and boolean fields | Primary key `vendor_id`; the sample has one active policy per vendor |
| `payments` | Extract named JSON fields from `FINTRACE.payments`, restricted to the scoring dataset and its nine payment IDs | Primary key `payment_id`; `vendor_id` references the policy table; amount is `DECIMAL(18,2)` |
| `bank_settlements` | Read the separate CSV and resolve reference/currency to a payment ID | Primary key `bank_transaction_id`; `payment_id` references payments; bank status remains explicit |

The installed CSV reader inferred the amount column as a double; activation explicitly normalizes it to `DECIMAL(18,2)`. REST amount/date strings are also cast explicitly. The deployed schema and activation expressions are retained in the setup responses. Currency and effective dates remain explicit query conditions; the vendor-ID foreign key alone does not enforce those conditions.

Send the multi-table `COMPILE` statement as one request. Do not mechanically split the setup file at every semicolon: semicolons inside the embedded DDL belong to the same compilation operation. The setup script handles this boundary, while the application's investigation adapter remains restricted to SELECT queries.

## Exploration queries: two per source

The [exploration SQL](../../data/zetaris-scoring/02_exploration.sql) contains all six queries. Each query ID has its SQL, HTTP status, elapsed time and actual returned rows in [results.json](../../data/zetaris-scoring/results.json). All six returned HTTP 200.

| Query ID | Question answered | Actual result |
|---|---|---|
| `ERP-1` | Which payment facts belong to the scoring scope? | 9 payment rows, all USD; fields and amounts matched the inspectable synthetic input |
| `ERP-2` | How are those payments grouped by vendor and currency? | 8 vendor/currency groups; the duplicate-payment vendor has two separate payment IDs totaling USD 2,000 |
| `BANK-1` | Which references were observed and what is their bank status? | 7 bank records, with separate posted/returned statuses |
| `BANK-2` | What counts and amounts belong to each bank status? | 6 posted observations totaling USD 5,310; 1 returned observation of USD 900 |
| `POLICY-1` | What effective supplier thresholds does the REST feed provide? | 8 vendor policies, effective 1 August–31 December 2026 |
| `POLICY-2` | Are the policies unique by vendor and what thresholds apply? | 8 rows and 8 distinct vendors; USD 1,000 review threshold and USD 25 variance threshold |

The two payment IDs for one vendor are separate disbursement records, not duplicated primary keys. This compact three-source exercise does not include enough invoice/allocation evidence to conclude that the vendor was overpaid.

## Queries through the USL

The [USL query SQL](../../data/zetaris-scoring/03_usl_queries.sql) contains three queries over the deployed semantic tables, followed by the hand-written comparison. All three USL queries returned HTTP 200; [results.json](../../data/zetaris-scoring/results.json) retains the full responses.

| Query ID | Purpose | Actual result |
|---|---|---|
| `USL-1` | Join each payment to its bank observation and effective supplier policy | 9 rows and 9 unique payment IDs; all 9 have an effective policy match; no lost or multiplied payments |
| `USL-2` | Separate posted, returned and absent bank observations | 3 USD groups, shown below |
| `USL-3` | Identify payments above the illustrative policy's manual-review threshold | 2 payments of USD 1,200 exceed USD 1,000; this requests review rather than establishing a financial anomaly |

`USL-2` returned:

| Bank observation | Payments | ERP amount, USD | Posted bank amount, USD | Posted observed variance, USD |
|---|---:|---:|---:|---:|
| Posted | 6 | 5,350.00 | 5,310.00 | 40.00 |
| No bank observation | 2 | 1,500.00 | `NULL` | `NULL` |
| Returned | 1 | 900.00 | `NULL` | `NULL` |

The USD 40 posted variance consists of two USD 20 differences. Each is below the sample's USD 25 variance-review threshold; the two USD 1,200 payments appear in `USL-3` because of the separate amount threshold. Neither the missing observations nor the returned transaction are silently treated as a zero settlement. These are observations for review, not proof of fraud, a fee or a final financial loss.

Verification independently compared the returned rows with the CSV/JSON fixtures and decimal arithmetic, checked one-to-one join behavior in this scope, and preserved missing/returned variance as `NULL`.

## Executed native Zetaris data quality

The setup registers the following native row-level rule, then executes it against the USL table:

```sql
REGISTER DQ positive_payment_amount
TABLE lightning.metastore.fintrace_scoring.payment_review.payments
AS payment_amount IS NOT NULL AND payment_amount > 0;

RUN DQ positive_payment_amount
TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

SHOW DQ INVALID RECORD positive_payment_amount
TABLE lightning.metastore.fintrace_scoring.payment_review.payments;
```

The second custom rule, `policy_threshold_valid`, requires non-null, non-negative review/variance thresholds and grace days, plus a valid effective-date interval. Its exact predicate is in [01_setup.sql](../../data/zetaris-scoring/01_setup.sql). The [quality SQL](../../data/zetaris-scoring/04_quality.sql) and [execution results](../../data/zetaris-scoring/results.json) preserve the actual runs and rejected-record inspection.

| Native rule | Table | Type | Total records | Valid | Invalid |
|---|---|---|---:|---:|---:|
| `vendor_id` | `vendor_policy` | Primary key | 8 | 8 | 0 |
| `payment_id` | `payments` | Primary key | 9 | 9 | 0 |
| `vendor_id` | `payments` | Foreign key | 9 | 9 | 0 |
| `bank_transaction_id` | `bank_settlements` | Primary key | 7 | 7 | 0 |
| `payment_id` | `bank_settlements` | Foreign key | 7 | 7 | 0 |
| `positive_payment_amount` | `payments` | Custom predicate | 9 | 9 | 0 |
| `policy_threshold_valid` | `vendor_policy` | Custom predicate | 8 | 8 | 0 |

`LIST DQ USL` returns these seven rules, and the final verification actually executes all seven with `RUN DQ`; rule inventory alone is not counted as a passing check. Both custom-rule invalid-record queries also succeeded with empty results. The key checks establish the tested sample's uniqueness and references, while the two custom predicates establish their defined field expectations.

A rule's valid-record proportion applies only to its predicate and table grain; it is not a financial-accuracy score or a model-performance score. The tables have different grains and the rules overlap, so their counts are not pooled into a single accuracy percentage. The positive-amount check, for example, does not prove that a payment was authorized or settled.

The captured platform views complement the executable SQL and JSON results: [deployed USL model](../../data/zetaris-scoring/evidence/usl-model.png), [native quality view](../../data/zetaris-scoring/evidence/usl-quality.png), and [USL query result](../../data/zetaris-scoring/evidence/usl-query.png).

## Reproduce the scoring exercise

Use Node.js 22 or later and an existing configured local Zetaris/PostgreSQL environment from [INTEGRATIONS.md](../INTEGRATIONS.md), including the `FINTRACE` source. Keep its origin, numeric organization ID, API credential and database URL in an ignored private profile; no credentials are supplied by this package.

From the repository root, prepare the deterministic assets and save the separate scoring snapshot:

```sh
node --env-file=.env.zetaris.local --import tsx scripts/prepare_zetaris_scoring.ts --connect
```

In another terminal, keep the read-only synthetic policy service running:

```sh
node --import tsx scripts/serve_zetaris_policy.ts
```

Then provision the owned demonstration objects and execute the evidence queries:

```sh
node --env-file=.env.zetaris.local --import tsx scripts/setup_zetaris_usl.ts --apply
node --env-file=.env.zetaris.local --import tsx scripts/verify_zetaris_usl.ts --connect
```

The policy service binds to loopback port 4315. The verified Docker deployment reaches it through `host.docker.internal`; other deployments need their own reachable endpoint. The setup script copies the CSV into the driver-accessible shared directory, checks local ownership receipts before reusing objects, and refuses to overwrite unrelated existing objects. Keep the receipts when rerunning this owned local deployment. To inspect an already deployed model without provisioning it again, run the verification command with its matching private profile.

For an offline asset check, run `node --import tsx scripts/prepare_zetaris_scoring.ts --check`. The online scoring commands use Zetaris and PostgreSQL, not Nightshift or any model API. Query elapsed times in the evidence are request observations; this is not a latency benchmark.

## Reflection 1 — work avoided compared with a hand-written approach

For this payment-review use case, a hand-written integration needs source registration, field/type normalization, a reusable relationship contract, query construction and quality checks. USL does not remove the need to understand the sources or decide what constitutes a trustworthy match. It gives the typed model and its relationships a shared definition rather than leaving every consumer to reconstruct that definition inside its own query. It does not automatically generate or validate every analytical join.

The practical opportunity is repeated work: payment, settlement and vendor relationships can be reviewed once at the semantic-model boundary, then reused by several exploration queries. A change still needs an explicit source mapping, compatibility checks and a fresh quality run. The initial build also includes installation, syntax discovery and debugging, which should not be counted as savings.

**Implemented comparison:** `BONUS-MANUAL` normalizes all three raw sources in a hand-written CTE query. Its nine ordered result rows matched `USL-1` after decimal normalization, including `NULL` values. The source-level consumer SQL contains 2,406 characters; the USL consumer contains 1,002. That moves source parsing and casts into the reusable activation mappings. It is a smaller consumer query, not a reduction in total implementation code: the model DDL and activation SQL still exist and are excluded from that count.

**Estimate, not a measured result:** for one subsequent change to an already-understood three-source model, budget 45–60 minutes to edit and review three separately maintained consumer joins, versus 30–45 minutes to edit the common mapping and recheck the consumers. The paired planning assumptions imply about 15 minutes of potentially avoided repeated editing. They assume one developer, three consumers, unchanged business rules and working connectors; they exclude source setup, installation and incident diagnosis. Actual work can fall outside these ranges or take longer with USL.

No controlled developer-time comparison was performed, so FinTrace claims no observed percentage improvement or customer time saving. Query durations are execution measurements, not evidence of development productivity. A fair follow-up would time the same schema change in a hand-written baseline and a USL implementation, with equivalent checks and the same developer familiarity.

## Reflection 2 — help and limits in FinTrace

The useful boundary is an explicit record model. Payment-level analysis needs one row per payment; settlement events can have several rows per reference; vendor history can contain multiple effective versions. The semantic mapping must preserve those grains. Aggregating settlement events before a payment-level join, or selecting the instruction valid at the relevant time, is a business decision rather than an automatic consequence of declaring a relationship.

A shared model can reduce inconsistent field names, types and repeated source-specific expressions. Native quality results make a failed expectation inspectable alongside the model instead of relying only on an application's import checks. The value is strongest when several consumers need the same agreed relationships.

There are limits. A declared key does not by itself prove uniqueness in a changing source. A syntactically valid join can multiply rows, currency amounts cannot be added across currencies without an explicit conversion policy, and a recent extract can still have incomplete historical coverage. A quality rule checks its defined population and predicate only; a pass is not a guarantee about untested fields or every financial conclusion. The demonstration uses small synthetic feeds, so it does not establish production scalability or operational data freshness.

The compact deployed policy table uses `vendor_id` as its primary key and represents one effective policy per vendor. Its original JSON retains `policy_id` and `policy_version`, but those fields are not exposed by this compact USL. Supporting several historical policies for one vendor would require an explicit change to the model's key/grain and provenance fields, rather than simply appending policy versions to this schema.

FinTrace therefore retains its independent money, timing and coverage checks, source citations and human review. Semantic modeling supports those controls; it does not replace them or authorize payments.

## Reflection 3 — PM proposal: review a semantic change before activation

**User and problem.** A finance-data maintainer updates a bank or vendor mapping. A valid schema can still introduce duplicated payment rows, unmatched references or a stale quality result. Reviewers need to understand the impact before the new mapping becomes the version used by consumers.

**Proposed behavior.** Add a single change-review workflow that shows the proposed schema and mapping differences, the intended grain, affected relationships, required quality checks and a bounded sample of exceptions. Show separate states for checks that have not run, passed, failed or become stale after a source/mapping change. Keep the previous active mapping available while a candidate is evaluated. This is a proposed workflow improvement, not a feature implemented in this submission or a claim that every underlying capability is absent from Zetaris.

**Acceptance criteria:**

1. A candidate with an incompatible column type is rejected before activation; the previous active mapping continues to answer its existing queries.
2. A seeded duplicate payment key produces the exact affected-key count and at most ten sample records. A bank-reference coverage check reports its denominator and unmatched count separately from a schema check.
3. Updating a mapping or its source-version identifier marks the prior quality result stale; the interface does not present that old pass as a fresh check of the candidate.
4. A reviewer can export the candidate DDL, source mappings, quality predicates and actual execution results without credentials, then reproduce the recorded counts.
5. Activating a reviewed candidate records its version, the selected quality-run identifiers and the reviewer action. A failed mandatory rule requires correction or an explicit recorded exception rather than an automatic green status.

The proposal should first be tested with synthetic data and measured for review errors and task completion. No usability, productivity or financial-risk reduction is claimed from this unimplemented design.

## Technical references

- [Zetaris SQL commands: USL and data quality](https://github.com/zetaris/getting-started/blob/main/docs/guides/zetaris-lightning-sql-commands.md), sections 13–14.
- [FinTrace live integration contract](../INTEGRATIONS.md).
- [Current verification record](VALIDATION.md).
