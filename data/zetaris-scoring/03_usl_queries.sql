-- USL-1: What bank observation and effective supplier policy belong to each payment?
SELECT p.payment_id, p.vendor_id, p.currency, p.payment_amount,
  b.bank_transaction_id, b.settlement_status, b.settled_amount,
  CASE WHEN b.bank_transaction_id IS NULL THEN 'no_bank_observation'
  WHEN b.settlement_status = 'returned' THEN 'returned'
  WHEN b.settlement_status = 'posted' THEN 'posted' ELSE 'other' END AS bank_observation,
  CASE WHEN b.settlement_status = 'posted'
    THEN CAST(p.payment_amount - b.settled_amount AS DECIMAL(18,2))
    ELSE CAST(NULL AS DECIMAL(18,2)) END AS observed_variance,
  v.max_unreviewed_payment, v.variance_review_threshold
FROM lightning.metastore.fintrace_scoring.payment_review.payments p
LEFT JOIN lightning.metastore.fintrace_scoring.payment_review.bank_settlements b ON p.payment_id = b.payment_id AND p.currency = b.currency
LEFT JOIN lightning.metastore.fintrace_scoring.payment_review.vendor_policy v ON p.vendor_id = v.vendor_id AND p.currency = v.currency
  AND p.payment_date BETWEEN v.effective_from AND v.effective_to
ORDER BY p.payment_id;

-- USL-2: How many payments have posted, returned or missing bank observations, without mixing their monetary meaning?
SELECT p.currency, CASE WHEN b.bank_transaction_id IS NULL THEN 'no_bank_observation'
  WHEN b.settlement_status = 'returned' THEN 'returned'
  WHEN b.settlement_status = 'posted' THEN 'posted' ELSE 'other' END AS bank_observation,
  COUNT(*) AS payment_count, SUM(p.payment_amount) AS erp_payment_amount,
  SUM(CASE WHEN b.settlement_status = 'posted' THEN b.settled_amount ELSE CAST(NULL AS DECIMAL(18,2)) END) AS posted_bank_amount,
  SUM(CASE WHEN b.settlement_status = 'posted' THEN p.payment_amount - b.settled_amount ELSE CAST(NULL AS DECIMAL(18,2)) END) AS posted_observed_variance
FROM lightning.metastore.fintrace_scoring.payment_review.payments p
LEFT JOIN lightning.metastore.fintrace_scoring.payment_review.bank_settlements b ON p.payment_id = b.payment_id AND p.currency = b.currency
GROUP BY p.currency, CASE WHEN b.bank_transaction_id IS NULL THEN 'no_bank_observation'
  WHEN b.settlement_status = 'returned' THEN 'returned'
  WHEN b.settlement_status = 'posted' THEN 'posted' ELSE 'other' END
ORDER BY p.currency, bank_observation;

-- USL-3: Which payments exceed the effective policy's illustrative manual-review threshold?
SELECT p.payment_id, p.vendor_id, p.currency, p.payment_amount, v.max_unreviewed_payment
FROM lightning.metastore.fintrace_scoring.payment_review.payments p
LEFT JOIN lightning.metastore.fintrace_scoring.payment_review.vendor_policy v ON p.vendor_id = v.vendor_id AND p.currency = v.currency
  AND p.payment_date BETWEEN v.effective_from AND v.effective_to
WHERE p.payment_amount > v.max_unreviewed_payment
ORDER BY p.payment_id;

-- BONUS-MANUAL: Does a hand-written source-normalization query return exactly the same rows as USL-1?
WITH erp AS (SELECT
  get_json_object(payload, '$.payment_id') AS payment_id,
  get_json_object(payload, '$.vendor_id') AS vendor_id,
  CAST(get_json_object(payload, '$.payment_date') AS DATE) AS payment_date,
  get_json_object(payload, '$.reference_number') AS reference_number,
  get_json_object(payload, '$.payment_currency') AS currency,
  CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2)) AS payment_amount,
  get_json_object(payload, '$.payment_status') AS payment_status
FROM FINTRACE.payments WHERE dataset_id = 'ds-f9be2f5bab44f603' AND get_json_object(payload, '$.payment_id') IN ('PAY_DEMO_NORMAL', 'PAY_DEMO_DUP_OTHER', 'PAY_DEMO_DUP', 'PAY_DEMO_STALE', 'PAY_DEMO_MISSING', 'PAY_DEMO_FEE', 'PAY_DEMO_FUTURE_EVENT', 'PAY_DEMO_FUTURE_FEE', 'PAY_DEMO_CONTEXT_TAIL')),
bank_feed AS (SELECT bank_transaction_id, payment_reference,
  CAST(currency AS STRING) AS currency,
  CAST(amount AS DECIMAL(18,2)) AS settled_amount,
  CAST(status AS STRING) AS settlement_status,
  CAST(posted_date AS DATE) AS posted_date
FROM FINTRACE_BANK.bank_settlements),
policies AS (SELECT policy.vendor_id, policy.currency,
  CAST(policy.max_unreviewed_payment AS DECIMAL(18,2)) AS max_unreviewed_payment,
  CAST(policy.variance_review_threshold AS DECIMAL(18,2)) AS variance_review_threshold,
  CAST(policy.settlement_grace_days AS INT) AS settlement_grace_days,
  CAST(policy.effective_from AS DATE) AS effective_from,
  CAST(policy.effective_to AS DATE) AS effective_to
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) policy_rows AS policy)
SELECT p.payment_id, p.vendor_id, p.currency, p.payment_amount,
  b.bank_transaction_id, b.settlement_status, b.settled_amount,
  CASE WHEN b.bank_transaction_id IS NULL THEN 'no_bank_observation'
  WHEN b.settlement_status = 'returned' THEN 'returned'
  WHEN b.settlement_status = 'posted' THEN 'posted' ELSE 'other' END AS bank_observation,
  CASE WHEN b.settlement_status = 'posted'
    THEN CAST(p.payment_amount - b.settled_amount AS DECIMAL(18,2))
    ELSE CAST(NULL AS DECIMAL(18,2)) END AS observed_variance,
  v.max_unreviewed_payment, v.variance_review_threshold
FROM erp p
LEFT JOIN bank_feed b ON p.reference_number = b.payment_reference AND p.currency = b.currency
LEFT JOIN policies v ON p.vendor_id = v.vendor_id AND p.currency = v.currency
  AND p.payment_date BETWEEN v.effective_from AND v.effective_to
ORDER BY p.payment_id;
