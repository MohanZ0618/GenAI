-- DQ-PAYMENTS: Execute the registered positive-payment amount rule in Zetaris.
RUN DQ positive_payment_amount TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

-- DQ-PAYMENTS-INVALID: Inspect rows rejected by the positive-payment amount rule.
SHOW DQ INVALID RECORD positive_payment_amount TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

-- DQ-POLICY: Execute the registered policy-threshold validity rule in Zetaris.
RUN DQ policy_threshold_valid TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy;

-- DQ-POLICY-INVALID: Inspect rows rejected by the policy-threshold validity rule.
SHOW DQ INVALID RECORD policy_threshold_valid TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy;

-- DQ-STATUS: Read the USL's native constraint and DQ status after execution.
LIST DQ USL lightning.metastore.fintrace_scoring.payment_review;

-- DQ-KEY-vendor_policy-vendor_id: Execute the USL-generated primary or foreign key constraint.
RUN DQ vendor_id TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy;

-- DQ-KEY-payments-payment_id: Execute the USL-generated primary or foreign key constraint.
RUN DQ payment_id TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

-- DQ-KEY-payments-vendor_id: Execute the USL-generated primary or foreign key constraint.
RUN DQ vendor_id TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

-- DQ-KEY-bank_settlements-bank_transaction_id: Execute the USL-generated primary or foreign key constraint.
RUN DQ bank_transaction_id TABLE lightning.metastore.fintrace_scoring.payment_review.bank_settlements;

-- DQ-KEY-bank_settlements-payment_id: Execute the USL-generated primary or foreign key constraint.
RUN DQ payment_id TABLE lightning.metastore.fintrace_scoring.payment_review.bank_settlements;
