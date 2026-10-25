# Direct LLM Case-Packet Leakage Audit — Version 1.0

## Audit conclusion

The frozen packet schema contains only operational source fields, stable derived record IDs, routing metadata, and the decision cutoff. No target, adjudication, annotated-evidence, Rules/SQL, or classical-ML field is included. The authoritative `case_entity_records.jsonl` files are explicitly prohibited because their record selection was generated from ground-truth evidence annotations.

**Schema decision: PASS. No REVIEW or FAIL field is permitted in a packet.**

## Decision key

- Inference-time: field is present in the delivered operational snapshot or fixed harness route.
- Pre-reconciliation: field is an operational observation available to a reconciliation analyst under the delivered-snapshot protocol. Empty values remain empty.
- Target/evidence/Rules/ML-derived: `No` means the field is not produced from that category.
- Safe: `PASS` means the field may be exposed under the frozen structural scope. Operational values can be decisive without becoming label leakage.

Every comma-separated source field below receives the same explicit decisions shown in its row; no unlisted table field is serialized.

| Source table | Source field(s), individually covered | Inference-time? | Pre-reconciliation? | Target-derived? | Evidence-annotation-derived? | Rules-derived? | ML-derived? | Safe |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `vendors` | `vendor_id`, `vendor_name`, `vendor_type`, `tax_id_hash`, `country`, `currency`, `payment_terms`, `default_payment_method`, `bank_account_token`, `bank_routing_token`, `vendor_status`, `created_at`, `updated_at`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `vendor_change_log` | `change_id`, `vendor_id`, `field_changed`, `old_value`, `new_value`, `changed_at`, `changed_by`, `change_reason`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `purchase_orders` | `po_id`, `vendor_id`, `po_date`, `currency`, `subtotal`, `tax`, `shipping`, `po_total`, `department`, `cost_center`, `gl_account`, `status`, `expected_delivery_date`, `created_by`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `po_lines` | `po_id`, `po_line_id`, `item_id`, `description`, `quantity`, `unit_price`, `line_amount`, `gl_account`, `department`, `cost_center`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `invoices` | `invoice_id`, `vendor_id`, `po_id`, `invoice_number`, `invoice_date`, `received_date`, `due_date`, `currency`, `subtotal`, `tax`, `shipping`, `invoice_total`, `payment_terms`, `status`, `duplicate_reference`, `created_at`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `invoice_lines` | `invoice_id`, `invoice_line_id`, `po_line_id`, `item_id`, `quantity`, `unit_price`, `line_amount`, `gl_account`, `department`, `cost_center`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `approval_events` | `approval_event_id`, `invoice_id`, `approval_level`, `approver_id`, `approver_role`, `action`, `event_timestamp`, `previous_status`, `new_status`, `comments`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `payments` | `payment_id`, `vendor_id`, `payment_date`, `payment_method`, `payment_currency`, `payment_amount`, `bank_account_id`, `payment_status`, `settlement_status`, `reference_number`, `created_at`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `payment_allocations` | `payment_id`, `invoice_id`, `allocated_amount`, `allocation_date`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `gl_entries` | `journal_id`, `journal_line_id`, `transaction_type`, `source_transaction_id`, `posting_date`, `accounting_period`, `gl_account`, `debit`, `credit`, `currency`, `department`, `cost_center`, `memo`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `bank_transactions` | `bank_transaction_id`, `bank_account_id`, `transaction_date`, `posted_date`, `transaction_type`, `amount`, `currency`, `direction`, `bank_reference`, `counterparty_token`, `payment_reference`, `status`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `bank_statements` | `bank_statement_id`, `bank_account_id`, `statement_date`, `opening_balance`, `closing_balance`, `total_debits`, `total_credits`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `employees` | `employee_id`, `role`, `department`, `approval_limit`, `active_status`, `source_system` | Yes | Yes | No | No | No | No | PASS |
| `audit_log` | `event_id`, `entity_type`, `entity_id`, `event_type`, `timestamp`, `actor_id`, `field`, `old_value`, `new_value`, `source_system` | Yes, through cutoff | Yes | No | No | No | No | PASS |

## Derived packet and routing fields

| Source | Field | Inference-time? | Pre-reconciliation? | Target-derived? | Evidence-annotation-derived? | Rules-derived? | ML-derived? | Safe |
|---|---|---:|---:|---:|---:|---:|---:|---|
| deterministic serializer | `record_id` (`table:primary-key`) | Yes | Yes | No | No | No | No | PASS |
| packet protocol | `packet_version` | Yes | Not a financial fact | No | No | No | No | PASS |
| harness route | `case_id` | Yes | Not evidence | No | No | No | No | PASS |
| harness route | `primary_entity_type` | Yes | Yes | No | No | No | No | PASS |
| harness route | `primary_entity_id` | Yes | Yes | No | No | No | No | PASS |
| frozen experiment configuration | `decision_as_of_date` | Yes | Yes | No | No | No | No | PASS |

## Fields that resemble explanations

`description`, `comments`, `memo`, `change_reason`, `event_type`, `field`, `old_value`, and `new_value` are genuine operational text, not benchmark adjudication. They are retained because Phase 4 supplies complete legitimate source context. They remain untrusted data under the prompt-injection safeguard. No post-hoc human RCA field exists in the 14-table schema.

`invoices.duplicate_reference` is an operational nullable cross-reference and is not an anomaly flag. It is retained consistently for every structurally scoped invoice, never used to select a record, and is generally empty in the benchmark. Its name alone is not a benchmark label.

## Forbidden artifact audit

| Artifact/field family | Decision | Reason |
|---|---|---|
| `case_entity_records.jsonl` | FAIL / prohibited | Generator selected tables and records from ground-truth `evidence_required` and `evidence_ids`; oracle context |
| `rca_ground_truth.jsonl`, `failure_manifest.csv` | FAIL / prohibited | direct target, tier/hop, and adjudication metadata |
| expected answers/questions beyond route | FAIL / prohibited | direct answers; route whitelist retains only case/primary identifiers |
| `causal_edges.csv`, `internal/mutation_log.jsonl` | FAIL / prohibited | exact causal and before/after ground truth |
| `raw_clean/*`, dataset quality/failure signatures | FAIL / prohibited | pre-mutation or post-generation knowledge |
| Rules/SQL run artifacts | FAIL / prohibited | prior predictions, status, traces, rules, reasons, evidence, and metrics |
| classical-ML run/features/model artifacts | FAIL / prohibited | learned predictions/probabilities/features and post-test analysis |
| split, difficulty, tier, hop count | FAIL / prohibited | benchmark evaluation metadata, not business fields |

## Executable enforcement

`OperationalSnapshot` opens exactly `data/benchmark/full/<table>.csv` for the 14 registered tables and records every opened path. `CasePacketBuilder` accepts exactly three route keys, recursively scans every packet key against the frozen forbidden-key registry, and serializes only the fields declared in `TABLE_SCHEMAS`. Unit tests reject forbidden route keys, target-like packet keys, oracle artifact access, and nondeterministic output.

**FINAL FIELD-LEVEL DECISION: PASS**
