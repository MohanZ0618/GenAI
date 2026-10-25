# ML Feature Leakage Audit — Version 1.0

Registry SHA-256: `b515b9f81e8284281dc7bddfcc2b32e9655d09fce71d8aed998b8687f7840d3d`

Audit questions: Q1 inference-time source availability; Q2 no future information; Q3 no target/proxy; Q4 not post-reconciliation; Q5 no validation/test statistics; Q6 no Rules/SQL output; Q7 known at decision time.

All 147 frozen features are PASS. There are no unresolved REVIEW or FAIL entries. IDs/tokens used transiently for joins/equality never enter the matrix. The only audit-log feature is the legitimate `FX_CONVERSION_APPLIED` count through cutoff.

| Feature ID | Name | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 | Result |
|---|---|---|---|---|---|---|---|---|---|
| CAT001 | primary_entity_type | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT002 | invoice_currency | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT003 | invoice_status | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT004 | invoice_payment_terms | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT005 | invoice_department | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT006 | invoice_gl_account | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT007 | po_currency | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT008 | po_status | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT009 | po_department | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT010 | po_gl_account | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT011 | vendor_type | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT012 | vendor_country | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT013 | vendor_currency | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT014 | vendor_payment_terms | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT015 | vendor_default_payment_method | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT016 | vendor_status | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT017 | payment_method | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT018 | payment_currency | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT019 | payment_status | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT020 | settlement_status | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT021 | bank_transaction_type | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT022 | bank_currency | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT023 | bank_direction | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT024 | bank_status | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT025 | final_approval_role | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT026 | final_approval_action | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| CAT027 | gl_primary_transaction_type | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM001 | invoice_total | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM002 | invoice_subtotal | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM003 | invoice_tax | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM004 | invoice_shipping | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM005 | invoice_age_calendar_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM006 | invoice_due_lag_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM007 | invoice_received_delay_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM008 | invoice_line_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM009 | invoice_line_quantity_sum | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM010 | invoice_line_amount_sum | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM011 | invoice_line_unit_price_mean | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM012 | po_total | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM013 | po_subtotal | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM014 | po_tax | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM015 | po_shipping | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM016 | po_age_calendar_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM017 | po_line_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM018 | po_line_quantity_sum | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM019 | po_line_amount_sum | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM020 | payment_amount | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM021 | payment_age_calendar_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM022 | allocation_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM023 | allocated_amount_sum | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM024 | linked_invoice_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM025 | linked_invoice_total_sum | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM026 | linked_payment_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM027 | bank_amount | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM028 | bank_age_calendar_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM029 | bank_reference_match_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM030 | gl_line_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM031 | gl_journal_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM032 | gl_total_debit | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM033 | gl_total_credit | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM034 | gl_ap_debit | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM035 | gl_cash_credit | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM036 | approval_event_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM037 | approval_effective_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM038 | approval_max_level | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM039 | approval_distinct_role_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM040 | approval_missing_employee_actor_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM041 | vendor_change_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM042 | vendor_change_before_payment_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM043 | vendor_name_length | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM044 | vendor_name_token_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM045 | duplicate_same_vendor_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM046 | duplicate_exact_reference_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM047 | duplicate_best_reference_similarity | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM048 | duplicate_min_date_gap_days | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM049 | duplicate_min_amount_gap | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM050 | bank_fee_debit_total | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM051 | fx_journal_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM052 | fx_event_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM053 | payment_reference_use_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| NUM054 | bank_economic_candidate_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF001 | invoice_po_total_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF002 | invoice_po_total_rel_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF003 | invoice_po_tax_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF004 | invoice_po_shipping_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF005 | invoice_po_line_amount_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF006 | invoice_po_line_quantity_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF007 | payment_allocated_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF008 | payment_allocated_rel_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF009 | invoice_paid_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF010 | invoice_paid_rel_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF011 | payment_bank_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF012 | payment_bank_rel_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF013 | gl_balance_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF014 | payment_ap_debit_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF015 | payment_cash_credit_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF016 | bank_fee_adjusted_abs_diff | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF017 | days_po_to_invoice | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF018 | days_invoice_to_payment | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF019 | days_payment_to_bank | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| DIF020 | minutes_final_approval_to_payment | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT001 | invoice_has_po | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT002 | po_found | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT003 | invoice_po_vendor_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT004 | invoice_po_currency_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT005 | all_invoice_lines_po_linked | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT006 | any_invoice_line_missing_po_target | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT007 | invoice_po_quantities_all_equal | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT008 | payment_has_allocations | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT009 | allocations_all_invoices_found | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT010 | payment_invoice_currency_all_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT011 | payment_invoice_vendor_all_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT012 | payment_reference_present | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT013 | payment_reference_unique | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT014 | bank_reference_match_found | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT015 | bank_reference_match_unique | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT016 | payment_bank_currency_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT017 | payment_bank_token_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT018 | gl_source_found | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT019 | gl_currency_all_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT020 | gl_period_all_match_payment_month | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT021 | vendor_current_token_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT022 | vendor_bank_history_present | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT023 | final_approver_employee_found | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT024 | final_approver_active | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT025 | final_approver_role_match | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MAT026 | invoice_reference_present | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS001 | missing_invoice | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS002 | missing_po | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS003 | missing_vendor | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS004 | missing_payment | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS005 | missing_bank_transaction | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS006 | missing_gl | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS007 | missing_approval | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS008 | missing_employee | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS009 | missing_reference | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS010 | missing_currency | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS011 | missing_amount | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS012 | missing_invoice_lines | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS013 | missing_po_lines | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS014 | missing_allocations | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| MIS015 | missing_vendor_change_history | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| REL001 | scope_invoice_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| REL002 | scope_payment_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| REL003 | scope_bank_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| REL004 | scope_distinct_invoice_vendor_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| REL005 | scope_distinct_payment_vendor_count | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

## Forbidden-feature registry

- case_id as a model feature
- failure_type/ground-truth anomaly label
- difficulty
- reasoning_hops label
- root_cause_category
- split name
- injected_timestamp
- expected answers
- evidence annotations
- causal_edges
- mutation log
- clean pre-mutation tables
- dataset quality/failure signatures
- Rules/SQL predictions, status, rule IDs, traces, or evidence
- LLM/RAG/GraphRAG outputs
- invoices.duplicate_reference
- vendor_change_log.change_reason
- approval_events.comments
- gl_entries.memo
- audit_log fields other than FX_CONVERSION_APPLIED type/count through cutoff
- source_system
- raw case/transaction/vendor/employee IDs as categorical values
- future/test-derived statistics

## Resolution

No feature requires REVIEW. The feature pipeline must assert exact registry equality and fail if any forbidden artifact or field is requested.

**LEAKAGE AUDIT: PASS**
