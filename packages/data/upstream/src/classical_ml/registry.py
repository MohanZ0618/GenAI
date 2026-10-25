"""Pre-registered feature and model-search registries for ML baseline v1.0."""

from __future__ import annotations

from dataclasses import asdict, dataclass


RANDOM_SEED = 314159
AS_OF_DATE = "2026-06-30"
NO_FAILURE = "NO_FAILURE"

FAILURE_TYPES = tuple(f"F{number:02d}_{name}" for number, name in (
    (1, "DUPLICATE_INVOICE"),
    (2, "PO_INVOICE_AMOUNT_MISMATCH"),
    (3, "QUANTITY_MISMATCH"),
    (4, "INCORRECT_VENDOR_ASSOCIATION"),
    (5, "PAYMENT_WITHOUT_VALID_INVOICE"),
    (6, "INVOICE_PAID_TWICE"),
    (7, "PARTIAL_PAYMENT_RESIDUAL_BALANCE"),
    (8, "APPROVAL_WORKFLOW_FAILURE"),
    (9, "GL_POSTING_MISMATCH"),
    (10, "WRONG_ACCOUNTING_PERIOD"),
    (11, "VENDOR_MASTER_CHANGE_CONFLICT"),
    (12, "ERP_PAYMENT_MISSING_FROM_BANK"),
    (13, "BANK_TRANSACTION_MISSING_FROM_ERP"),
    (14, "BANK_ERP_AMOUNT_MISMATCH"),
    (15, "INCORRECT_PAYMENT_BANK_MATCH"),
))
CLASSES = FAILURE_TYPES + (NO_FAILURE,)

TIER_BY_CLASS = {failure: (1 if failure.startswith("F01_") else 2 if failure.startswith(("F04_", "F09_", "F10_", "F12_", "F13_")) else 3) for failure in FAILURE_TYPES}
HOP_BY_CLASS = {
    **{failure: 0 for failure in FAILURE_TYPES if failure.startswith("F01_")},
    **{failure: 1 for failure in FAILURE_TYPES if failure.startswith(("F04_", "F09_", "F10_", "F12_", "F13_"))},
    **{failure: 2 for failure in FAILURE_TYPES if failure.startswith(("F02_", "F03_", "F05_", "F06_", "F07_", "F11_", "F14_"))},
    **{failure: 3 for failure in FAILURE_TYPES if failure.startswith("F15_")},
    **{failure: 4 for failure in FAILURE_TYPES if failure.startswith("F08_")},
}


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    name: str
    source_tables: str
    definition: str
    feature_type: str
    missing_handling: str
    temporal_safety: str
    notes: str = ""

    def serializable(self) -> dict[str, str]:
        return asdict(self)


def _f(identifier: str, name: str, sources: str, definition: str, kind: str, missing: str, temporal: str, notes: str = "") -> FeatureDefinition:
    return FeatureDefinition(identifier, name, sources, definition, kind, missing, temporal, notes)


CAT_FEATURES = (
    _f("CAT001", "primary_entity_type", "routing metadata", "Whitelisted primary entity type.", "categorical", "__MISSING__", "Available at routing time"),
    _f("CAT002", "invoice_currency", "invoices", "Currency of representative scoped invoice.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT003", "invoice_status", "invoices", "Normalized operational invoice status.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT004", "invoice_payment_terms", "invoices", "Normalized invoice payment terms.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT005", "invoice_department", "invoice_lines", "Mode department across representative invoice lines, lexical tie-break.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT006", "invoice_gl_account", "invoice_lines", "Mode GL account across representative invoice lines, lexical tie-break.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT007", "po_currency", "purchase_orders", "Currency of invoice-linked PO.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT008", "po_status", "purchase_orders", "Normalized status of invoice-linked PO.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT009", "po_department", "purchase_orders", "Normalized department of invoice-linked PO.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT010", "po_gl_account", "purchase_orders", "Normalized header GL account of invoice-linked PO.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT011", "vendor_type", "vendors", "Normalized vendor type for representative scoped vendor.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT012", "vendor_country", "vendors", "Normalized vendor country.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT013", "vendor_currency", "vendors", "Normalized vendor master currency.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT014", "vendor_payment_terms", "vendors", "Normalized vendor master payment terms.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT015", "vendor_default_payment_method", "vendors", "Normalized vendor default payment method.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT016", "vendor_status", "vendors", "Normalized operational vendor status.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT017", "payment_method", "payments", "Normalized representative payment method.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT018", "payment_currency", "payments", "Representative payment currency.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT019", "payment_status", "payments", "Normalized representative payment status.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT020", "settlement_status", "payments", "Normalized representative settlement status.", "categorical", "__MISSING__", "Delivered snapshot"),
    _f("CAT021", "bank_transaction_type", "bank_transactions", "Normalized representative bank transaction type.", "categorical", "__MISSING__", "Rows posted through AS_OF_DATE only"),
    _f("CAT022", "bank_currency", "bank_transactions", "Representative bank transaction currency.", "categorical", "__MISSING__", "Rows posted through AS_OF_DATE only"),
    _f("CAT023", "bank_direction", "bank_transactions", "Normalized representative bank direction.", "categorical", "__MISSING__", "Rows posted through AS_OF_DATE only"),
    _f("CAT024", "bank_status", "bank_transactions", "Normalized representative bank status.", "categorical", "__MISSING__", "Rows posted through AS_OF_DATE only"),
    _f("CAT025", "final_approval_role", "approval_events", "Role on latest effective approval event at/before payment creation.", "categorical", "__MISSING__", "Event timestamp <= payment creation"),
    _f("CAT026", "final_approval_action", "approval_events", "Action on latest effective approval event at/before payment creation.", "categorical", "__MISSING__", "Event timestamp <= payment creation"),
    _f("CAT027", "gl_primary_transaction_type", "gl_entries", "Mode transaction type among source-linked GL rows.", "categorical", "__MISSING__", "Delivered snapshot"),
)


NUMERIC_FEATURE_SPECS = (
    ("NUM001", "invoice_total", "invoices", "Representative invoice total"),
    ("NUM002", "invoice_subtotal", "invoices", "Representative invoice subtotal"),
    ("NUM003", "invoice_tax", "invoices", "Representative invoice tax"),
    ("NUM004", "invoice_shipping", "invoices", "Representative invoice shipping"),
    ("NUM005", "invoice_age_calendar_days", "invoices", "AS_OF_DATE minus invoice_date in calendar days"),
    ("NUM006", "invoice_due_lag_days", "invoices", "due_date minus invoice_date in calendar days"),
    ("NUM007", "invoice_received_delay_days", "invoices", "received_date minus invoice_date in calendar days"),
    ("NUM008", "invoice_line_count", "invoice_lines", "Count of representative invoice lines"),
    ("NUM009", "invoice_line_quantity_sum", "invoice_lines", "Sum of parseable invoice-line quantities"),
    ("NUM010", "invoice_line_amount_sum", "invoice_lines", "Sum of parseable invoice-line amounts"),
    ("NUM011", "invoice_line_unit_price_mean", "invoice_lines", "Mean parseable invoice-line unit price"),
    ("NUM012", "po_total", "purchase_orders", "Linked PO total"),
    ("NUM013", "po_subtotal", "purchase_orders", "Linked PO subtotal"),
    ("NUM014", "po_tax", "purchase_orders", "Linked PO tax"),
    ("NUM015", "po_shipping", "purchase_orders", "Linked PO shipping"),
    ("NUM016", "po_age_calendar_days", "purchase_orders", "AS_OF_DATE minus po_date in calendar days"),
    ("NUM017", "po_line_count", "po_lines", "Count of linked PO lines"),
    ("NUM018", "po_line_quantity_sum", "po_lines", "Sum of parseable PO-line quantities"),
    ("NUM019", "po_line_amount_sum", "po_lines", "Sum of parseable PO-line amounts"),
    ("NUM020", "payment_amount", "payments", "Representative payment amount"),
    ("NUM021", "payment_age_calendar_days", "payments", "AS_OF_DATE minus payment_date in calendar days"),
    ("NUM022", "allocation_count", "payment_allocations", "Count of allocations in scoped payment/invoice relationships"),
    ("NUM023", "allocated_amount_sum", "payment_allocations", "Sum of parseable scoped allocations"),
    ("NUM024", "linked_invoice_count", "payment_allocations;invoices", "Distinct existing linked invoices"),
    ("NUM025", "linked_invoice_total_sum", "payment_allocations;invoices", "Sum of totals for distinct linked invoices"),
    ("NUM026", "linked_payment_count", "payment_allocations;payments", "Distinct existing linked payments"),
    ("NUM027", "bank_amount", "bank_transactions", "Representative posted bank transaction amount"),
    ("NUM028", "bank_age_calendar_days", "bank_transactions", "AS_OF_DATE minus bank posted_date in calendar days"),
    ("NUM029", "bank_reference_match_count", "payments;bank_transactions", "Bank rows sharing normalized representative payment reference"),
    ("NUM030", "gl_line_count", "payments;gl_entries", "Count of source-linked GL lines"),
    ("NUM031", "gl_journal_count", "payments;gl_entries", "Distinct source-linked journal count"),
    ("NUM032", "gl_total_debit", "gl_entries", "Sum debit across source-linked GL rows"),
    ("NUM033", "gl_total_credit", "gl_entries", "Sum credit across source-linked GL rows"),
    ("NUM034", "gl_ap_debit", "gl_entries", "Debit on exact AP control account across source-linked rows"),
    ("NUM035", "gl_cash_credit", "gl_entries", "Credit on exact cash control account across source-linked rows"),
    ("NUM036", "approval_event_count", "approval_events", "Count of scoped approval events"),
    ("NUM037", "approval_effective_count", "approval_events", "APPROVED/AUTO_APPROVED events at/before payment creation"),
    ("NUM038", "approval_max_level", "approval_events", "Maximum parseable effective approval level"),
    ("NUM039", "approval_distinct_role_count", "approval_events", "Distinct normalized roles on effective approval events"),
    ("NUM040", "approval_missing_employee_actor_count", "approval_events;employees", "Human effective approval actors without employee row"),
    ("NUM041", "vendor_change_count", "vendor_change_log", "Bank-account-token change count for scoped vendor"),
    ("NUM042", "vendor_change_before_payment_count", "vendor_change_log;payments", "Bank-token changes at/before payment creation"),
    ("NUM043", "vendor_name_length", "vendors", "Unicode character length after NFKC/whitespace normalization"),
    ("NUM044", "vendor_name_token_count", "vendors", "Whitespace token count after NFKC normalization"),
    ("NUM045", "duplicate_same_vendor_count", "invoices", "Other active positive invoices with same vendor"),
    ("NUM046", "duplicate_exact_reference_count", "invoices", "Same-vendor invoices with equal normalized reference"),
    ("NUM047", "duplicate_best_reference_similarity", "invoices", "Maximum normalized Levenshtein similarity to same-vendor invoice"),
    ("NUM048", "duplicate_min_date_gap_days", "invoices", "Minimum absolute invoice-date gap to same-vendor invoice"),
    ("NUM049", "duplicate_min_amount_gap", "invoices", "Minimum absolute total gap to same-vendor same-currency invoice"),
    ("NUM050", "bank_fee_debit_total", "bank_transactions;gl_entries", "Debit total of source-linked BANK_FEE journals"),
    ("NUM051", "fx_journal_count", "bank_transactions;gl_entries", "Distinct source-linked FX_SETTLEMENT journals"),
    ("NUM052", "fx_event_count", "bank_transactions;audit_log", "FX_CONVERSION_APPLIED events through AS_OF_DATE"),
    ("NUM053", "payment_reference_use_count", "payments", "Payments sharing normalized representative reference"),
    ("NUM054", "bank_economic_candidate_count", "payments;bank_transactions", "Posted bank rows with same currency/token, amount within quantum, and date within 7 days"),
)
NUM_FEATURES = tuple(_f(identifier, name, sources, definition, "numeric", "Training median; explicit entity missingness retained", "AS_OF_DATE/delivered snapshot; no historical aggregate", "Decimal converted to float only after deterministic arithmetic") for identifier, name, sources, definition in NUMERIC_FEATURE_SPECS)


DIFF_FEATURE_SPECS = (
    ("DIF001", "invoice_po_total_abs_diff", "invoices;purchase_orders", "abs(invoice_total-po_total)"),
    ("DIF002", "invoice_po_total_rel_diff", "invoices;purchase_orders", "abs(invoice_total-po_total)/max(abs(po_total),0.01)"),
    ("DIF003", "invoice_po_tax_abs_diff", "invoices;purchase_orders", "abs(invoice_tax-po_tax)"),
    ("DIF004", "invoice_po_shipping_abs_diff", "invoices;purchase_orders", "abs(invoice_shipping-po_shipping)"),
    ("DIF005", "invoice_po_line_amount_abs_diff", "invoice_lines;po_lines", "abs(sum(invoice lines)-sum(PO lines))"),
    ("DIF006", "invoice_po_line_quantity_abs_diff", "invoice_lines;po_lines", "abs(sum(invoice quantities)-sum(PO quantities))"),
    ("DIF007", "payment_allocated_abs_diff", "payments;payment_allocations", "abs(payment_amount-sum(allocations))"),
    ("DIF008", "payment_allocated_rel_diff", "payments;payment_allocations", "absolute payment/allocation difference divided by max(abs(payment_amount),0.01)"),
    ("DIF009", "invoice_paid_abs_diff", "invoices;payment_allocations;payments", "abs(invoice_total-effective allocated sum)"),
    ("DIF010", "invoice_paid_rel_diff", "invoices;payment_allocations;payments", "absolute invoice/effective-paid difference divided by max(abs(invoice_total),0.01)"),
    ("DIF011", "payment_bank_abs_diff", "payments;bank_transactions", "abs(payment_amount-representative bank amount)"),
    ("DIF012", "payment_bank_rel_diff", "payments;bank_transactions", "absolute payment/bank difference divided by max(abs(payment_amount),0.01)"),
    ("DIF013", "gl_balance_abs_diff", "gl_entries", "abs(total debit-total credit)"),
    ("DIF014", "payment_ap_debit_abs_diff", "payments;gl_entries", "abs(payment_amount-AP debit)"),
    ("DIF015", "payment_cash_credit_abs_diff", "payments;gl_entries", "abs(payment_amount-cash credit)"),
    ("DIF016", "bank_fee_adjusted_abs_diff", "payments;bank_transactions;gl_entries", "abs(abs(payment-bank amount)-linked fee debit)"),
    ("DIF017", "days_po_to_invoice", "purchase_orders;invoices", "invoice_date-po_date in calendar days"),
    ("DIF018", "days_invoice_to_payment", "invoices;payments", "payment_date-invoice_date in calendar days"),
    ("DIF019", "days_payment_to_bank", "payments;bank_transactions", "bank transaction_date-payment_date in calendar days"),
    ("DIF020", "minutes_final_approval_to_payment", "approval_events;payments", "payment created_at-final effective approval timestamp in minutes"),
)
DIFF_FEATURES = tuple(_f(identifier, name, sources, definition, "numeric", "Training median plus missingness features", "Only delivered/as-of rows; approval event <= payment creation", "Relative denominator floor is 0.01") for identifier, name, sources, definition in DIFF_FEATURE_SPECS)


MATCH_FEATURE_SPECS = (
    ("MAT001", "invoice_has_po", "invoices", "1 when po_id is nonempty"),
    ("MAT002", "po_found", "invoices;purchase_orders", "1 when linked PO exists"),
    ("MAT003", "invoice_po_vendor_match", "invoices;purchase_orders", "Trimmed case-sensitive vendor IDs equal"),
    ("MAT004", "invoice_po_currency_match", "invoices;purchase_orders", "Normalized currencies equal"),
    ("MAT005", "all_invoice_lines_po_linked", "invoice_lines;po_lines", "All nonempty invoice-line PO references resolve"),
    ("MAT006", "any_invoice_line_missing_po_target", "invoice_lines;po_lines", "Any nonempty invoice-line PO reference is unresolved"),
    ("MAT007", "invoice_po_quantities_all_equal", "invoice_lines;po_lines", "All resolved line quantities are exactly equal integers"),
    ("MAT008", "payment_has_allocations", "payments;payment_allocations", "At least one allocation exists"),
    ("MAT009", "allocations_all_invoices_found", "payment_allocations;invoices", "Every scoped allocation references an existing invoice"),
    ("MAT010", "payment_invoice_currency_all_match", "payments;invoices", "All scoped payment/invoice currencies equal"),
    ("MAT011", "payment_invoice_vendor_all_match", "payments;invoices", "All scoped payment/invoice vendor IDs equal"),
    ("MAT012", "payment_reference_present", "payments", "Normalized payment reference is nonempty"),
    ("MAT013", "payment_reference_unique", "payments", "Normalized representative payment reference occurs once"),
    ("MAT014", "bank_reference_match_found", "payments;bank_transactions", "At least one bank row has normalized payment reference"),
    ("MAT015", "bank_reference_match_unique", "payments;bank_transactions", "Exactly one bank row has normalized payment reference"),
    ("MAT016", "payment_bank_currency_match", "payments;bank_transactions", "Representative payment/bank currencies equal"),
    ("MAT017", "payment_bank_token_match", "payments;bank_transactions", "Payment destination token equals bank counterparty token"),
    ("MAT018", "gl_source_found", "payments;gl_entries", "At least one source-linked GL row exists"),
    ("MAT019", "gl_currency_all_match", "payments;gl_entries", "All source-linked GL currencies equal payment currency"),
    ("MAT020", "gl_period_all_match_payment_month", "payments;gl_entries", "All source-linked GL periods/posting months equal payment month"),
    ("MAT021", "vendor_current_token_match", "payments;vendors", "Payment destination token equals current vendor token"),
    ("MAT022", "vendor_bank_history_present", "vendor_change_log", "At least one bank-account-token history row exists"),
    ("MAT023", "final_approver_employee_found", "approval_events;employees", "Latest effective human approver has employee row; auto is missing"),
    ("MAT024", "final_approver_active", "approval_events;employees", "Latest effective human employee is active"),
    ("MAT025", "final_approver_role_match", "approval_events;employees", "Latest event role equals employee role"),
    ("MAT026", "invoice_reference_present", "invoices", "Normalized invoice number is nonempty"),
)
MATCH_FEATURES = tuple(_f(identifier, name, sources, definition, "binary", "-1 unknown, 0 false, 1 true", "Delivered/as-of evidence only", "IDs/tokens are used only for equality, never retained") for identifier, name, sources, definition in MATCH_FEATURE_SPECS)


MISSING_FEATURE_SPECS = (
    ("MIS001", "missing_invoice", "invoices", "No representative scoped invoice"),
    ("MIS002", "missing_po", "purchase_orders", "Invoice declares PO but target is absent"),
    ("MIS003", "missing_vendor", "vendors", "Representative scoped vendor row absent"),
    ("MIS004", "missing_payment", "payments", "No representative scoped payment"),
    ("MIS005", "missing_bank_transaction", "bank_transactions", "No representative as-of bank row"),
    ("MIS006", "missing_gl", "gl_entries", "No source-linked GL row"),
    ("MIS007", "missing_approval", "approval_events", "No scoped approval event"),
    ("MIS008", "missing_employee", "employees", "A relied-upon human approval actor has no employee row"),
    ("MIS009", "missing_reference", "invoices;payments;bank_transactions", "Representative invoice/payment reference absent"),
    ("MIS010", "missing_currency", "invoices;payments;bank_transactions", "Representative economic currency absent"),
    ("MIS011", "missing_amount", "invoices;payments;bank_transactions", "Representative economic amount absent/unparseable"),
    ("MIS012", "missing_invoice_lines", "invoice_lines", "Representative invoice has zero lines"),
    ("MIS013", "missing_po_lines", "po_lines", "Declared/found PO has zero lines"),
    ("MIS014", "missing_allocations", "payment_allocations", "Representative payment/invoice scope has zero allocations"),
    ("MIS015", "missing_vendor_change_history", "vendor_change_log", "Scoped vendor has zero bank-token history rows"),
)
MISSING_FEATURES = tuple(_f(identifier, name, sources, definition, "binary", "Always observed 0/1", "Missingness derives only from model-visible snapshot", "No annotation-package missingness is used") for identifier, name, sources, definition in MISSING_FEATURE_SPECS)


REL_FEATURES = (
    _f("REL001", "scope_invoice_count", "invoices;payment_allocations", "Distinct invoices reachable from primary via permitted direct relationships.", "numeric", "0", "Delivered snapshot"),
    _f("REL002", "scope_payment_count", "payments;payment_allocations", "Distinct payments reachable from primary via permitted direct relationships.", "numeric", "0", "Delivered snapshot"),
    _f("REL003", "scope_bank_count", "payments;bank_transactions", "Distinct as-of bank rows reachable by normalized reference.", "numeric", "0", "Bank posted_date <= AS_OF_DATE"),
    _f("REL004", "scope_distinct_invoice_vendor_count", "invoices", "Distinct nonmissing vendor IDs among scoped invoices.", "numeric", "0", "Delivered snapshot", "Raw IDs are discarded"),
    _f("REL005", "scope_distinct_payment_vendor_count", "payments", "Distinct nonmissing vendor IDs among scoped payments.", "numeric", "0", "Delivered snapshot", "Raw IDs are discarded"),
)

FEATURES = CAT_FEATURES + NUM_FEATURES + DIFF_FEATURES + MATCH_FEATURES + MISSING_FEATURES + REL_FEATURES
CATEGORICAL_FEATURE_NAMES = tuple(feature.name for feature in CAT_FEATURES)
NUMERIC_FEATURE_NAMES = tuple(feature.name for feature in FEATURES if feature.feature_type != "categorical")
FEATURE_BY_NAME = {feature.name: feature for feature in FEATURES}


FORBIDDEN_FEATURE_REGISTRY = (
    "case_id as a model feature", "failure_type/ground-truth anomaly label", "difficulty", "reasoning_hops label",
    "root_cause_category", "split name", "injected_timestamp", "expected answers", "evidence annotations",
    "causal_edges", "mutation log", "clean pre-mutation tables", "dataset quality/failure signatures",
    "Rules/SQL predictions, status, rule IDs, traces, or evidence", "LLM/RAG/GraphRAG outputs",
    "invoices.duplicate_reference", "vendor_change_log.change_reason", "approval_events.comments",
    "gl_entries.memo", "audit_log fields other than FX_CONVERSION_APPLIED type/count through cutoff",
    "source_system", "raw case/transaction/vendor/employee IDs as categorical values", "future/test-derived statistics",
)


MODEL_SEARCH_SPACE = {
    "logistic_regression": {
        "fixed": {"penalty": "l2", "solver": "lbfgs", "max_iter": 2000, "random_state": RANDOM_SEED},
        "grid": {"C": [0.1, 1.0, 10.0], "class_weight": [None, "balanced"]},
    },
    "random_forest": {
        "fixed": {"n_estimators": 300, "max_features": "sqrt", "bootstrap": True, "n_jobs": 1, "random_state": RANDOM_SEED},
        "grid": {"max_depth": [None, 16], "min_samples_leaf": [1, 3], "class_weight": [None, "balanced_subsample"]},
    },
    "hist_gradient_boosting": {
        "fixed": {"max_iter": 200, "early_stopping": False, "class_weight": "balanced", "random_state": RANDOM_SEED},
        "grid": {"learning_rate": [0.05, 0.1], "max_leaf_nodes": [15, 31], "l2_regularization": [0.0, 1.0]},
    },
}

MODEL_SELECTION_ORDER = (
    "highest validation macro F1",
    "highest validation weighted F1",
    "lowest validation false-positive rate",
    "lowest mean validation inference latency",
    "simpler family: logistic_regression, then random_forest, then hist_gradient_boosting",
    "lexicographically smallest canonical parameter JSON",
)
