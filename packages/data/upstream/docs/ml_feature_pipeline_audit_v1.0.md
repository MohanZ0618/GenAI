# Classical ML Feature-Pipeline Audit — Version 1.0

## Decision

**PASS**. This audit was completed after deterministic train/validation feature extraction and train-only preprocessing fit, and before any candidate estimator training.

## Frozen provenance

- ML specification SHA-256: `0d220564335a85e6fe3a193e212d68aec2abbf7744a23f267ba4390b428d6897`
- Feature registry SHA-256: `b515b9f81e8284281dc7bddfcc2b32e9655d09fce71d8aed998b8687f7840d3d`
- Registered pre-encoding features: 147
- Transformed columns after train-fit one-hot encoding: 265

## Leakage and fit-scope checks

- Model-visible snapshot access audit: PASS
- Train registry/order exact: True
- Validation registry/order exact: True
- Preprocessing fit scope: train only
- Validation handling: transform only, no refit
- Forbidden feature-name hits: none
- High-cardinality categorical fields (>100 train values): none
- Numeric features with absolute one-vs-rest train correlation >0.95: ['duplicate_exact_reference_count', 'payment_allocated_rel_diff', 'missing_vendor']

Each flagged feature was investigated against its frozen formula and source lineage:

- `duplicate_exact_reference_count`: PASS — an operational same-vendor normalized-reference count computed from invoices without labels; strong separation is consistent with the registered duplicate condition.
- `payment_allocated_rel_diff`: PASS — an operational payment/allocation arithmetic difference computed without labels; strong separation is consistent with missing/invalid allocation structure.
- `missing_vendor`: PASS — entity absence derived from permitted linkage and explicitly registered missingness, not annotation-package absence.

None is derived from benchmark labels, mutation provenance, Rules/SQL outputs, post-reconciliation fields, or future/test statistics. All remain PASS under the already frozen registry.

Strong association is reported for auditability and does not by itself establish leakage. Every feature remains governed by the already frozen source-lineage registry; no feature was added, removed, or revised after this audit.

## Distribution checks

- Constant train features: ['approval_missing_employee_actor_count', 'vendor_name_token_count', 'invoice_po_tax_abs_diff', 'invoice_po_shipping_abs_diff', 'gl_balance_abs_diff', 'missing_po', 'missing_employee', 'missing_reference', 'missing_currency', 'missing_amount', 'missing_invoice_lines', 'missing_po_lines']
- Near-constant train features (>=99% one value): ['approval_missing_employee_actor_count', 'gl_balance_abs_diff', 'missing_po', 'missing_employee', 'missing_reference', 'missing_currency', 'missing_amount', 'missing_invoice_lines', 'missing_po_lines']
- Per-feature missing rates, cardinalities, and correlation flags are saved in `feature_audit.csv` in the immutable run directory.

## Conclusion

No material feature-pipeline leakage or registry mismatch was detected.
