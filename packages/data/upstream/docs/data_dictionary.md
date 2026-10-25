# Data dictionary

## Common conventions

| Term | Meaning |
|---|---|
| `*_id` | Synthetic internal identifier. IDs do not contain failure labels. |
| `*_token` | Non-operational synthetic placeholder, never a real banking identifier. |
| `currency` | ISO-like currency code controlling decimal precision. |
| `source_system` | System that observed or owns the row; cross-system rows are not identical copies. |
| `department` / `cost_center` | Synthetic management-accounting dimensions. |
| `created_at` / `timestamp` | ISO local timestamp used for event ordering, not wall-clock generation time. |

## Vendor and workforce

- `vendor_type`: supplier, services, software, logistics, or professional.
- `tax_id_hash`: truncated SHA-256 of a synthetic seed/vendor string.
- `payment_terms`: DUE_ON_RECEIPT, NET15, NET30, NET45, or NET60.
- `bank_account_token`, `bank_routing_token`: safe placeholders for vendor settlement instructions.
- `vendor_status`: active, on hold, or another generated lifecycle state.
- `field_changed`, `old_value`, `new_value`: reconstruct an effective vendor master transition.
- `changed_by`, `change_reason`: synthetic actor and business explanation for the change.
- `role`, `approval_limit`, `active_status`: workflow authority attributes; no employee names are generated.

## Procurement

- `po_id`, `po_line_id`: PO header and globally unique line identifiers.
- `subtotal`: exact sum of line amounts.
- `tax`, `shipping`: header additions; `po_total = subtotal + tax + shipping`.
- `expected_delivery_date`: planned fulfillment date, not an accounting posting date.
- `created_by`: synthetic requester/employee ID.
- `item_id`, `description`: synthetic goods/service classification and safe description.
- `quantity`, `unit_price`, `line_amount`: `line_amount = quantity × unit_price` at currency precision.
- `gl_account`: intended expense account carried into invoice accounting.

## Invoices and approvals

- `po_id`: existing PO for PO-backed invoices; empty for non-PO invoices.
- `invoice_number`: vendor-facing synthetic reference; not the internal `invoice_id`.
- `invoice_date`, `received_date`, `due_date`: supplier date, AP receipt date, and contractual due date.
- `invoice_total`: line subtotal plus tax and shipping.
- `duplicate_reference`: reserved operational cross-reference; failures are not directly flagged here.
- `po_line_id`: matched PO line or empty on non-PO invoice lines.
- `approval_level`: ordered workflow level; zero denotes submission.
- `action`: submitted, approved, rejected, resubmitted, delegated, or auto_approved.
- `previous_status`, `new_status`: event-sourced workflow transition.
- `approver_role`: role used to evaluate delegated authority.

## Payments and allocations

- `payment_method`: ACH, wire, check, or virtual_card.
- `payment_currency`, `payment_amount`: ERP disbursement currency and gross amount.
- `bank_account_id`: tokenized vendor destination snapshot used by the payment system.
- `payment_status`: operational lifecycle state such as submitted or completed.
- `settlement_status`: pending, settled, or failed cross-system outcome.
- `reference_number`: ERP/payment-processor reference used to match bank observations.
- `allocated_amount`: portion of a payment applied to an invoice. Sum by payment normally equals payment amount; sum by paid invoice normally equals invoice total.
- `allocation_date`: date the AP subledger applied the payment.

## General ledger

- `journal_id`: groups lines in one balanced double-entry journal.
- `journal_line_id`: unique row identifier.
- `transaction_type`: invoice, payment, bank_fee, or another source class.
- `source_transaction_id`: operational source ID; not a failure label.
- `posting_date`, `accounting_period`: ledger date and `YYYY-MM` period.
- `debit`, `credit`: nonnegative monetary sides; sum debit equals sum credit by journal.
- `memo`: synthetic accounting description.

## Bank data

- `bank_account_id`: synthetic company bank account name used for statements.
- `transaction_date`, `posted_date`: initiation/effective date and bank posting date.
- `transaction_type`: ACH debit, wire debit, check clearing, card settlement, bank fee, return, or reversal.
- `direction`: debit reduces the bank balance; credit increases it.
- `bank_reference`: bank-owned synthetic reference.
- `counterparty_token`: tokenized external settlement counterparty.
- `payment_reference`: reference used for ERP/bank record linkage; it is not guaranteed to be correct after injection.
- `status`: bank-side posting or return state.
- `opening_balance`, `closing_balance`, `total_debits`, `total_credits`: statement control totals.

## Audit and benchmark artifacts

- `entity_type`, `entity_id`, `event_type`: audited entity and event.
- `actor_id`: synthetic user or system actor.
- `field`, `old_value`, `new_value`: optional change detail.
- `case_id`: neutral RCA case identifier.
- `failure_type`: one of F01–F15 or `NO_FAILURE`; present only in evaluation artifacts, never operational tables.
- `root_cause_category`: finer causal label such as transmission failure or stale vendor bank version.
- `evidence_required`, `evidence_ids`: tables and identifiers needed for the reference investigation.
- `reasoning_hops`: intended minimum causal-link depth.
- `difficulty`: easy, medium, or hard.
- `split`: train, validation, test, or challenge_test.

