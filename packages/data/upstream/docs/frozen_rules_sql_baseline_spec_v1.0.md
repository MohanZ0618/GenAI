# Frozen Rules/SQL Baseline Specification — Version 1.0

## 1. Scope and assumptions

This document is the locked design for the strong deterministic Rules/SQL baseline evaluated on FinRCA-Bench v1. It specifies detection, evidence retrieval, tri-state handling, rule collisions, and single-label output before implementation or examination of held-out test performance. Implementation may optimize query execution but may not change semantics.

The baseline may use SQL, deterministic scalar functions, joins, anti-joins, constraints, aggregation, exact matching, and the narrowly specified fuzzy invoice-reference comparison. It may not use learned parameters, embeddings, LLMs, benchmark labels, or post-adjudication artifacts.

### 1.1 Evaluation unit and decision time

The experiment harness supplies only:

- `case_id`, used for routing and output correlation;
- the primary entity type and ID stated in the benchmark question; and
- access to the model-visible financial tables.

The primary entity is not a label and may not be used as evidence by itself. No ground-truth evidence list is supplied to the baseline.

The frozen analytical cutoff is `AS_OF_DATE = 2026-06-30`, taken from `config.yaml`. It is used for aging and clearing-window calculations, especially F12. It is not used as a surrogate ingestion timestamp: most tables do not contain a record-availability timestamp, and a future business posting date can be visible in an ERP extract. Every method receives the same delivered model-visible snapshot. Where a rule explicitly uses an event timestamp, the rule states its cutoff condition. The harness must certify table completeness for absence rules; if a required table failed to load, absence from that table cannot be interpreted as evidence.

Business days are Monday through Friday. No holiday calendar exists, so holidays are not excluded. All timestamps are interpreted as local benchmark time; no timezone conversion is performed.

### 1.2 Single-primary-label protocol

FinRCA-Bench v1 has one primary failure label per case. Every applicable rule is still executed and its raw trace retained. If multiple rules return `ANOMALY`, the frozen collision policy in Section 11 selects one scored `predicted_failure_type`; the remaining hits remain diagnostic and are not silently discarded from the audit log.

A rule is applicable when the supplied primary entity is either the rule's subject or reaches the subject through that rule's stated join path. Rules outside that connected evidence scope are not executed and are not treated as missing evidence. Final aggregation is deterministic: (1) choose the highest-precedence anomaly when one or more applicable rules fire; (2) when none fire but any applicable rule is `INSUFFICIENT_EVIDENCE`, return insufficient; (3) only when every applicable rule has sufficient evidence and returns match, return `MATCH`/`NO_FAILURE`.

### 1.3 Permitted and prohibited information

Permitted inputs are the fourteen financial tables listed in Section 2 and fixed experiment configuration constants listed in Section 9. Operational `audit_log` events may be used only where a rule explicitly permits them, their timestamp is on or before the cutoff, and they describe a source-system event rather than a human RCA adjudication.

The following are prohibited at inference time: `rca_ground_truth.jsonl`, `failure_manifest.csv`, expected answers in `benchmark_questions.jsonl`, `causal_edges.csv`, `internal/mutation_log.jsonl`, `dataset_quality_report.json`, clean pre-mutation tables, split labels, failure signatures, injector code, and any field derived from those artifacts.

### 1.4 Three-state semantics

- `ANOMALY`: sufficient required evidence exists and the positive condition is true.
- `MATCH`: sufficient required evidence exists and the positive condition is false, including an explicitly modeled legitimate exception.
- `INSUFFICIENT_EVIDENCE`: a required record/field is unavailable or ambiguous and the rule is not specifically defined as an absence detector.

`INSUFFICIENT_EVIDENCE` must set `is_anomaly = null`; it is not a negative prediction.

## 2. Data/schema summary

Only these tables exist for this baseline:

| Table | Primary key | Important types and relationships |
|---|---|---|
| `vendors` | `vendor_id` | Master attributes and current bank token; timestamps are ISO datetimes. |
| `vendor_change_log` | `change_id` | `vendor_id` logically references `vendors`; old/new values are strings interpreted by `field_changed`. |
| `purchase_orders` | `po_id` | `vendor_id` references `vendors`; monetary fields are fixed-point decimals. |
| `po_lines` | `po_line_id` | `po_id` references `purchase_orders`; quantity is integer and money is decimal. |
| `invoices` | `invoice_id` | Nonempty `po_id` references `purchase_orders`; empty `po_id` means non-PO invoice. |
| `invoice_lines` | `invoice_line_id` | `invoice_id` references `invoices`; nonempty `po_line_id` references `po_lines`. |
| `approval_events` | `approval_event_id` | `invoice_id` references `invoices`; `approver_id` may reference `employees` or a named system actor. |
| `payments` | `payment_id` | `vendor_id` references `vendors`; `bank_account_id` is the vendor destination snapshot, not the company bank account. |
| `payment_allocations` | (`payment_id`, `invoice_id`, `allocation_date`) | Many-to-many bridge from payments to invoices. |
| `gl_entries` | `journal_line_id` | `journal_id` groups lines; `source_transaction_id` is polymorphic according to `transaction_type`. |
| `bank_transactions` | `bank_transaction_id` | `bank_account_id` is the company bank account; `counterparty_token` is comparable to `payments.bank_account_id`; `payment_reference` is comparable to `payments.reference_number`. |
| `bank_statements` | `bank_statement_id` | Statement controls only; no v1 failure rule requires this table. |
| `employees` | `employee_id` | Role, approval limit, and active status for approval authorization. |
| `audit_log` | `event_id` | Generic operational event log; `entity_id` is polymorphic according to `entity_type`. |

### 2.1 Canonical columns and important data types

`STRING` includes IDs, categories, tokens, references, accounts, and source-system names. `DECIMAL` is fixed-point money, `INTEGER` is exact, `DATE` is ISO `YYYY-MM-DD`, and `TIMESTAMP` is ISO local datetime.

- `vendors`: `vendor_id STRING PK`, `vendor_name STRING`, `vendor_type STRING`, `tax_id_hash STRING`, `country STRING`, `currency STRING`, `payment_terms STRING`, `default_payment_method STRING`, `bank_account_token STRING`, `bank_routing_token STRING`, `vendor_status STRING`, `created_at TIMESTAMP`, `updated_at TIMESTAMP`, `source_system STRING`.
- `vendor_change_log`: `change_id STRING PK`, `vendor_id STRING FK`, `field_changed STRING`, `old_value STRING`, `new_value STRING`, `changed_at TIMESTAMP`, `changed_by STRING`, `change_reason STRING`, `source_system STRING`.
- `purchase_orders`: `po_id STRING PK`, `vendor_id STRING FK`, `po_date DATE`, `currency STRING`, `subtotal DECIMAL`, `tax DECIMAL`, `shipping DECIMAL`, `po_total DECIMAL`, `department STRING`, `cost_center STRING`, `gl_account STRING`, `status STRING`, `expected_delivery_date DATE`, `created_by STRING`, `source_system STRING`.
- `po_lines`: `po_id STRING FK`, `po_line_id STRING PK`, `item_id STRING`, `description STRING`, `quantity INTEGER`, `unit_price DECIMAL`, `line_amount DECIMAL`, `gl_account STRING`, `department STRING`, `cost_center STRING`, `source_system STRING`.
- `invoices`: `invoice_id STRING PK`, `vendor_id STRING FK`, `po_id STRING nullable FK`, `invoice_number STRING`, `invoice_date DATE`, `received_date DATE`, `due_date DATE`, `currency STRING`, `subtotal DECIMAL`, `tax DECIMAL`, `shipping DECIMAL`, `invoice_total DECIMAL`, `payment_terms STRING`, `status STRING`, `duplicate_reference STRING nullable`, `created_at TIMESTAMP`, `source_system STRING`.
- `invoice_lines`: `invoice_id STRING FK`, `invoice_line_id STRING PK`, `po_line_id STRING nullable FK`, `item_id STRING`, `quantity INTEGER`, `unit_price DECIMAL`, `line_amount DECIMAL`, `gl_account STRING`, `department STRING`, `cost_center STRING`, `source_system STRING`.
- `approval_events`: `approval_event_id STRING PK`, `invoice_id STRING FK`, `approval_level INTEGER`, `approver_id STRING logical FK/system actor`, `approver_role STRING`, `action STRING`, `event_timestamp TIMESTAMP`, `previous_status STRING`, `new_status STRING`, `comments STRING`, `source_system STRING`.
- `payments`: `payment_id STRING PK`, `vendor_id STRING FK`, `payment_date DATE`, `payment_method STRING`, `payment_currency STRING`, `payment_amount DECIMAL`, `bank_account_id STRING token`, `payment_status STRING`, `settlement_status STRING`, `reference_number STRING`, `created_at TIMESTAMP`, `source_system STRING`.
- `payment_allocations`: `payment_id STRING composite PK/FK`, `invoice_id STRING composite PK/FK`, `allocated_amount DECIMAL`, `allocation_date DATE composite PK`, `source_system STRING`.
- `gl_entries`: `journal_id STRING grouping key`, `journal_line_id STRING PK`, `transaction_type STRING`, `source_transaction_id STRING logical polymorphic FK`, `posting_date DATE`, `accounting_period STRING YYYY-MM`, `gl_account STRING`, `debit DECIMAL`, `credit DECIMAL`, `currency STRING`, `department STRING`, `cost_center STRING`, `memo STRING`, `source_system STRING`.
- `bank_transactions`: `bank_transaction_id STRING PK`, `bank_account_id STRING company-account token`, `transaction_date DATE`, `posted_date DATE`, `transaction_type STRING`, `amount DECIMAL`, `currency STRING`, `direction STRING`, `bank_reference STRING`, `counterparty_token STRING`, `payment_reference STRING logical payment link`, `status STRING`, `source_system STRING`.
- `bank_statements`: `bank_statement_id STRING PK`, `bank_account_id STRING`, `statement_date DATE`, `opening_balance DECIMAL`, `closing_balance DECIMAL`, `total_debits DECIMAL`, `total_credits DECIMAL`, `source_system STRING`.
- `employees`: `employee_id STRING PK`, `role STRING`, `department STRING`, `approval_limit DECIMAL`, `active_status STRING`, `source_system STRING`.
- `audit_log`: `event_id STRING PK`, `entity_type STRING`, `entity_id STRING logical polymorphic FK`, `event_type STRING`, `timestamp TIMESTAMP`, `actor_id STRING`, `field STRING`, `old_value STRING`, `new_value STRING`, `source_system STRING`.

There is no receipts table, PO-amendment table, FX-rate table, vendor-alias table, parent/subsidiary hierarchy, accounting-calendar table, bank-to-payment foreign key, or dedicated approval-policy table. The specification does not invent any of them.

## 3. Shared output and evidence contract

Every scored case returns exactly one object:

```json
{
  "case_id": "...",
  "method": "rules_sql",
  "is_anomaly": true,
  "predicted_failure_type": "F01_DUPLICATE_INVOICE",
  "confidence": null,
  "evidence_record_ids": ["invoices:INV_0001"],
  "triggered_rule_id": "RSQL_F01_V1",
  "hop_count": 0,
  "status": "ANOMALY",
  "reason": "Invoice INV_0001 and invoice INV_0002 share vendor VND_01, normalized reference SYN001, currency USD, and total 100.00 within 14 days."
}
```

For final `MATCH`, `is_anomaly=false`, `predicted_failure_type="NO_FAILURE"`, `triggered_rule_id="RSQL_NO_ANOMALY_V1"`, and `hop_count` is the maximum hop count among applicable rules needed to establish the match. For final `INSUFFICIENT_EVIDENCE`, `is_anomaly=null`, `predicted_failure_type=null`, `triggered_rule_id="RSQL_EVIDENCE_GATE_V1"`, and the reason names the missing or ambiguous fields and affected rules. `confidence` is always `null`. Individual rule traces retain their own rule IDs and hop counts for both match and insufficient outcomes.

Evidence IDs use `table_name:primary_key`. The composite allocation form is `payment_allocations:<payment_id>|<invoice_id>|<allocation_date>`. Absence is described by an observed count in `reason`; the baseline never fabricates an ID for a missing row.

Reasons are deterministic templates populated with observed values. No generative text is allowed.

## 4. Shared normalization specification

These functions are part of the frozen rule semantics:

- `NORM_TEXT(x)`: if NULL, return NULL; otherwise Unicode NFKC normalize, trim leading/trailing whitespace, collapse internal Unicode whitespace to one ASCII space, and uppercase.
- `NORM_REFERENCE(x)`: apply NFKC and uppercase, then remove every character outside ASCII `A-Z` and `0-9`. Leading zeros are preserved. Empty result becomes NULL.
- `EDIT_SIM(a,b)`: if either normalized reference is NULL, return NULL; otherwise `1 - LEVENSHTEIN_DISTANCE(a,b) / MAX(LENGTH(a),LENGTH(b))`; two empty values are never compared.
- `NORM_STATUS(x)`: `NORM_TEXT(x)` with spaces and hyphens converted to underscores.
- `PARSE_DATE(x)` / `PARSE_TS(x)`: strict ISO parsing. Invalid values become NULL and cause `INSUFFICIENT_EVIDENCE` for rules that require them.
- `CURRENCY_QUANTUM(c)`: `1` for JPY and `0.01` for USD, EUR, GBP, and CAD. Unknown currency returns NULL.
- `Q_MONEY(x,c)`: decimal quantization to the currency quantum using round-half-up. Binary floating-point is prohibited.
- `WITHIN_MONEY(a,b,c)`: true when `ABS(Q_MONEY(a,c)-Q_MONEY(b,c)) <= CURRENCY_QUANTUM(c)`.
- `BUSINESS_DAYS_BETWEEN(a,b)`: count Monday-Friday dates strictly after `a` and through `b`; returns NULL if `b<a`.

IDs are compared after trim only and remain case-sensitive because generated IDs are canonical. Vendor names are not used for identity matching; `vendor_id` is authoritative. Currency conversion is never inferred from amount ratios.

An effective successful payment has `NORM_STATUS(payment_status)='COMPLETED'` and `NORM_STATUS(settlement_status)='SETTLED'`. Reversed payments and their allocations are excluded from net-paid aggregates. A posted bank debit has `direction='DEBIT'`, `status='POSTED'`, and `posted_date <= AS_OF_DATE`.

## 5. Detailed rule specifications

### 5.1 RSQL_F01_V1 — F01_DUPLICATE_INVOICE

**1. Failure type.** A positive is an active positive-value invoice for which another active invoice has the same vendor, currency, amount within currency quantum, sufficiently similar normalized invoice reference, and an invoice date inside the duplicate window. A negative is a unique invoice, a canceled invoice, a nonpositive credit memo, or a recurring invoice outside the reference/date criteria.

**2. Required tables.**

- Table: `invoices`; required fields: `invoice_id`, `vendor_id`, `invoice_number`, `invoice_date`, `currency`, `invoice_total`, `status`; purpose: self-join candidate obligations.

**3. Join path.** Self-join `invoices i1` to `invoices i2` with `i1.invoice_id < i2.invoice_id`. This is candidate comparison, not an FK traversal. If the primary invoice is missing, return insufficient evidence.

**4. Reasoning complexity.** Tier 1 — single-record / zero-hop. **Hop count: 0.** It performs a set-level duplicate comparison inside one entity table without following an explicit relationship.

**5. Deterministic detection rule.** Exclude statuses `CANCELED` and `CREDIT_APPLIED` and totals `<=0`. Require equal non-NULL `vendor_id` and `currency`; `WITHIN_MONEY(i1.invoice_total,i2.invoice_total,currency)`; `ABS(invoice_date1-invoice_date2) <= DUPLICATE_DATE_WINDOW_DAYS`; and either normalized references are equal or edit similarity meets `DUPLICATE_REFERENCE_SIMILARITY`. NULL vendor, currency, total, date, or primary reference yields insufficient evidence for that primary invoice. A pair is emitted once in lexical invoice-ID order.

**6. SQL-style pseudocode.**

```sql
SELECT i1.invoice_id, i2.invoice_id,
  CASE WHEN i1.vendor_id = i2.vendor_id
        AND i1.currency = i2.currency
        AND WITHIN_MONEY(i1.invoice_total, i2.invoice_total, i1.currency)
        AND ABS(DATE_DIFF(i1.invoice_date, i2.invoice_date)) <= :dup_days
        AND (NORM_REFERENCE(i1.invoice_number) = NORM_REFERENCE(i2.invoice_number)
             OR EDIT_SIM(NORM_REFERENCE(i1.invoice_number),
                         NORM_REFERENCE(i2.invoice_number)) >= :dup_similarity)
       THEN 1 ELSE 0 END AS is_anomaly
FROM invoices i1
JOIN invoices i2 ON i1.invoice_id < i2.invoice_id
WHERE NORM_STATUS(i1.status) NOT IN ('CANCELED','CREDIT_APPLIED')
  AND NORM_STATUS(i2.status) NOT IN ('CANCELED','CREDIT_APPLIED')
  AND i1.invoice_total > 0 AND i2.invoice_total > 0;
```

**7. Thresholds and tolerances.** `DUPLICATE_DATE_WINDOW_DAYS`: initial 14; candidate grid `{7,14,30}`; **VALIDATION-TUNED**. `DUPLICATE_REFERENCE_SIMILARITY`: initial `0.90`; candidate grid `{0.85,0.90,0.95,1.00}`; **VALIDATION-TUNED**. Currency quantum is globally fixed. Joint selection maximizes validation macro-F1, ties choosing the higher similarity then shorter window.

**8. Data normalization.** Use shared reference, status, date, currency, and money normalization. Do not strip leading zeros or use vendor names.

**9. Edge cases.** Same-vendor recurring invoices with distinct references normally match; references differing by only one character may be flagged. A canceled duplicate does not create two active obligations. Credit memos are excluded. Cross-vendor duplicates are not detected. Multiple invoices legitimately sharing one PO are not duplicates unless the duplicate criteria also hold.

**10. Missing-data behavior.** Missing primary invoice/reference/vendor/currency/amount/date is `INSUFFICIENT_EVIDENCE`. A complete invoice table with no qualifying pair is `MATCH`.

**11. Expected output.** An anomaly returns both invoice IDs, `triggered_rule_id=RSQL_F01_V1`, hop 0, and a reason listing vendor, normalized references, amounts, and day difference. Other fields use the shared contract.

**12. Evidence requirements.** Minimum records: both invoice rows. Minimum fields: IDs, vendor IDs, references, dates, currencies, totals, and statuses.

**13. Expected strengths.** Exact and near-exact reference duplication with matching economic attributes.

**14. Expected failure modes.** Semantic duplicate references with low character similarity, vendor aliases, cross-currency duplicates, or legitimate same-day recurring charges.

### 5.2 RSQL_F02_V1 — F02_PO_INVOICE_AMOUNT_MISMATCH

**1. Failure type.** A positive is a PO-backed active invoice whose line price/amount, or fully covered PO header tax/shipping, differs from authorization by more than the PO tolerance. A negative is within tolerance, non-PO, canceled/credited, or a legitimate partial invoice whose line prices remain authorized.

**2. Required tables.**

- Table: `invoices`; required fields: `invoice_id`, `po_id`, `currency`, `tax`, `shipping`, `status`; purpose: invoice scope/header.
- Table: `invoice_lines`; required fields: `invoice_id`, `invoice_line_id`, `po_line_id`, `quantity`, `unit_price`, `line_amount`; purpose: billed economics.
- Table: `purchase_orders`; required fields: `po_id`, `currency`, `tax`, `shipping`; purpose: authorization/header charges.
- Table: `po_lines`; required fields: `po_line_id`, `po_id`, `quantity`, `unit_price`, `line_amount`; purpose: authorized line economics.

**3. Join path.** `invoices.po_id -> purchase_orders.po_id`; `invoices.invoice_id -> invoice_lines.invoice_id -> po_lines.po_line_id`; verify `po_lines.po_id = invoices.po_id`. Use inner joins for valid line comparison and anti-joins to detect missing links. A missing referenced PO/line is insufficient for F02 and may be reported as structural data quality outside the 15 labels.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** The strongest rule traverses invoice header to invoice line and then to its authorized PO line.

**5. Deterministic detection rule.** For each matched line compute authorized billed amount `invoice_line.quantity * po_line.unit_price`. Flag when absolute unit-price variance or extended-amount variance exceeds `MAX(currency_quantum, ABS(authorized_value)*PO_TOLERANCE_PERCENT/100)`. Header tax/shipping are compared only when every PO line is represented once and invoice quantities equal PO quantities. Currency mismatch returns insufficient evidence because no FX table exists. Exclude canceled, credit-applied, nonpositive, and non-PO invoices.

**6. SQL-style pseudocode.**

```sql
WITH line_check AS (
 SELECT i.invoice_id, il.invoice_line_id,
   ABS(il.unit_price - pol.unit_price) AS unit_delta,
   ABS(il.line_amount - (il.quantity * pol.unit_price)) AS amount_delta,
   MAX(CURRENCY_QUANTUM(i.currency),
       ABS(pol.unit_price) * :po_pct / 100) AS unit_tol,
   MAX(CURRENCY_QUANTUM(i.currency),
       ABS(il.quantity * pol.unit_price) * :po_pct / 100) AS amount_tol
 FROM invoices i
 JOIN purchase_orders po ON po.po_id = i.po_id
 JOIN invoice_lines il ON il.invoice_id = i.invoice_id
 JOIN po_lines pol ON pol.po_line_id = il.po_line_id AND pol.po_id = po.po_id
 WHERE i.currency = po.currency
), coverage AS (
 SELECT i.invoice_id,
   CASE WHEN COUNT(DISTINCT il.po_line_id) = COUNT(DISTINCT pol.po_line_id)
             AND SUM(CASE WHEN il.quantity <> pol.quantity THEN 1 ELSE 0 END) = 0
        THEN 1 ELSE 0 END AS full_coverage
 FROM invoices i JOIN purchase_orders po ON po.po_id=i.po_id
 JOIN po_lines pol ON pol.po_id=po.po_id
 LEFT JOIN invoice_lines il ON il.invoice_id=i.invoice_id
                              AND il.po_line_id=pol.po_line_id
 GROUP BY i.invoice_id
)
SELECT i.invoice_id,
 CASE WHEN EXISTS (SELECT 1 FROM line_check l WHERE l.invoice_id=i.invoice_id
                   AND (l.unit_delta>l.unit_tol OR l.amount_delta>l.amount_tol))
        OR (c.full_coverage=1 AND
            (ABS(i.tax-po.tax) > MAX(CURRENCY_QUANTUM(i.currency),ABS(po.tax)*:po_pct/100)
             OR ABS(i.shipping-po.shipping) > MAX(CURRENCY_QUANTUM(i.currency),ABS(po.shipping)*:po_pct/100)))
      THEN 1 ELSE 0 END AS is_anomaly
FROM invoices i JOIN purchase_orders po ON po.po_id=i.po_id
JOIN coverage c ON c.invoice_id=i.invoice_id;
```

**7. Thresholds and tolerances.** `PO_TOLERANCE_PERCENT=2.0`, globally fixed from `config.yaml`; currency quantum fixed. No validation tuning.

**8. Data normalization.** Decimal quantization and strict currency equality. Status normalization excludes canceled/credit rows. Quantities are parsed as exact integers.

**9. Edge cases.** Partial invoices are judged by authorized unit price, not full PO total. Multiple invoices against one PO can exhaust quantity cumulatively, but v1 has no receipt/cumulative-billing table, so cumulative overbilling is not detectable. Discounts below PO price within tolerance match. Amended/canceled POs cannot be reliably interpreted because no amendment history exists. Tax/shipping are compared only for complete coverage.

**10. Missing-data behavior.** Missing PO/line, currency, money, or quantity is insufficient. Non-PO invoices are not applicable and evaluate `MATCH` for F02. A complete within-tolerance comparison is `MATCH`.

**11. Expected output.** Evidence contains the invoice, PO, and offending invoice/PO lines; reason reports observed and authorized unit/extended values and tolerance.

**12. Evidence requirements.** Minimum anomaly evidence: invoice, PO, one offending invoice line, and its referenced PO line; header-only tax/shipping anomalies require all lines establishing full coverage.

**13. Expected strengths.** Explicit price, extended-amount, tax, and shipping variance beyond a known tolerance.

**14. Expected failure modes.** PO amendments, cumulative billing, discounts/credits without dedicated fields, and currency conversion.

### 5.3 RSQL_F03_V1 — F03_QUANTITY_MISMATCH

**1. Failure type.** A positive is an active PO-backed invoice line whose integer quantity is not equal to its referenced PO-line quantity. A negative has equal quantity or is non-PO/canceled/credited.

**2. Required tables.**

- Table: `invoices`; required fields: `invoice_id`, `status`; purpose: scope active invoice obligations.
- Table: `invoice_lines`; required fields: `invoice_id`, `invoice_line_id`, `po_line_id`, `quantity`; purpose: supply billed quantity and the PO-line link.
- Table: `po_lines`; required fields: `po_line_id`, `quantity`; purpose: supply ordered quantity.

**3. Join path.** `invoices.invoice_id -> invoice_lines.invoice_id -> po_lines.po_line_id`, inner join; missing nonempty `po_line_id` target is insufficient.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** It traverses the invoice-to-line and line-to-PO-line relationships.

**5. Deterministic detection rule.** After excluding canceled/credit invoices, flag if `CAST(invoice_line.quantity AS INTEGER) <> CAST(po_line.quantity AS INTEGER)`. No amount condition may suppress a quantity mismatch. NULL/nonintegral quantity is insufficient.

**6. SQL-style pseudocode.**

```sql
SELECT i.invoice_id, il.invoice_line_id, pol.po_line_id,
 CASE WHEN il.quantity <> pol.quantity THEN 1 ELSE 0 END AS is_anomaly
FROM invoices i
JOIN invoice_lines il ON il.invoice_id=i.invoice_id
JOIN po_lines pol ON pol.po_line_id=il.po_line_id
WHERE NORM_STATUS(i.status) NOT IN ('CANCELED','CREDIT_APPLIED')
  AND il.po_line_id IS NOT NULL AND TRIM(il.po_line_id) <> '';
```

**7. Thresholds and tolerances.** `QUANTITY_TOLERANCE=0`, globally fixed. No percentage tolerance and no validation tuning.

**8. Data normalization.** Strict integer parsing; no rounding of fractional quantities. IDs are trimmed only.

**9. Edge cases.** Legitimate partial billing, backorders, or staged deliveries will be flagged because no receipts or cumulative-quantity table exists. Split payments do not affect the rule. Equal amounts with different quantities remain anomalous by design.

**10. Missing-data behavior.** Missing invoice, line, referenced PO line, or quantity is insufficient. Non-PO lines are `MATCH` for this rule.

**11. Expected output.** Return invoice, invoice-line, and PO-line IDs; reason reports both quantities.

**12. Evidence requirements.** The active invoice row, offending invoice line, and referenced PO line with both quantities.

**13. Expected strengths.** Exact linked-line quantity violations, including amount-preserving manipulation.

**14. Expected failure modes.** Legitimate partial fulfillment and many-to-one line mappings absent from the schema.

### 5.4 RSQL_F04_V1 — F04_INCORRECT_VENDOR_ASSOCIATION

**1. Failure type.** A positive is a PO-backed invoice whose non-NULL `vendor_id` differs from its referenced PO's non-NULL `vendor_id`. A negative has equal IDs or is non-PO.

**2. Required tables.**

- Table: `invoices`; required fields: `invoice_id`, `po_id`, `vendor_id`, `status`; purpose: provide the asserted vendor and PO link.
- Table: `purchase_orders`; required fields: `po_id`, `vendor_id`; purpose: provide the authorized vendor.

**3. Join path.** `invoices.po_id -> purchase_orders.po_id`, inner join. Missing referenced PO is insufficient, not F04.

**4. Reasoning complexity.** Tier 2 — one-hop relational. **Hop count: 1.** One explicit invoice-to-PO relationship is followed.

**5. Deterministic detection rule.** Exclude canceled/credit invoices. If both vendor IDs are present, flag `invoice.vendor_id <> purchase_order.vendor_id`. Vendor names and fuzzy matching are prohibited because IDs are authoritative.

**6. SQL-style pseudocode.**

```sql
SELECT i.invoice_id, po.po_id,
 CASE WHEN i.vendor_id <> po.vendor_id THEN 1 ELSE 0 END AS is_anomaly
FROM invoices i JOIN purchase_orders po ON po.po_id=i.po_id
WHERE i.vendor_id IS NOT NULL AND po.vendor_id IS NOT NULL
  AND NORM_STATUS(i.status) NOT IN ('CANCELED','CREDIT_APPLIED');
```

**7. Thresholds and tolerances.** None.

**8. Data normalization.** Trim IDs; do not normalize names or collapse related vendors.

**9. Edge cases.** Parent/subsidiary vendors, vendor mergers, novations, and aliases will be flagged unless IDs were updated consistently; no hierarchy/merge table exists. Non-PO invoices cannot be assessed.

**10. Missing-data behavior.** Missing PO, invoice vendor, or PO vendor is insufficient. Non-PO is `MATCH` for F04.

**11. Expected output.** Return invoice and PO IDs; reason states both vendor IDs exactly.

**12. Evidence requirements.** Invoice with `vendor_id` and `po_id`; referenced PO with `vendor_id`.

**13. Expected strengths.** Explicit referential vendor inconsistency.

**14. Expected failure modes.** Legitimate legal-entity relationships not modeled in v1 and wrong vendors on non-PO invoices.

### 5.5 RSQL_F05_V1 — F05_PAYMENT_WITHOUT_VALID_INVOICE

**1. Failure type.** A positive is an effective completed payment with no positive allocation to an existing invoice, or with any allocation referencing a missing invoice. A negative is a reversed payment or a payment whose positive allocations all reference valid invoices.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `payment_status`, `settlement_status`, `payment_amount`; purpose: identify effective disbursements.
- Table: `payment_allocations`; required fields: `payment_id`, `invoice_id`, `allocated_amount`, `allocation_date`; purpose: establish allocation support or its absence and construct the composite evidence ID.
- Table: `invoices`; required fields: `invoice_id`; purpose: verify that an allocated payable actually exists.

**3. Join path.** `payments.payment_id -> payment_allocations.payment_id -> invoices.invoice_id`, left joins because relationship absence is the signal. The allocation table must be a complete loaded snapshot.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** It traverses the payment-to-allocation bridge and allocation-to-invoice relationship.

**5. Deterministic detection rule.** Restrict to effective successful payments with positive amount. Aggregate `valid_allocation_count` for allocations with `allocated_amount>0` and existing invoice, plus `invalid_allocation_count` for allocations whose invoice is missing. Flag when valid count is zero or invalid count is positive. Do not treat bank transactions such as fees as payments because they are not rows in `payments`.

**6. SQL-style pseudocode.**

```sql
SELECT p.payment_id,
 CASE WHEN COUNT(CASE WHEN pa.allocated_amount>0 AND i.invoice_id IS NOT NULL THEN 1 END)=0
            OR COUNT(CASE WHEN pa.invoice_id IS NOT NULL AND i.invoice_id IS NULL THEN 1 END)>0
      THEN 1 ELSE 0 END AS is_anomaly
FROM payments p
LEFT JOIN payment_allocations pa ON pa.payment_id=p.payment_id
LEFT JOIN invoices i ON i.invoice_id=pa.invoice_id
WHERE NORM_STATUS(p.payment_status)='COMPLETED'
  AND NORM_STATUS(p.settlement_status)='SETTLED'
  AND p.payment_amount>0
GROUP BY p.payment_id;
```

**7. Thresholds and tolerances.** Positive allocation threshold is `>0` at currency precision; fixed. No tuning.

**8. Data normalization.** Shared statuses and currency money parsing. IDs trim only.

**9. Edge cases.** Deposits/prepayments without invoices would be flagged because no prepayment type exists. Reversals are excluded. A payment allocated partly to a valid and partly to a missing invoice is anomalous. Bank fees never enter this rule unless incorrectly represented as ERP payments.

**10. Missing-data behavior.** If payments, allocations, or invoices table is unavailable, insufficient. If all tables are complete and no relationship row exists, absence is positive evidence and returns anomaly.

**11. Expected output.** Return payment plus any invalid allocation IDs; reason reports valid and invalid allocation counts.

**12. Evidence requirements.** Payment record and, when present, invalid allocation rows. No fabricated invoice evidence is returned for an anti-join.

**13. Expected strengths.** Unsupported disbursements and broken allocation foreign keys.

**14. Expected failure modes.** Legitimate deposits, advances, or non-invoice disbursements absent from the schema.

### 5.6 RSQL_F06_V1 — F06_INVOICE_PAID_TWICE

**1. Failure type.** A positive is an active positive invoice whose allocations from effective successful payments exceed its total by more than currency quantum. A negative is exactly settled, underpaid, reversed, canceled, or credited.

**2. Required tables.**

- Table: `invoices`; required fields: `invoice_id`, `currency`, `invoice_total`, `status`; purpose: define the obligation and its active state.
- Table: `payment_allocations`; required fields: `invoice_id`, `payment_id`, `allocated_amount`, `allocation_date`; purpose: aggregate amounts settling the obligation and identify evidence rows.
- Table: `payments`; required fields: `payment_id`, `payment_currency`, `payment_status`, `settlement_status`; purpose: include only effective successful payments and validate allocation currency context.

**3. Join path.** `invoices.invoice_id -> payment_allocations.invoice_id -> payments.payment_id`; aggregate left joins.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** It aggregates across the invoice-allocation-payment chain.

**5. Deterministic detection rule.** `net_paid = SUM(allocated_amount)` only for effective successful payments whose `payment_currency=invoice.currency`. A contributing currency mismatch is insufficient for F06 because allocations carry no independent currency. Flag when `net_paid - invoice_total > currency_quantum`. Do not flag merely because more than one payment exists. Exclude invoice totals `<=0` and canceled/credit statuses.

**6. SQL-style pseudocode.**

```sql
SELECT i.invoice_id,
 SUM(CASE WHEN NORM_STATUS(p.payment_status)='COMPLETED'
               AND NORM_STATUS(p.settlement_status)='SETTLED'
               AND p.payment_currency=i.currency
          THEN pa.allocated_amount ELSE 0 END) AS net_paid,
 SUM(CASE WHEN NORM_STATUS(p.payment_status)='COMPLETED'
               AND NORM_STATUS(p.settlement_status)='SETTLED'
               AND p.payment_currency<>i.currency THEN 1 ELSE 0 END) AS currency_errors,
 CASE WHEN currency_errors>0 THEN NULL
      WHEN net_paid-i.invoice_total>CURRENCY_QUANTUM(i.currency) THEN 1 ELSE 0 END
FROM invoices i
LEFT JOIN payment_allocations pa ON pa.invoice_id=i.invoice_id
LEFT JOIN payments p ON p.payment_id=pa.payment_id
WHERE i.invoice_total>0 AND NORM_STATUS(i.status) NOT IN ('CANCELED','CREDIT_APPLIED')
GROUP BY i.invoice_id,i.invoice_total,i.currency;
```

**7. Thresholds and tolerances.** `OVERPAYMENT_TOLERANCE = currency quantum`, fixed.

**8. Data normalization.** Money, currency, and effective-payment status rules are shared. Negative allocations are retained as offsets only if their payment is effective.

**9. Edge cases.** Split payments are normal when their sum equals the invoice. Intentional overpayment/on-account credits will be flagged because no credit-balance field exists. Reversed payments are excluded. Credit memos are excluded as primary obligations.

**10. Missing-data behavior.** Missing invoice amount/currency or unavailable allocation/payment table is insufficient. Complete evidence at or below balance is `MATCH`.

**11. Expected output.** Return invoice, all contributing effective payments, and allocation composite IDs; reason states invoice total, net paid, and excess.

**12. Evidence requirements.** Invoice plus every allocation/payment included in `net_paid`.

**13. Expected strengths.** Exact overpayment and duplicate-disbursement aggregation across split/batch structures.

**14. Expected failure modes.** Intended on-account overpayments, refunds not linked through allocations, and missing reversal semantics.

### 5.7 RSQL_F07_V1 — F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE

**1. Failure type.** A positive is an invoice marked `PAID` with positive effective allocations that are less than its positive total by more than currency quantum. A negative is fully paid, or partially paid while status remains open/approved/partially paid.

**2. Required tables.**

- Table: `invoices`; required fields: `invoice_id`, `invoice_total`, `currency`, `status`; purpose: provide obligation, residual basis, and claimed paid state.
- Table: `payment_allocations`; required fields: `invoice_id`, `payment_id`, `allocated_amount`, `allocation_date`; purpose: aggregate applied amounts and identify evidence rows.
- Table: `payments`; required fields: `payment_id`, `payment_currency`, `payment_status`, `settlement_status`; purpose: restrict the aggregate to effective successful payments and validate allocation currency context.

**3. Join path.** `invoices -> payment_allocations -> payments`, aggregate left joins.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** It compares invoice state to aggregate settled allocations over two relationships.

**5. Deterministic detection rule.** Compute `net_paid` exactly as F06, including strict payment/invoice currency equality. Flag only when normalized invoice status is `PAID`, `net_paid>0`, and `invoice_total-net_paid>currency_quantum`. A zero-paid invoice marked paid is insufficient for this specific partial-payment class and remains available to a general data-quality trace, not relabeled F07.

**6. SQL-style pseudocode.**

```sql
SELECT i.invoice_id,
 SUM(CASE WHEN NORM_STATUS(p.payment_status)='COMPLETED'
               AND NORM_STATUS(p.settlement_status)='SETTLED'
               AND p.payment_currency=i.currency
          THEN pa.allocated_amount ELSE 0 END) AS net_paid,
 SUM(CASE WHEN NORM_STATUS(p.payment_status)='COMPLETED'
               AND NORM_STATUS(p.settlement_status)='SETTLED'
               AND p.payment_currency<>i.currency THEN 1 ELSE 0 END) AS currency_errors,
 CASE WHEN currency_errors>0 THEN NULL
      WHEN NORM_STATUS(i.status)='PAID' AND net_paid>0
            AND i.invoice_total-net_paid>CURRENCY_QUANTUM(i.currency)
      THEN 1 ELSE 0 END AS is_anomaly
FROM invoices i
LEFT JOIN payment_allocations pa ON pa.invoice_id=i.invoice_id
LEFT JOIN payments p ON p.payment_id=pa.payment_id
GROUP BY i.invoice_id,i.status,i.invoice_total,i.currency;
```

**7. Thresholds and tolerances.** `RESIDUAL_TOLERANCE = currency quantum`, fixed.

**8. Data normalization.** Shared money, status, and effective-payment rules.

**9. Edge cases.** Scheduled partials with nonpaid status match. Discounts/write-offs without a dedicated field can appear as residuals and be flagged if status is paid. Reversals are excluded from net paid. Overpayment is handled by F06, not F07.

**10. Missing-data behavior.** Missing total/currency/status or unavailable allocation/payment evidence is insufficient. A complete nonpaid partial is `MATCH`.

**11. Expected output.** Return invoice, contributing payments, and allocations; reason reports total, net paid, residual, and observed status.

**12. Evidence requirements.** Invoice and all effective allocation/payment records used in the balance.

**13. Expected strengths.** Paid-status residual errors despite internally consistent payment, GL, and bank amounts.

**14. Expected failure modes.** Contractual write-offs, discounts, and credit offsets not represented in allocations.

### 5.8 RSQL_F08_V1 — F08_APPROVAL_WORKFLOW_FAILURE

**1. Failure type.** A positive is a payment released for an invoice before the required terminal approval, with a required role missing, or with an unauthorized final approver. A negative completes the frozen amount-based approval ladder before payment.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `created_at`, `payment_status`; purpose: identify release and its decision timestamp.
- Table: `payment_allocations`; required fields: `payment_id`, `invoice_id`, `allocation_date`; purpose: connect released payments to approved obligations and identify evidence rows.
- Table: `invoices`; required fields: `invoice_id`, `invoice_total`, `currency`; purpose: select the required amount-based policy.
- Table: `approval_events`; required fields: `invoice_id`, `approval_level`, `approver_id`, `approver_role`, `action`, `event_timestamp`; purpose: reconstruct approval sequence and timing.
- Table: `employees`; required fields: `employee_id`, `role`, `approval_limit`, `active_status`; purpose: validate human approver authority.

**3. Join path.** `payments.payment_id -> payment_allocations.payment_id -> invoices.invoice_id -> approval_events.invoice_id`; non-system `approval_events.approver_id -> employees.employee_id`. Left join approvals/employees so missing required events/actors are detectable.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 4.** The maximum evidence path reaches the employee authority through payment, allocation, invoice, and approval event.

**5. Deterministic detection rule.** The frozen policy is: total `<=500`: terminal `AUTO` approval; `>500..10000`: `MANAGER`; `>10000..50000`: `MANAGER,DIRECTOR`; `>50000..250000`: `MANAGER,DIRECTOR,CONTROLLER`; `>250000`: `MANAGER,DIRECTOR,TREASURY`. Because no FX-rate/policy-currency field exists, the policy uses the nominal quantized `invoice_total` in its recorded currency, matching the benchmark workflow. Consider only `APPROVED` or `AUTO_APPROVED` events at or before payment creation. Required roles must appear in increasing approval level; the final event must precede/equal payment creation. Non-auto actors must exist, be active, and have employee role equal to event role. The final actor's approval limit must be at least invoice total. Auto approval is valid only at `<=500` with system actor/auto role. Any violation is positive.

**6. SQL-style pseudocode.**

```sql
WITH required AS (
 SELECT i.invoice_id,
  CASE WHEN i.invoice_total<=500 THEN 'AUTO'
       WHEN i.invoice_total<=10000 THEN 'MANAGER'
       WHEN i.invoice_total<=50000 THEN 'MANAGER,DIRECTOR'
       WHEN i.invoice_total<=250000 THEN 'MANAGER,DIRECTOR,CONTROLLER'
       ELSE 'MANAGER,DIRECTOR,TREASURY' END AS required_roles
 FROM invoices i
), effective_events AS (
 SELECT ae.*, e.role AS employee_role, e.approval_limit, e.active_status
 FROM approval_events ae LEFT JOIN employees e ON e.employee_id=ae.approver_id
 WHERE NORM_STATUS(ae.action) IN ('APPROVED','AUTO_APPROVED')
)
SELECT p.payment_id,i.invoice_id,
 CASE WHEN NOT ROLES_PRESENT_IN_LEVEL_ORDER(r.required_roles,effective_events)
        OR TERMINAL_APPROVAL_TS(effective_events)>p.created_at
        OR FINAL_ACTOR_INVALID(effective_events,i.invoice_total)
      THEN 1 ELSE 0 END AS is_anomaly
FROM payments p JOIN payment_allocations pa ON pa.payment_id=p.payment_id
JOIN invoices i ON i.invoice_id=pa.invoice_id
JOIN required r ON r.invoice_id=i.invoice_id
LEFT JOIN effective_events ON effective_events.invoice_id=i.invoice_id
WHERE NORM_STATUS(p.payment_status) IN ('COMPLETED','SUBMITTED');
```

**7. Thresholds and tolerances.** Approval breakpoints `{500,10000,50000,250000}` and the role ladder are globally fixed policy constants. No validation tuning.

**8. Data normalization.** Status/action/role use `NORM_STATUS`; money uses invoice currency. Approval events are sorted by parsed timestamp then approval level then event ID.

**9. Edge cases.** Rejections followed by valid resubmission are allowed if the final effective chain is complete. Delegation is insufficient unless a subsequent valid approved event names an authorized actor. Batch payments are anomalous if any allocated invoice lacks approval. Auto approval above 500 is anomalous. The table has no separate policy-version field, so historical policy changes cannot be modeled. Nominal limits across currencies are a benchmark convention rather than a general accounting policy.

**10. Missing-data behavior.** Missing invoice amount, payment time, approval table, or employee evidence for a non-system approver is insufficient, except a complete approval table with a missing required event is positive evidence. Missing actor row for a claimed human approval is anomalous unauthorized approval.

**11. Expected output.** Return payment, allocation, invoice, relevant approval events, and final employee when present; reason lists required roles, observed roles/levels, final timestamp, and payment timestamp.

**12. Evidence requirements.** Payment and allocation, invoice total, complete approval event sequence, and employee record for every human event relied upon.

**13. Expected strengths.** Explicit missing levels, ordering violations, invalid actors, and amount-policy violations.

**14. Expected failure modes.** Undocumented delegation policy, historical policy versions, or approvals held in unavailable systems.

### 5.9 RSQL_F09_V1 — F09_GL_POSTING_MISMATCH

**1. Failure type.** A positive is an effective completed payment whose required payment journal is absent after the posting lag, unbalanced, in the wrong currency/accounts, or different in amount from the operational payment. A negative has a balanced journal whose AP debit and cash credit equal the payment.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `payment_date`, `payment_currency`, `payment_amount`, `payment_status`, `settlement_status`; purpose: provide the authoritative operational transaction.
- Table: `gl_entries`; required fields: `journal_id`, `journal_line_id`, `transaction_type`, `source_transaction_id`, `posting_date`, `gl_account`, `debit`, `credit`, `currency`; purpose: provide the complete source-linked accounting journal.

**3. Join path.** Logical left join `payments.payment_id -> gl_entries.source_transaction_id` constrained by `NORM_STATUS(transaction_type)='PAYMENT'`. `source_transaction_id` is not globally unique without this discriminator. Missing rows are detectable only when the GL snapshot is complete.

**4. Reasoning complexity.** Tier 2 — one-hop relational. **Hop count: 1.** It compares an operational payment to its source-linked journal.

**5. Deterministic detection rule.** For each effective payment old enough to post, collect all payment GL rows. Flag if none exist; any contributing currency differs; journal debits do not equal credits; AP debit on `200000-ACCOUNTS-PAYABLE` differs from payment amount beyond quantum; or cash credit on `100000-CASH` differs beyond quantum. Multiple journal lines and cost-center splits are allowed. Rows with transaction types `PAYMENT_REVERSAL`, `BANK_FEE`, or `FX_SETTLEMENT` do not enter the source aggregate.

**6. SQL-style pseudocode.**

```sql
WITH pg AS (
 SELECT p.payment_id, p.payment_amount, p.payment_currency,
   COUNT(g.journal_line_id) AS line_count,
   SUM(g.debit) AS total_debit, SUM(g.credit) AS total_credit,
   SUM(CASE WHEN g.gl_account='200000-ACCOUNTS-PAYABLE' THEN g.debit ELSE 0 END) AS ap_debit,
   SUM(CASE WHEN g.gl_account='100000-CASH' THEN g.credit ELSE 0 END) AS cash_credit,
   SUM(CASE WHEN g.currency<>p.payment_currency THEN 1 ELSE 0 END) AS currency_errors
 FROM payments p LEFT JOIN gl_entries g
   ON g.source_transaction_id=p.payment_id
  AND NORM_STATUS(g.transaction_type)='PAYMENT'
 WHERE EFFECTIVE_PAYMENT(p)=1
 GROUP BY p.payment_id,p.payment_amount,p.payment_currency
)
SELECT *, CASE WHEN line_count=0 OR currency_errors>0
                    OR NOT WITHIN_MONEY(total_debit,total_credit,payment_currency)
                    OR NOT WITHIN_MONEY(ap_debit,payment_amount,payment_currency)
                    OR NOT WITHIN_MONEY(cash_credit,payment_amount,payment_currency)
               THEN 1 ELSE 0 END AS is_anomaly
FROM pg;
```

**7. Thresholds and tolerances.** `GL_POSTING_LAG_BUSINESS_DAYS=0`, fixed because completed benchmark payment journals post on payment date. Money tolerance is currency quantum. No validation tuning.

**8. Data normalization.** Shared statuses, currency, dates, and decimal money. Account strings are trimmed and uppercased but otherwise exact.

**9. Edge cases.** Legitimate cost-center/account splits match if required AP/cash control totals agree. A payment reversal is excluded by effective-payment status and separate transaction type. FX on the bank side does not alter the payment journal. Alternative charts of accounts would fail because v1 has no account-role mapping table.

**10. Missing-data behavior.** Unavailable GL table or invalid payment amount/currency is insufficient. With a complete GL snapshot and elapsed posting lag, no source-linked journal is positive evidence.

**11. Expected output.** Return payment and all payment journal-line IDs; reason reports payment amount, AP debit, cash credit, total debit/credit, currencies, and line count.

**12. Evidence requirements.** Payment row plus the complete source-linked payment journal; for missing posting, payment row and a trace stating zero qualifying GL rows in a complete snapshot.

**13. Expected strengths.** Balanced-but-wrong journals, wrong accounts/currency, missing posting, and double-entry violations.

**14. Expected failure modes.** Alternate chart-of-account conventions, delayed posting policies, or correcting journals without explicit linkage.

### 5.10 RSQL_F10_V1 — F10_WRONG_ACCOUNTING_PERIOD

**1. Failure type.** A positive is a source-linked payment journal whose `accounting_period` is not the `YYYY-MM` of the payment's economic date, or whose posting-date month disagrees with its stored period. A negative uses the payment period, irrespective of later bank posting.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `payment_date`; purpose: define the economic date and expected period.
- Table: `gl_entries`; required fields: `journal_id`, `journal_line_id`, `transaction_type`, `source_transaction_id`, `posting_date`, `accounting_period`; purpose: provide observed ledger dates and periods.

**3. Join path.** `payments.payment_id -> gl_entries.source_transaction_id` where transaction type is payment; inner join because F10 evaluates existing journals. Missing journal is left to F09 and is insufficient for F10.

**4. Reasoning complexity.** Tier 2 — one-hop relational. **Hop count: 1.** One source relationship links economic and accounting dates.

**5. Deterministic detection rule.** `expected_period = FORMAT_YYYY_MM(payment_date)`. Flag if any payment journal line has `accounting_period <> expected_period`, or `FORMAT_YYYY_MM(posting_date) <> accounting_period`. No grace crosses a month boundary. Bank transaction/statement dates never determine the economic period.

**6. SQL-style pseudocode.**

```sql
SELECT p.payment_id,g.journal_id,
 CASE WHEN SUM(CASE WHEN g.accounting_period<>FORMAT_YYYY_MM(p.payment_date)
                          OR FORMAT_YYYY_MM(g.posting_date)<>g.accounting_period
                     THEN 1 ELSE 0 END)>0
      THEN 1 ELSE 0 END AS is_anomaly
FROM payments p JOIN gl_entries g
 ON g.source_transaction_id=p.payment_id
AND NORM_STATUS(g.transaction_type)='PAYMENT'
GROUP BY p.payment_id,g.journal_id;
```

**7. Thresholds and tolerances.** `ACCOUNTING_PERIOD_TOLERANCE=0 periods`, globally fixed.

**8. Data normalization.** Strict ISO dates; accounting period must match regex `^[0-9]{4}-[0-9]{2}$` and a real month.

**9. Edge cases.** Legitimate bank clearing after month-end matches because bank dates are ignored. Organizations using accrual/reversal policies different from payment-date accounting would need a policy table that v1 lacks. Closed-period adjustments are flagged.

**10. Missing-data behavior.** Missing/invalid payment date, posting date, period, or journal is insufficient. A complete period-aligned journal is `MATCH`.

**11. Expected output.** Return payment and all lines of the affected journal; reason states payment date, expected period, observed posting dates, and periods.

**12. Evidence requirements.** Payment date and every source-linked journal line's posting date/accounting period.

**13. Expected strengths.** Explicit period shifts and internal posting-date/period inconsistencies.

**14. Expected failure modes.** Legitimate policy-based accrual timing not modeled in the schema.

### 5.11 RSQL_F11_V1 — F11_VENDOR_MASTER_CHANGE_CONFLICT

**1. Failure type.** A positive is a payment that uses a bank token different from the vendor token effective at payment creation and has a returned/failed bank outcome. A negative uses the effective token, including a payment correctly using an old token before a later change.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `vendor_id`, `bank_account_id`, `created_at`, `reference_number`, `settlement_status`; purpose: provide the vendor, destination snapshot, decision time, and bank reference.
- Table: `vendors`; required fields: `vendor_id`, `bank_account_token`; purpose: provide current vendor state and history anchor.
- Table: `vendor_change_log`; required fields: `change_id`, `vendor_id`, `field_changed`, `old_value`, `new_value`, `changed_at`; purpose: reconstruct the bank token effective at payment creation.
- Table: `bank_transactions`; required fields: `bank_transaction_id`, `payment_reference`, `counterparty_token`, `status`, `posted_date`; purpose: provide external use of the destination and settlement result.

**3. Join path.** `payments.vendor_id -> vendors.vendor_id -> vendor_change_log.vendor_id`, filtered to `field_changed='bank_account_token'`; separately `NORM_REFERENCE(payments.reference_number) -> NORM_REFERENCE(bank_transactions.payment_reference)`. Payment `bank_account_id` compares to vendor/change tokens; it must never join to bank transaction `bank_account_id`.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** Effective-state reconstruction follows payment to vendor and then vendor history; bank outcome is a parallel one-hop link.

**5. Deterministic detection rule.** Reconstruct `effective_token(T)` at `T=payment.created_at`: use the latest qualifying change with `changed_at<=T` and its `new_value`; if none, use `old_value` from the earliest qualifying change after T; if no changes, use current vendor token. When payment token differs, require a decisive history row establishing the transition from the payment token to the effective token; otherwise return insufficient. Flag when the decisive change exists, matched bank `counterparty_token` equals the stale payment token, and bank status is `RETURNED` or payment settlement status is `FAILED`. If token differs but settlement posted successfully, return match for F11 while retaining a warning trace.

**6. SQL-style pseudocode.**

```sql
WITH history AS (
 SELECT p.payment_id,
   LAST_VALUE_BEFORE(vcl.changed_at,vcl.new_value,p.created_at) AS last_new,
   FIRST_VALUE_AFTER(vcl.changed_at,vcl.old_value,p.created_at) AS next_old
 FROM payments p JOIN vendors v ON v.vendor_id=p.vendor_id
 LEFT JOIN vendor_change_log vcl ON vcl.vendor_id=v.vendor_id
   AND NORM_STATUS(vcl.field_changed)='BANK_ACCOUNT_TOKEN'
 GROUP BY p.payment_id
), effective AS (
 SELECT p.*, COALESCE(h.last_new,h.next_old,v.bank_account_token) AS effective_token,
        DECISIVE_TOKEN_CHANGE_EXISTS(p.vendor_id,p.bank_account_id,
                                     COALESCE(h.last_new,h.next_old,v.bank_account_token),
                                     p.created_at) AS decisive_change
 FROM payments p JOIN vendors v ON v.vendor_id=p.vendor_id
 JOIN history h ON h.payment_id=p.payment_id
)
SELECT e.payment_id,b.bank_transaction_id,
 CASE WHEN e.decisive_change=1 AND e.bank_account_id<>e.effective_token
            AND b.counterparty_token=e.bank_account_id
            AND (NORM_STATUS(b.status)='RETURNED'
                 OR NORM_STATUS(e.settlement_status)='FAILED')
      THEN 1 ELSE 0 END AS is_anomaly
FROM effective e JOIN bank_transactions b
 ON NORM_REFERENCE(b.payment_reference)=NORM_REFERENCE(e.reference_number);
```

**7. Thresholds and tolerances.** No numeric tolerance. Temporal comparison is exact at timestamp precision. No tuning.

**8. Data normalization.** Tokens/IDs trim only and remain case-sensitive; change field/status uses shared status normalization; references and timestamps use shared functions.

**9. Edge cases.** Payment before a change uses the next change's `old_value` and matches. Multiple changes use the latest decisive transition; a mismatch without a transition from payment token to effective token is insufficient. Vendor merger/currency/terms changes do not satisfy this bank-token rule. Successful use of a stale-but-still-valid token is not labeled F11 under the frozen positive definition.

**10. Missing-data behavior.** Missing vendor, token, timestamp, history needed to explain a current mismatch, or matched bank outcome is insufficient. No history plus payment token equal to current token is `MATCH`.

**11. Expected output.** Return payment, vendor, decisive change row(s), and bank transaction; reason states effective timestamp, old/effective/payment/counterparty tokens, and bank status.

**12. Evidence requirements.** Payment, vendor current record, the change rows required to reconstruct state, and matched bank transaction.

**13. Expected strengths.** Exact temporal master-data conflicts and stale-token returns.

**14. Expected failure modes.** Incomplete change history, multiple banking instruments simultaneously valid, or external bank-token aliases.

### 5.12 RSQL_F12_V1 — F12_ERP_PAYMENT_MISSING_FROM_BANK

**1. Failure type.** A positive is a completed/settled ERP payment older than its method-specific clearing window with no posted or returned non-fee bank record carrying its payment reference. A negative has external bank evidence or is still inside the clearing window.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `payment_date`, `payment_method`, `payment_status`, `settlement_status`, `reference_number`; purpose: define the expected settlement and clearing window.
- Table: `bank_transactions`; required fields: `bank_transaction_id`, `payment_reference`, `transaction_type`, `direction`, `status`, `posted_date`; purpose: supply or disprove external settlement evidence.

**3. Join path.** Logical left join `NORM_REFERENCE(payments.reference_number) -> NORM_REFERENCE(bank_transactions.payment_reference)`. Relationship absence is the signal; the bank snapshot must be complete through the cutoff.

**4. Reasoning complexity.** Tier 2 — one-hop relational. **Hop count: 1.** One cross-system reference link is tested for absence.

**5. Deterministic detection rule.** Restrict to payments with completed/settled status and non-NULL reference. Compute business-day age from payment date to cutoff. A bank record counts as external evidence when it has the normalized reference, is not a separately typed bank fee, and is posted/returned by the cutoff. Flag only if evidence count is zero and age is strictly greater than the method clearing limit. A submitted/pending payment is never F12; inside-window absence is normal.

**6. SQL-style pseudocode.**

```sql
SELECT p.payment_id, COUNT(b.bank_transaction_id) AS bank_evidence_count,
 CASE WHEN PAYMENT_REFERENCE_USE_COUNT(NORM_REFERENCE(p.reference_number))<>1 THEN NULL
      WHEN EFFECTIVE_PAYMENT(p)=1
            AND BUSINESS_DAYS_BETWEEN(p.payment_date,:as_of)
                > CLEARING_LIMIT(p.payment_method)
            AND COUNT(b.bank_transaction_id)=0
      THEN 1 ELSE 0 END AS is_anomaly
FROM payments p LEFT JOIN bank_transactions b
 ON NORM_REFERENCE(b.payment_reference)=NORM_REFERENCE(p.reference_number)
AND NORM_STATUS(b.transaction_type)<>'BANK_FEE'
AND NORM_STATUS(b.status) IN ('POSTED','RETURNED')
AND b.posted_date<=:as_of
GROUP BY p.payment_id;
```

**7. Thresholds and tolerances.** Clearing limits: ACH 3, wire 1, check 10, virtual card 2 business days; fixed from config/methodology. `CLEARING_GRACE_BUSINESS_DAYS=0`, fixed. No validation tuning.

**8. Data normalization.** Shared reference, method/status, and date functions. Method synonyms are not inferred beyond exact normalized configured values.

**9. Edge cases.** Friday-to-Monday ACH timing is normal under business-day counting. Checks receive ten business days. A returned transaction is bank evidence and routes toward F11 or a return trace, not F12. A payment reference reused across payments can make matching ambiguous and returns insufficient rather than anomaly.

**10. Missing-data behavior.** Unavailable bank table, NULL/duplicate payment reference, invalid date/method, or incomplete cutoff snapshot is insufficient. Complete-table zero-match after the window is positive by definition.

**11. Expected output.** Return payment ID; no nonexistent bank ID is invented. Reason reports method, payment date, cutoff, business-day age, limit, normalized reference, and zero bank records.

**12. Evidence requirements.** Payment record and an auditable anti-join count over the complete bank snapshot.

**13. Expected strengths.** Explicit overdue cross-system absence while preserving normal clearing delays.

**14. Expected failure modes.** Bank reference corruption/reuse, holiday calendars, batched bank records without payment-level references, and incomplete statement feeds.

### 5.13 RSQL_F13_V1 — F13_BANK_TRANSACTION_MISSING_FROM_ERP

**1. Failure type.** A positive is a posted outgoing operational debit (ACH, wire, check, or card settlement) with no matching ERP payment. A normal negative is matched to a payment, or is a separately typed bank fee with a balanced fee journal, or a documented reversal credit.

**2. Required tables.**

- Table: `bank_transactions`; required fields: `bank_transaction_id`, `payment_reference`, `transaction_type`, `direction`, `amount`, `currency`, `status`, `posted_date`; purpose: define the externally observed outgoing transaction.
- Table: `payments`; required fields: `payment_id`, `reference_number`; purpose: test whether ERP has the corresponding payment.
- Table: `gl_entries`; required fields: `journal_id`, `journal_line_id`, `transaction_type`, `source_transaction_id`, `debit`, `credit`, `currency`; purpose: validate the legitimate bank-fee exception.

**3. Join path.** Left join bank `payment_reference -> payments.reference_number`; parallel left join `bank_transaction_id -> gl_entries.source_transaction_id` with transaction-type discriminator. Both are one-hop logical relationships.

**4. Reasoning complexity.** Tier 2 — one-hop relational. **Hop count: 1.** The bank debit is checked against ERP payment and accounting links in parallel.

**5. Deterministic detection rule.** For posted debits through cutoff: if normalized transaction type is `BANK_FEE`, return match only when a balanced `BANK_FEE` journal linked to the bank transaction exists; otherwise a missing fee journal is anomalous F13. If type is `PAYMENT_REVERSAL` or direction is credit, F13 does not apply. For operational debit types `{ACH_DEBIT,WIRE_DEBIT,CHECK_CLEARING,CARD_SETTLEMENT}`, flag when no uniquely matched ERP payment exists. Unknown debit types without a payment return insufficient, not anomaly.

**6. SQL-style pseudocode.**

```sql
SELECT b.bank_transaction_id,
 COUNT(DISTINCT p.payment_id) AS payment_matches,
 BALANCED_SOURCE_JOURNAL_EXISTS(b.bank_transaction_id,'BANK_FEE') AS fee_gl_exists,
 CASE WHEN NORM_STATUS(b.transaction_type)='BANK_FEE' AND fee_gl_exists=1 THEN 0
      WHEN NORM_STATUS(b.transaction_type)='BANK_FEE' AND fee_gl_exists=0 THEN 1
      WHEN NORM_STATUS(b.transaction_type) IN
           ('ACH_DEBIT','WIRE_DEBIT','CHECK_CLEARING','CARD_SETTLEMENT')
           AND COUNT(DISTINCT p.payment_id)=0 THEN 1
      WHEN NORM_STATUS(b.transaction_type) IN
           ('ACH_DEBIT','WIRE_DEBIT','CHECK_CLEARING','CARD_SETTLEMENT')
           AND COUNT(DISTINCT p.payment_id)=1 THEN 0
      ELSE NULL END AS is_anomaly
FROM bank_transactions b
LEFT JOIN payments p
 ON NORM_REFERENCE(p.reference_number)=NORM_REFERENCE(b.payment_reference)
LEFT JOIN gl_entries g ON g.source_transaction_id=b.bank_transaction_id
WHERE NORM_STATUS(b.direction)='DEBIT' AND NORM_STATUS(b.status)='POSTED'
  AND b.posted_date<=:as_of
GROUP BY b.bank_transaction_id;
```

**7. Thresholds and tolerances.** Journal balance uses currency quantum; no other thresholds or tuning.

**8. Data normalization.** Shared transaction type/status/reference/currency/money functions.

**9. Edge cases.** Accounted bank fees match without ERP payments. Reversal credits are excluded. Manual wires are anomalous. Unknown debit types are insufficient. A normalized reference matching more than one payment is ambiguous and insufficient unless F15 resolves a reciprocal cross-match.

**10. Missing-data behavior.** Unavailable payment table makes ordinary unmatched debit insufficient. Complete table and zero match is positive. Bank fee requires GL availability; absent GL table is insufficient, while complete GL with no fee journal is positive.

**11. Expected output.** Return bank transaction and any fee journal evidence; reason states transaction type, direction, amount, normalized reference, and payment-match count.

**12. Evidence requirements.** Bank row plus matching-payment query result; fee exceptions require every line of the balanced fee journal.

**13. Expected strengths.** Manual/unrecorded outgoing transactions and legitimate bank-fee separation.

**14. Expected failure modes.** Batched bank debits, unknown bank transaction coding, reference truncation, or legitimate non-AP disbursements.

### 5.14 RSQL_F14_V1 — F14_BANK_ERP_AMOUNT_MISMATCH

**1. Failure type.** A positive is a uniquely reference-matched payment/bank debit in the same currency whose amount delta exceeds currency quantum and is not exactly explained by a balanced source-linked fee journal. A negative is exact, within rounding tolerance, fully fee-explained, or a documented FX settlement.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `payment_currency`, `payment_amount`, `reference_number`; purpose: provide the ERP amount/currency and match reference.
- Table: `bank_transactions`; required fields: `bank_transaction_id`, `payment_reference`, `currency`, `amount`, `direction`, `status`, `posted_date`; purpose: provide the external settlement amount/currency.
- Table: `gl_entries`; required fields: `journal_id`, `journal_line_id`, `transaction_type`, `source_transaction_id`, `debit`, `credit`, `currency`; purpose: quantify balanced fee or FX accounting explanations.
- Table: `audit_log`; required fields: `event_id`, `entity_type`, `entity_id`, `event_type`, `timestamp`; purpose: validate only the structured FX legitimate exception.

**3. Join path.** `payments.reference_number -> bank_transactions.payment_reference`; then `bank_transactions.bank_transaction_id -> gl_entries.source_transaction_id` for `BANK_FEE` or `FX_SETTLEMENT`. `bank_transaction_id -> audit_log.entity_id` is a parallel operational-event link. Left joins preserve absent adjustments.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 2.** It follows payment to bank settlement and then to accounting explanation.

**5. Deterministic detection rule.** Require exactly one non-fee posted bank debit matched by normalized reference. If currencies match, compute `delta_abs=ABS(payment_amount-bank_amount)` and `explained_fee=SUM(debit)` across balanced `BANK_FEE` journals whose source is that matched bank transaction. Match when `delta_abs<=quantum` or `ABS(delta_abs-explained_fee)<=quantum`; otherwise flag. If currencies differ, return match only when a balanced `FX_SETTLEMENT` journal linked to the bank transaction and a pre-cutoff `FX_CONVERSION_APPLIED` audit event both exist; otherwise insufficient because no FX rate table exists. F15 reciprocal cross-match takes precedence over F14.

**6. SQL-style pseudocode.**

```sql
WITH matched AS (
 SELECT p.*,b.bank_transaction_id,b.amount AS bank_amount,b.currency AS bank_currency,
        COUNT(*) OVER (PARTITION BY p.payment_id) AS match_count
 FROM payments p JOIN bank_transactions b
  ON NORM_REFERENCE(b.payment_reference)=NORM_REFERENCE(p.reference_number)
 WHERE NORM_STATUS(b.direction)='DEBIT' AND NORM_STATUS(b.status)='POSTED'
   AND NORM_STATUS(b.transaction_type)<>'BANK_FEE' AND b.posted_date<=:as_of
), adjusted AS (
 SELECT m.*, BALANCED_DEBIT_TOTAL(m.bank_transaction_id,'BANK_FEE') AS explained_fee,
        BALANCED_JOURNAL_EXISTS(m.bank_transaction_id,'FX_SETTLEMENT') AS fx_gl,
        EVENT_EXISTS(m.bank_transaction_id,'FX_CONVERSION_APPLIED',:as_of) AS fx_event
 FROM matched m
)
SELECT *, CASE
 WHEN match_count<>1 THEN NULL
 WHEN payment_currency<>bank_currency AND fx_gl=1 AND fx_event=1 THEN 0
 WHEN payment_currency<>bank_currency THEN NULL
 WHEN ABS(payment_amount-bank_amount)<=CURRENCY_QUANTUM(payment_currency) THEN 0
 WHEN ABS(ABS(payment_amount-bank_amount)-explained_fee)
          <=CURRENCY_QUANTUM(payment_currency) THEN 0
 ELSE 1 END AS is_anomaly
FROM adjusted;
```

**7. Thresholds and tolerances.** Currency quantum fixed. Fee explanation must match the absolute delta within quantum. No inferred FX tolerance and no validation tuning.

**8. Data normalization.** Shared references, status/type, currency, and money. Only audit event type `FX_CONVERSION_APPLIED` is permitted; audit free text and old/new narrative are not used.

**9. Edge cases.** A 25-unit delta with a balanced 25-unit fee journal matches; the same delta without it is anomalous. Separately posted fees do not alter an exact primary debit. Currency mismatch without both structured FX artifacts is insufficient. Partial settlement should be represented through payment allocations/status; an unexplained bank delta remains F14.

**10. Missing-data behavior.** Missing/ambiguous bank match, currency, amount, GL table, or required cross-currency evidence is insufficient. A complete same-currency mismatch with no adjustment row is positive absence evidence.

**11. Expected output.** Return payment, bank transaction, and adjustment GL/audit IDs when present; reason reports both amounts/currencies, absolute delta, explained fee, and FX evidence booleans.

**12. Evidence requirements.** Payment and unique matched bank transaction; a normal fee/FX decision additionally requires complete linked journal lines and the structured FX event where applicable.

**13. Expected strengths.** Exact same-currency mismatches and explicit fee-accounting exceptions.

**14. Expected failure modes.** FX without structured evidence, aggregate bank fees, discounts, or external processor adjustments lacking source links.

### 5.15 RSQL_F15_V1 — F15_INCORRECT_PAYMENT_BANK_MATCH

**1. Failure type.** A positive is a reciprocal two-payment/two-bank cross-match: each bank row references the other payment, while amount, currency, destination token, and date uniquely support the opposite pairing. A negative has a consistent reference/economic match, a legitimate batch, or ambiguous nonunique candidates.

**2. Required tables.**

- Table: `payments`; required fields: `payment_id`, `vendor_id`, `bank_account_id`, `payment_date`, `payment_currency`, `payment_amount`, `reference_number`, `payment_status`, `settlement_status`; purpose: provide current reference assignments and economic candidates.
- Table: `bank_transactions`; required fields: `bank_transaction_id`, `counterparty_token`, `transaction_date`, `posted_date`, `currency`, `amount`, `payment_reference`, `direction`, `status`; purpose: provide the externally matched settlements.
- Table: `payment_allocations`; required fields: `payment_id`, `invoice_id`, `allocated_amount`, `allocation_date`; purpose: prove each candidate payment supports a distinct obligation and identify evidence rows.
- Table: `invoices`; required fields: `invoice_id`, `vendor_id`; purpose: validate the allocated obligations and their identity.

**3. Join path.** Current link: bank `payment_reference -> payment.reference_number`; candidate economic link: equal currency/token, within-money amount, and date window. Evidence then follows each candidate `payment_id -> payment_allocations.payment_id -> invoices.invoice_id`. The reciprocal cycle is `bank A -> referenced payment B -> bank B -> referenced payment A`, with both alternative economic links verified.

**4. Reasoning complexity.** Tier 3 — multi-hop relational. **Hop count: 3.** The reciprocal relationship chain and obligation validation require at least three traversals.

**5. Deterministic detection rule.** Build `ref_payment(b)` from normalized reference and require uniqueness. Build economic candidates `econ_payment(b)` requiring effective payment, same currency, `WITHIN_MONEY` amount, `bank.counterparty_token=payment.bank_account_id`, and absolute payment/transaction-date difference within `CROSS_MATCH_DATE_WINDOW_CALENDAR_DAYS`. Require exactly one economic candidate and at least one valid allocation/invoice for each involved payment. A cross edge exists when referenced and economic payment IDs differ. Flag only when two cross edges form a reciprocal cycle and the two payment amounts are distinct beyond quantum. F14 is suppressed for those four records.

**6. SQL-style pseudocode.**

```sql
WITH ref_match AS (
 SELECT b.bank_transaction_id,MIN(p.payment_id) AS ref_payment_id
 FROM bank_transactions b JOIN payments p
  ON NORM_REFERENCE(b.payment_reference)=NORM_REFERENCE(p.reference_number)
 WHERE POSTED_DEBIT(b)=1
 GROUP BY b.bank_transaction_id
 HAVING COUNT(*)=1
), econ_match AS (
 SELECT b.bank_transaction_id,MIN(p.payment_id) AS econ_payment_id
 FROM bank_transactions b JOIN payments p
  ON b.currency=p.payment_currency
 AND WITHIN_MONEY(b.amount,p.payment_amount,b.currency)
 AND b.counterparty_token=p.bank_account_id
 AND ABS(DATE_DIFF(b.transaction_date,p.payment_date))<=:cross_days
 WHERE POSTED_DEBIT(b)=1 AND EFFECTIVE_PAYMENT(p)=1
   AND EXISTS (SELECT 1 FROM payment_allocations pa JOIN invoices i
               ON i.invoice_id=pa.invoice_id
               WHERE pa.payment_id=p.payment_id AND i.vendor_id=p.vendor_id)
 GROUP BY b.bank_transaction_id
 HAVING COUNT(*)=1
), cross_edge AS (
 SELECT r.bank_transaction_id,r.ref_payment_id,e.econ_payment_id
 FROM ref_match r JOIN econ_match e USING (bank_transaction_id)
 WHERE r.ref_payment_id<>e.econ_payment_id
)
SELECT a.bank_transaction_id,b.bank_transaction_id,
       a.econ_payment_id,b.econ_payment_id,1 AS is_anomaly
FROM cross_edge a JOIN cross_edge b
 ON a.ref_payment_id=b.econ_payment_id
AND a.econ_payment_id=b.ref_payment_id
AND a.bank_transaction_id<b.bank_transaction_id
JOIN payments p1 ON p1.payment_id=a.econ_payment_id
JOIN payments p2 ON p2.payment_id=b.econ_payment_id
WHERE p1.vendor_id=p2.vendor_id
  AND NOT WITHIN_MONEY(p1.payment_amount,p2.payment_amount,p1.payment_currency);
```

**7. Thresholds and tolerances.** `CROSS_MATCH_DATE_WINDOW_CALENDAR_DAYS=7`, globally fixed from the benchmark mechanism. Amount equality uses currency quantum. Candidate/reference uniqueness is exactly one. No validation tuning.

**8. Data normalization.** Shared reference, dates, statuses, currency, and money; bank counterparty/payment destination tokens are trimmed exact strings. Company `bank_account_id` values are never compared to payment destination tokens.

**9. Edge cases.** Identical-amount payments are insufficient because the swap is not observable. More than one economic candidate is insufficient, not arbitrarily resolved. Batches match when one payment's amount equals its bank debit and allocations support multiple invoices. F14-like one-sided mismatch lacks a reciprocal cycle and stays F14.

**10. Missing-data behavior.** Missing token/reference/date/currency/amount, nonunique candidate, or missing allocation/invoice evidence is insufficient. A unique consistent pairing is `MATCH`.

**11. Expected output.** Return two payments, two bank transactions, and all allocations/invoices establishing their obligations; reason gives both current pairs, both proposed pairs, amounts, tokens, and dates.

**12. Evidence requirements.** Both payment rows, both bank rows, at least one valid allocation and invoice per payment, and every field used in reference/economic matching.

**13. Expected strengths.** Reciprocal swapped references among similar same-vendor settlements without relying on ground-truth causal edges.

**14. Expected failure modes.** Identical amounts, larger cycles, batch-level bank references, missing counterparty tokens, or more than two plausible candidates.

## 6. Baseline rule registry

| Rule ID | Failure Type | Tables | Hop Count | Tier | Detection Mechanism | Tunable Parameters | Output Class |
|---|---|---|---:|---|---|---|---|
| RSQL_F01_V1 | F01 duplicate invoice | invoices | 0 | Tier 1 | normalized/fuzzy self-duplicate | duplicate days, similarity | F01_DUPLICATE_INVOICE |
| RSQL_F02_V1 | F02 PO/invoice amount | invoices, invoice_lines, purchase_orders, po_lines | 2 | Tier 3 | authorized line/header variance | fixed PO tolerance | F02_PO_INVOICE_AMOUNT_MISMATCH |
| RSQL_F03_V1 | F03 quantity mismatch | invoices, invoice_lines, po_lines | 2 | Tier 3 | exact linked quantity inequality | none | F03_QUANTITY_MISMATCH |
| RSQL_F04_V1 | F04 wrong vendor | invoices, purchase_orders | 1 | Tier 2 | FK-linked vendor inequality | none | F04_INCORRECT_VENDOR_ASSOCIATION |
| RSQL_F05_V1 | F05 unsupported payment | payments, payment_allocations, invoices | 2 | Tier 3 | relationship anti-join | none | F05_PAYMENT_WITHOUT_VALID_INVOICE |
| RSQL_F06_V1 | F06 double payment | invoices, payment_allocations, payments | 2 | Tier 3 | successful allocation overage | fixed quantum | F06_INVOICE_PAID_TWICE |
| RSQL_F07_V1 | F07 partial/residual | invoices, payment_allocations, payments | 2 | Tier 3 | paid-status residual | fixed quantum | F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE |
| RSQL_F08_V1 | F08 approval failure | payments, payment_allocations, invoices, approval_events, employees | 4 | Tier 3 | policy sequence/authority | fixed approval ladder | F08_APPROVAL_WORKFLOW_FAILURE |
| RSQL_F09_V1 | F09 GL mismatch | payments, gl_entries | 1 | Tier 2 | source/control-account totals | fixed quantum/lag | F09_GL_POSTING_MISMATCH |
| RSQL_F10_V1 | F10 wrong period | payments, gl_entries | 1 | Tier 2 | economic month inequality | none | F10_WRONG_ACCOUNTING_PERIOD |
| RSQL_F11_V1 | F11 vendor change conflict | payments, vendors, vendor_change_log, bank_transactions | 2 | Tier 3 | temporal effective-state reconstruction | none | F11_VENDOR_MASTER_CHANGE_CONFLICT |
| RSQL_F12_V1 | F12 ERP missing bank | payments, bank_transactions | 1 | Tier 2 | clearing-window anti-join | fixed method windows | F12_ERP_PAYMENT_MISSING_FROM_BANK |
| RSQL_F13_V1 | F13 bank missing ERP | bank_transactions, payments, gl_entries | 1 | Tier 2 | reverse anti-join with fee exception | fixed quantum | F13_BANK_TRANSACTION_MISSING_FROM_ERP |
| RSQL_F14_V1 | F14 bank/ERP amount | payments, bank_transactions, gl_entries, audit_log | 2 | Tier 3 | delta minus documented adjustment | fixed quantum | F14_BANK_ERP_AMOUNT_MISMATCH |
| RSQL_F15_V1 | F15 wrong bank match | payments, bank_transactions, payment_allocations, invoices | 3 | Tier 3 | reciprocal unique cross-match | fixed 7-day window | F15_INCORRECT_PAYMENT_BANK_MATCH |

## 7. Table dependency matrix

Abbreviations: V=`vendors`, VC=`vendor_change_log`, PO=`purchase_orders`, POL=`po_lines`, I=`invoices`, IL=`invoice_lines`, AE=`approval_events`, E=`employees`, P=`payments`, PA=`payment_allocations`, GL=`gl_entries`, BT=`bank_transactions`, BS=`bank_statements`, AL=`audit_log`.

| Failure | V | VC | PO | POL | I | IL | AE | E | P | PA | GL | BT | BS | AL |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| F01 |  |  |  |  | ✓ |  |  |  |  |  |  |  |  |  |
| F02 |  |  | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| F03 |  |  |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| F04 |  |  | ✓ |  | ✓ |  |  |  |  |  |  |  |  |  |
| F05 |  |  |  |  | ✓ |  |  |  | ✓ | ✓ |  |  |  |  |
| F06 |  |  |  |  | ✓ |  |  |  | ✓ | ✓ |  |  |  |  |
| F07 |  |  |  |  | ✓ |  |  |  | ✓ | ✓ |  |  |  |  |
| F08 |  |  |  |  | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |  |  |  |
| F09 |  |  |  |  |  |  |  |  | ✓ |  | ✓ |  |  |  |
| F10 |  |  |  |  |  |  |  |  | ✓ |  | ✓ |  |  |  |
| F11 | ✓ | ✓ |  |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| F12 |  |  |  |  |  |  |  |  | ✓ |  |  | ✓ |  |  |
| F13 |  |  |  |  |  |  |  |  | ✓ |  | ✓ | ✓ |  |  |
| F14 |  |  |  |  |  |  |  |  | ✓ |  | ✓ | ✓ |  | ✓ |
| F15 |  |  |  |  | ✓ |  |  |  | ✓ | ✓ |  | ✓ |  |  |

`bank_statements` is intentionally unused: statements validate bank arithmetic but do not provide transaction-level linkage needed by these 15 classes.

## 8. Complexity and exact-hop analysis

| Complexity | Count | Rules |
|---|---:|---|
| Tier 1 — single-record / zero-hop | 1 | F01 |
| Tier 2 — one-hop relational | 5 | F04, F09, F10, F12, F13 |
| Tier 3 — multi-hop relational | 9 | F02, F03, F05, F06, F07, F08, F11, F14, F15 |

| Hop count | Count | Rules |
|---:|---:|---|
| 0 | 1 | F01 |
| 1 | 5 | F04, F09, F10, F12, F13 |
| 2 | 7 | F02, F03, F05, F06, F07, F11, F14 |
| 3 | 1 | F15 |
| 4 | 1 | F08 |

Hop count is the maximum explicit entity relationship traversed for the minimum legitimate anomaly evidence, not the number of tables mentioned in a query or the number of SQL joins used for aggregation.

## 9. Threshold registry

| Parameter | Definition | Frozen initial value / search space | Rationale | Policy |
|---|---|---|---|---|
| AS_OF_DATE | observation cutoff | 2026-06-30 | benchmark configuration | global fixed |
| MONEY_QUANTUM | absolute rounding tolerance | JPY 1; USD/EUR/GBP/CAD 0.01 | native precision | global fixed |
| DUPLICATE_DATE_WINDOW_DAYS | max invoice-date separation | initial 14; grid 7,14,30 | separate duplicates from recurring cycles | **VALIDATION-TUNED** |
| DUPLICATE_REFERENCE_SIMILARITY | minimum normalized edit similarity | initial .90; grid .85,.90,.95,1.00 | tolerate nonexact references | **VALIDATION-TUNED** |
| PO_TOLERANCE_PERCENT | authorized price/charge variance | 2.0% | `config.yaml` control | global fixed |
| QUANTITY_TOLERANCE | allowed unit difference | 0 | quantities are exact integers | global fixed |
| MIN_POSITIVE_ALLOCATION | allocation considered support | strictly greater than 0 | zero does not settle an obligation | global fixed |
| OVERPAYMENT_TOLERANCE | excess ignored as rounding | currency quantum | avoid subprecision flags | global fixed |
| RESIDUAL_TOLERANCE | residual ignored as rounding | currency quantum | avoid subprecision flags | global fixed |
| APPROVAL_POLICY | amount-to-role ladder | 500/10k/50k/250k as Section 5.8 | benchmark business policy | global fixed |
| GL_POSTING_LAG_BUSINESS_DAYS | completed payment GL wait | 0 | benchmark posts same day | global fixed |
| ACCOUNTING_PERIOD_TOLERANCE | allowed period displacement | 0 periods | benchmark economic-period policy | global fixed |
| ACH_CLEARING_BD | ACH settlement window | 3 | configuration | global fixed |
| WIRE_CLEARING_BD | wire settlement window | 1 | configuration | global fixed |
| CHECK_CLEARING_BD | check settlement window | 10 | configuration | global fixed |
| VIRTUAL_CARD_CLEARING_BD | card settlement window | 2 | generator methodology | global fixed |
| CLEARING_GRACE_BD | extra bank absence grace | 0 | method windows already include grace | global fixed |
| CROSS_MATCH_DATE_WINDOW_DAYS | F15 economic-candidate window | 7 calendar days | frozen failure mechanism | global fixed |
| CROSS_MATCH_CANDIDATE_COUNT | number of admissible economic/reference candidates | exactly 1 each | avoid arbitrary ambiguous matching | global fixed |

Only the two F01 parameters may be tuned. The exact grid, objective, and tie-break are frozen: maximize macro-F1 over all 16 output classes on validation; ties choose higher similarity, then shorter date window, then the initial value if still tied. The selected pair must be written to the baseline run manifest before any test inference. No rule, join, normalization, or other parameter may be validation-tuned.

## 10. Ambiguity register

No material ambiguity blocks implementation. The schema limitations below have explicit v1 decisions and therefore may not be revisited after test results.

| Topic / affected failure | Problem | Why it matters | Frozen decision before implementation |
|---|---|---|---|
| Approval policy / F08 | no policy table exists | required levels otherwise ambiguous | use the fixed ladder in Section 5.8 |
| Observation cutoff / F12 | no dataset metadata table exists | delay status needs a reference date | harness supplies fixed 2026-06-30 |
| Table completeness / absence rules | SQL cannot distinguish missing row from incomplete load | affects F05/F09/F12/F13/F14 | harness validates complete snapshots; failed table load yields insufficient |
| FX / F14 | no FX-rate table exists | cross-currency amount equality is undefined | match only with structured FX event plus balanced FX journal; otherwise insufficient |
| PO amendments/receipts / F02-F03 | no amendment, receipt, or cumulative billing table | legitimate partials may resemble mismatch | line-price rule limits F02; F03 flags exact quantity inequality and records limitation |
| Vendor aliases/hierarchy / F01/F04 | no alias or corporate-family table | semantic identity cannot be resolved | vendor IDs remain authoritative; no name-based merge |
| Bank-payment FK / F12-F15 | no physical FK exists | references can be missing or wrong | use normalized payment reference; F15 uses reciprocal economic matching |
| Payment status timing | status update timestamp is absent | state availability cannot be reconstructed from business dates | treat delivered status as available to every method; use cutoff only for explicit aging logic and record this limitation |

## 11. Potential rule collisions and precedence

The scored output is single-label. All raw rule hits are retained, then the following frozen precedence is applied from highest to lowest:

`F15 > F11 > F08 > F06 > F07 > F05 > F01 > F04 > F03 > F02 > F10 > F09 > F14 > F12 > F13`.

This order favors a more specific causal/relational mechanism over its surface symptom. It is not changed from test results.

| Involved rules | Why both can trigger | Multiple scored labels? | Frozen resolution |
|---|---|---|---|
| F03, F02 | quantity manipulation can also change unit price | no | F03 precedes F02 when linked quantity differs |
| F15, F14 | swapped references create apparent amount mismatch | no | reciprocal F15 cycle suppresses F14 on the four records |
| F11, F12/F14 | stale vendor data can cause failed or absent/mismatched settlement | no | temporally proven F11 takes precedence |
| F05, F12 | unsupported payment may also lack bank settlement | no | F05's missing payable is the more specific upstream condition |
| F08, downstream payment rules | an unauthorized payment can also fail later | no | F08 wins when its complete policy violation is evidenced, except F15/F11 |
| F06, F01 | duplicate obligation and duplicate disbursement can coexist in real data | no | F06 wins for actual overpayment; F01 raw hit is retained |
| F10, F09 | one journal may have wrong period and wrong amount/account | no | period-specific F10 precedes general GL mismatch |
| F13, accounted fee exception | bank fee lacks ERP payment by design | no anomaly collision | balanced, typed fee is MATCH and F13 is suppressed |
| F07, F06 | aggregate cannot be simultaneously below and above one invoice total | no | mutually exclusive by arithmetic |
| F12, F13 | one is ERP-without-bank and the other bank-without-ERP | no | mutually exclusive for the same reference under unique matching |

If two unrelated genuine anomalies survive precedence, the baseline returns the higher rule and records the second in the unscored trace. This is a known consequence of the benchmark's single-primary-label contract.

## 12. Leakage audit

| Candidate input | Decision | Rationale / restriction |
|---|---|---|
| `rca_ground_truth.jsonl`, `failure_manifest.csv` | excluded | direct labels and adjudication |
| expected answers/questions metadata | excluded except routing case/primary ID | direct targets; case ID is output correlation only |
| `mutation_log.jsonl`, clean tables | excluded | before/after injection ground truth |
| `causal_edges.csv` | excluded | exact graph-level ground truth, not operational data |
| dataset quality/failure signatures | excluded | post-generation validation reveals anomalies |
| split name | excluded | may correlate with held-out mechanisms/vendors |
| `invoices.duplicate_reference` | excluded from classification | operationally ambiguous and used by legitimate credit memo linkage; unnecessary for F01 |
| invoice/payment/bank statuses | allowed | delivered operational states, not human RCA labels; no update-time inference is attempted |
| `settlement_status` | allowed | source-system state central to reconciliation; lack of a status-update timestamp is a frozen limitation |
| `vendor_change_log.change_reason` | excluded from classification | narrative may overstate cause; structured field/time/values suffice |
| `audit_log.comments`, `old_value`, `new_value` | excluded from classification | free text/change narrative could directly disclose injected cause |
| anomaly-specific audit event types | excluded | events such as workflow override/transmission failure are not needed for class detection and risk cause leakage |
| `FX_CONVERSION_APPLIED` audit event type | allowed only in F14 negative branch | structured operational evidence establishes a legitimate FX exception; cannot trigger an anomaly label |
| GL `memo` | excluded from classification | narrative description is unnecessary and can reveal semantics |
| GL `transaction_type`, source ID, accounts | allowed | structured accounting linkage available in an ordinary ledger |
| bank `transaction_type`, direction, status | allowed | ordinary statement/transaction attributes needed to distinguish fees/reversals |
| `source_system` | excluded from predicates | useful for provenance but not needed to decide any rule |
| employee role/limit/status | allowed | contemporaneous structured authorization attributes |

The implementation must produce a feature/column access audit proving that no excluded artifact or field was read during inference.

## 13. Known limitations frozen before evaluation

- F01 cannot reliably identify semantic duplicates with unrelated references or vendor aliases.
- F02/F03 cannot reason about receipts, cumulative partial billing, PO amendments, discounts, or one invoice against multiple POs because the schema lacks those relationships.
- F04 treats IDs as authoritative and cannot model parent/subsidiary or merger equivalence.
- F05 can flag legitimate advances/prepayments because there is no payment-purpose field.
- F06/F07 cannot recognize contractual write-offs or on-account balances outside allocations.
- F08 cannot apply historical policy versions or undocumented delegation rules.
- F09 assumes the benchmark chart-of-account roles and same-day payment posting.
- F10 fixes payment date as the economic period under the benchmark accounting policy.
- F11 assumes vendor change history is complete and one bank token is effective at a time.
- F12 uses weekend-only business days and requires payment-level bank references.
- F13 cannot classify unknown bank transaction types deterministically.
- F14 cannot calculate FX from market rates and requires structured fee/FX linkage.
- F15 handles only observable reciprocal two-cycles with unique, distinct-amount economic candidates.
- Single-label precedence can hide a second genuine anomaly, though the raw trace preserves it.
- All behavior is specific to the synthetic v1 schema and must not be presented as a universal enterprise reconciliation policy.

## 14. Final freeze checklist

- [x] 15 failure definitions
- [x] rule IDs
- [x] required tables
- [x] join paths
- [x] hop counts
- [x] complexity tiers
- [x] deterministic conditions
- [x] normalization rules
- [x] thresholds
- [x] validation-tuned parameters and selection protocol
- [x] NULL behavior
- [x] missing-evidence behavior
- [x] edge-case behavior
- [x] rule precedence
- [x] evidence requirements
- [x] prediction output schema
- [x] leakage audit
- [x] known limitations

Implementation is authorized only if it reproduces this document verbatim in its run manifest, records the validation-selected F01 pair before test inference, and passes a column-access leakage test. Any semantic change after test observation requires declaring the run exploratory and creating a new held-out test set.

**READY TO FREEZE**
