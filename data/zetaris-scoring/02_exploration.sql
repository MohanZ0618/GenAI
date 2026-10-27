-- ERP-1: Which nine payment facts are in this scoring scope?
SELECT
  get_json_object(payload, '$.payment_id') AS payment_id,
  get_json_object(payload, '$.vendor_id') AS vendor_id,
  CAST(get_json_object(payload, '$.payment_date') AS DATE) AS payment_date,
  get_json_object(payload, '$.reference_number') AS reference_number,
  get_json_object(payload, '$.payment_currency') AS currency,
  CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2)) AS payment_amount,
  get_json_object(payload, '$.payment_status') AS payment_status
FROM FINTRACE.payments WHERE dataset_id = 'ds-f9be2f5bab44f603' AND get_json_object(payload, '$.payment_id') IN ('PAY_DEMO_NORMAL', 'PAY_DEMO_DUP_OTHER', 'PAY_DEMO_DUP', 'PAY_DEMO_STALE', 'PAY_DEMO_MISSING', 'PAY_DEMO_FEE', 'PAY_DEMO_FUTURE_EVENT', 'PAY_DEMO_FUTURE_FEE', 'PAY_DEMO_CONTEXT_TAIL')
ORDER BY payment_id;

-- ERP-2: How many scoped payments and what ERP amounts belong to each vendor and currency?
SELECT get_json_object(payload, '$.vendor_id') AS vendor_id,
  get_json_object(payload, '$.payment_currency') AS currency,
  COUNT(*) AS payment_count,
  SUM(CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2))) AS payment_amount
FROM FINTRACE.payments WHERE dataset_id = 'ds-f9be2f5bab44f603' AND get_json_object(payload, '$.payment_id') IN ('PAY_DEMO_NORMAL', 'PAY_DEMO_DUP_OTHER', 'PAY_DEMO_DUP', 'PAY_DEMO_STALE', 'PAY_DEMO_MISSING', 'PAY_DEMO_FEE', 'PAY_DEMO_FUTURE_EVENT', 'PAY_DEMO_FUTURE_FEE', 'PAY_DEMO_CONTEXT_TAIL')
GROUP BY get_json_object(payload, '$.vendor_id'), get_json_object(payload, '$.payment_currency')
ORDER BY vendor_id, currency;

-- BANK-1: Which bank references were observed, and were they posted or returned?
SELECT bank_transaction_id, payment_reference,
  CAST(currency AS STRING) AS currency,
  CAST(amount AS DECIMAL(18,2)) AS settled_amount,
  CAST(status AS STRING) AS settlement_status,
  CAST(posted_date AS DATE) AS posted_date
FROM FINTRACE_BANK.bank_settlements
ORDER BY bank_transaction_id;

-- BANK-2: What are the bank row counts and amounts by currency and bank status?
SELECT currency, status, COUNT(*) AS record_count,
  SUM(CAST(amount AS DECIMAL(18,2))) AS bank_amount
FROM FINTRACE_BANK.bank_settlements
GROUP BY currency, status ORDER BY currency, status;

-- POLICY-1: What effective supplier review thresholds are supplied by the policy API?
SELECT policy.vendor_id, policy.currency,
  CAST(policy.max_unreviewed_payment AS DECIMAL(18,2)) AS max_unreviewed_payment,
  CAST(policy.variance_review_threshold AS DECIMAL(18,2)) AS variance_review_threshold,
  CAST(policy.settlement_grace_days AS INT) AS settlement_grace_days,
  CAST(policy.effective_from AS DATE) AS effective_from,
  CAST(policy.effective_to AS DATE) AS effective_to
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) policy_rows AS policy
ORDER BY vendor_id;

-- POLICY-2: Do the policy feeds have one row per vendor and consistent declared currency/thresholds?
SELECT policy.currency, COUNT(*) AS policy_count,
  COUNT(DISTINCT policy.vendor_id) AS distinct_vendors,
  MIN(CAST(policy.max_unreviewed_payment AS DECIMAL(18,2))) AS minimum_review_threshold,
  MAX(CAST(policy.max_unreviewed_payment AS DECIMAL(18,2))) AS maximum_review_threshold,
  MIN(CAST(policy.variance_review_threshold AS DECIMAL(18,2))) AS minimum_variance_threshold
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) policy_rows AS policy
GROUP BY policy.currency ORDER BY policy.currency;
