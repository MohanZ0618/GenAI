# Canonical schemas

The executable schema registry is `src/schema.py`. CSV column order is stable, amounts are serialized as decimal strings, dates use ISO `YYYY-MM-DD`, and timestamps use ISO local datetime strings. Empty optional links are written as empty strings. Every model-visible table has a `source_system` field.

## Table definitions

| Table | Primary key | Canonical columns |
|---|---|---|
| `vendors` | `vendor_id` | vendor_id, vendor_name, vendor_type, tax_id_hash, country, currency, payment_terms, default_payment_method, bank_account_token, bank_routing_token, vendor_status, created_at, updated_at, source_system |
| `vendor_change_log` | `change_id` | change_id, vendor_id, field_changed, old_value, new_value, changed_at, changed_by, change_reason, source_system |
| `purchase_orders` | `po_id` | po_id, vendor_id, po_date, currency, subtotal, tax, shipping, po_total, department, cost_center, gl_account, status, expected_delivery_date, created_by, source_system |
| `po_lines` | `po_line_id` | po_id, po_line_id, item_id, description, quantity, unit_price, line_amount, gl_account, department, cost_center, source_system |
| `invoices` | `invoice_id` | invoice_id, vendor_id, po_id, invoice_number, invoice_date, received_date, due_date, currency, subtotal, tax, shipping, invoice_total, payment_terms, status, duplicate_reference, created_at, source_system |
| `invoice_lines` | `invoice_line_id` | invoice_id, invoice_line_id, po_line_id, item_id, quantity, unit_price, line_amount, gl_account, department, cost_center, source_system |
| `approval_events` | `approval_event_id` | approval_event_id, invoice_id, approval_level, approver_id, approver_role, action, event_timestamp, previous_status, new_status, comments, source_system |
| `payments` | `payment_id` | payment_id, vendor_id, payment_date, payment_method, payment_currency, payment_amount, bank_account_id, payment_status, settlement_status, reference_number, created_at, source_system |
| `payment_allocations` | payment_id + invoice_id + allocation_date | payment_id, invoice_id, allocated_amount, allocation_date, source_system |
| `gl_entries` | `journal_line_id` | journal_id, journal_line_id, transaction_type, source_transaction_id, posting_date, accounting_period, gl_account, debit, credit, currency, department, cost_center, memo, source_system |
| `bank_transactions` | `bank_transaction_id` | bank_transaction_id, bank_account_id, transaction_date, posted_date, transaction_type, amount, currency, direction, bank_reference, counterparty_token, payment_reference, status, source_system |
| `bank_statements` | `bank_statement_id` | bank_statement_id, bank_account_id, statement_date, opening_balance, closing_balance, total_debits, total_credits, source_system |
| `employees` | `employee_id` | employee_id, role, department, approval_limit, active_status, source_system |
| `audit_log` | `event_id` | event_id, entity_type, entity_id, event_type, timestamp, actor_id, field, old_value, new_value, source_system |

## Artifact schemas

`causal_edges.csv` has `source_entity_type`, `source_entity_id`, `relationship`, `target_entity_type`, and `target_entity_id`.

`failure_manifest.csv` has `case_id`, `failure_type`, `difficulty`, `primary_entity_type`, `primary_entity_id`, `affected_systems`, `reasoning_hops`, `injected_timestamp`, `root_cause_category`, and `split`.

`mutation_log.jsonl` has `case_id`, `table`, `record_id`, `field`, `original_value`, `mutated_value`, and `injection_reason`. `field=__record__` denotes an inserted or deleted row.

## Data types and invariants

- IDs, tokens, statuses, accounts, systems, countries, currencies, descriptions, and references: string.
- Amounts and approval limits: fixed-point decimal; no binary floating-point money arithmetic is used.
- Quantity and approval level: integer.
- Date fields: ISO date. Event/created/updated fields: ISO timestamp.
- A GL line has a nonnegative debit and credit; generated business lines use one side. Every `journal_id` balances.
- A bank debit reduces balance and a credit increases balance.
- `payment_allocations` is the authoritative many-to-many bridge between payments and invoices.

## Foreign-key relationships

- PO and invoice line headers must exist.
- A PO-backed invoice references an existing PO; non-PO invoices have an empty `po_id`.
- Nonempty `po_line_id` values on invoice lines reference PO lines.
- Approval events reference invoices.
- Allocations reference both payments and invoices.
- GL source IDs refer to invoices, payments, bank-fee transactions, or other source transactions according to `transaction_type`.
- A bank transaction links to an ERP payment through a cross-system reference, not by copying the ERP payment ID.

