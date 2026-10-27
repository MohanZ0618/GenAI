-- Synthetic FinTrace scoring demonstration. Credentials excluded.
-- Execute with scripts/setup_zetaris_usl.ts --apply; it checks object ownership.
-- Multi-table COMPILE below MUST be sent intact in one HTTP/JDBC request.
-- Do not split this file mechanically at semicolons. Copy bank CSV into the shared driver volume first.

-- Statement 1
CREATE LIGHTNING DATABASE FINTRACE_BANK DESCRIBE BY 'FinTrace synthetic bank CSV';

-- Statement 2
CREATE LIGHTNING FILESTORE TABLE bank_settlements FROM FINTRACE_BANK FORMAT CSV OPTIONS (path 'file:///home/zetaris/customer-data/shared/fintrace-scoring/bank_settlements.csv', header 'true', inferSchema 'true');

-- Statement 3
CREATE LIGHTNING DATABASE FINTRACE_POLICY DESCRIBE BY 'FinTrace synthetic vendor policy API';

-- Statement 4
CREATE LIGHTNING REST TABLE vendor_policy FROM FINTRACE_POLICY REQUEST (endpoint 'http://host.docker.internal:4315/vendor-policy', method 'GET', http_encoding 'URLENCODED', response_type 'JSON', insecure_ssl 'false') HEADER () BODY ();

-- Statement 5
CREATE NAMESPACE IF NOT EXISTS lightning.metastore;

-- Statement 6
CREATE NAMESPACE IF NOT EXISTS lightning.metastore.fintrace_scoring;

-- Statement 7
COMPILE USL IF NOT EXISTS payment_review DEPLOY NAMESPACE lightning.metastore.fintrace_scoring DDL
CREATE TABLE vendor_policy (
  vendor_id varchar(100) NOT NULL PRIMARY KEY,
  currency varchar(3),
  max_unreviewed_payment decimal(18,2),
  variance_review_threshold decimal(18,2),
  settlement_grace_days int,
  bank_change_review_required boolean,
  effective_from date,
  effective_to date
);
CREATE TABLE payments (
  payment_id varchar(100) NOT NULL PRIMARY KEY,
  vendor_id varchar(100) FOREIGN KEY REFERENCES vendor_policy(vendor_id),
  payment_date date,
  reference_number varchar(100),
  currency varchar(3),
  payment_amount decimal(18,2),
  payment_status varchar(30)
);
CREATE TABLE bank_settlements (
  bank_transaction_id varchar(100) NOT NULL PRIMARY KEY,
  payment_id varchar(100) FOREIGN KEY REFERENCES payments(payment_id),
  payment_reference varchar(100),
  currency varchar(3),
  settled_amount decimal(18,2),
  settlement_status varchar(30),
  posted_date date
);

-- Statement 8
ACTIVATE USL TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy AS
SELECT COALESCE(CAST(p.vendor_id AS STRING), '') AS vendor_id,
  CAST(p.currency AS STRING) AS currency,
  CAST(p.max_unreviewed_payment AS DECIMAL(18,2)) AS max_unreviewed_payment,
  CAST(p.variance_review_threshold AS DECIMAL(18,2)) AS variance_review_threshold,
  CAST(p.settlement_grace_days AS INT) AS settlement_grace_days,
  CAST(p.bank_change_review_required AS BOOLEAN) AS bank_change_review_required,
  CAST(p.effective_from AS DATE) AS effective_from,
  CAST(p.effective_to AS DATE) AS effective_to
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) AS p;

-- Statement 9
ACTIVATE USL TABLE lightning.metastore.fintrace_scoring.payment_review.payments AS
SELECT COALESCE(get_json_object(payload, '$.payment_id'), '') AS payment_id,
  get_json_object(payload, '$.vendor_id') AS vendor_id,
  CAST(get_json_object(payload, '$.payment_date') AS DATE) AS payment_date,
  get_json_object(payload, '$.reference_number') AS reference_number,
  get_json_object(payload, '$.payment_currency') AS currency,
  CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2)) AS payment_amount,
  get_json_object(payload, '$.payment_status') AS payment_status
FROM FINTRACE.payments WHERE dataset_id = 'ds-f9be2f5bab44f603' AND get_json_object(payload, '$.payment_id') IN ('PAY_DEMO_NORMAL', 'PAY_DEMO_DUP_OTHER', 'PAY_DEMO_DUP', 'PAY_DEMO_STALE', 'PAY_DEMO_MISSING', 'PAY_DEMO_FEE', 'PAY_DEMO_FUTURE_EVENT', 'PAY_DEMO_FUTURE_FEE', 'PAY_DEMO_CONTEXT_TAIL');

-- Statement 10
ACTIVATE USL TABLE lightning.metastore.fintrace_scoring.payment_review.bank_settlements AS
SELECT COALESCE(CAST(b.bank_transaction_id AS STRING), '') AS bank_transaction_id,
  p.payment_id AS payment_id,
  CAST(b.payment_reference AS STRING) AS payment_reference,
  CAST(b.currency AS STRING) AS currency,
  CAST(b.amount AS DECIMAL(18,2)) AS settled_amount,
  CAST(b.status AS STRING) AS settlement_status,
  CAST(b.posted_date AS DATE) AS posted_date
FROM FINTRACE_BANK.bank_settlements b
LEFT JOIN lightning.metastore.fintrace_scoring.payment_review.payments p
  ON b.payment_reference = p.reference_number AND b.currency = p.currency;

-- Statement 11
REGISTER DQ positive_payment_amount TABLE lightning.metastore.fintrace_scoring.payment_review.payments AS payment_amount IS NOT NULL AND payment_amount > 0;

-- Statement 12
RUN DQ positive_payment_amount TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

-- Statement 13
SHOW DQ INVALID RECORD positive_payment_amount TABLE lightning.metastore.fintrace_scoring.payment_review.payments;

-- Statement 14
REGISTER DQ policy_threshold_valid TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy AS max_unreviewed_payment IS NOT NULL AND max_unreviewed_payment >= 0 AND variance_review_threshold IS NOT NULL AND variance_review_threshold >= 0 AND settlement_grace_days IS NOT NULL AND settlement_grace_days >= 0 AND effective_from IS NOT NULL AND effective_to IS NOT NULL AND effective_to >= effective_from;

-- Statement 15
RUN DQ policy_threshold_valid TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy;

-- Statement 16
SHOW DQ INVALID RECORD policy_threshold_valid TABLE lightning.metastore.fintrace_scoring.payment_review.vendor_policy;

-- Statement 17
LIST DQ USL lightning.metastore.fintrace_scoring.payment_review;
