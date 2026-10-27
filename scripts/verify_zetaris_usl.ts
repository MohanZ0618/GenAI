import { randomUUID, createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { parse } from "csv-parse/sync";
import Decimal from "decimal.js";
import { parseZetarisResult } from "../apps/api/src/integrations/zetaris.ts";

// Explicit local scoring verification. No model calls or changes to the app adapter.
if (process.argv.slice(2).join(" ") !== "--connect")
  throw new Error(
    "Usage: node --env-file=.env.zetaris.local --import tsx scripts/verify_zetaris_usl.ts --connect",
  );
const root = fileURLToPath(new URL("../", import.meta.url));
const directory = resolve(root, "data/zetaris-scoring");
const manifest = JSON.parse(
  await readFile(resolve(directory, "source-manifest.json"), "utf8"),
) as {
  expectedDatasetId: string;
  paymentIds: string[];
  files: Record<string, { sha256: string }>;
};
const base = process.env.ZETARIS_BASE_URL;
const token = process.env.ZETARIS_API_KEY;
const org = process.env.ZETARIS_ORG_ID;
if (
  !base ||
  !/^https?:\/\/[^/]+\/?$/.test(base) ||
  !token ||
  !org ||
  !/^\d+$/.test(org)
)
  throw new Error(
    "Configure the Zetaris origin, API credential and numeric organisation ID first",
  );
const literal = (value: string) => "'" + value.replaceAll("'", "''") + "'";
const scope = `dataset_id = ${literal(manifest.expectedDatasetId)} AND get_json_object(payload, '$.payment_id') IN (${manifest.paymentIds.map(literal).join(", ")})`;
const usl = "lightning.metastore.fintrace_scoring.payment_review";
type Row = Record<string, unknown>;
type Query = { id: string; source: string; question: string; sql: string };
type Evidence = Query & {
  httpStatus: number;
  elapsedMs: number;
  rowCount: number;
  rows: Row[];
};
const evidence: Evidence[] = [];
const report: Record<string, unknown> = {
  startedAt: new Date().toISOString(),
  syntheticDataOnly: true,
  passed: false,
  datasetId: manifest.expectedDatasetId,
  usl,
  notice:
    "Three simulated business feeds over PostgreSQL, CSV and HTTP. ERP and bank records share a synthetic scenario generator. No customer data, model accuracy, Nightshift completion, measured development-time saving or automatic financial decision is claimed.",
  queries: evidence,
};
const persist = () =>
  writeFile(
    resolve(directory, "results.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
async function execute(query: Query): Promise<Row[]> {
  if (
    !/^(SELECT|WITH|DESCRIBE|LIST DQ|RUN DQ|SHOW DQ)\b/i.test(query.sql.trim())
  )
    throw new Error(
      "Verification is restricted to reads and named DQ execution",
    );
  const started = performance.now();
  const response = await fetch(
    base!.replace(/\/$/, "") + "/api/proxy/sql-editor/sqls/run-query",
    {
      method: "POST",
      signal: AbortSignal.timeout(120000),
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Org-ID": org!,
        "X-Request-ID": randomUUID(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ sql: query.sql, limit: 1000 }),
    },
  );
  if (!response.ok)
    throw new Error(
      `Scoring query ${query.id} failed (HTTP ${response.status}); credentials and response bodies omitted`,
    );
  const rows = parseZetarisResult(await response.json());
  if (rows.length >= 1000)
    throw new Error(`Scoring query ${query.id} reached its result bound`);
  evidence.push({
    ...query,
    httpStatus: response.status,
    elapsedMs: Math.round(performance.now() - started),
    rowCount: rows.length,
    rows,
  });
  await persist();
  console.log(
    JSON.stringify({
      query: query.id,
      source: query.source,
      rows: rows.length,
      status: "succeeded",
    }),
  );
  return rows;
}
const erpProjection = `SELECT
  get_json_object(payload, '$.payment_id') AS payment_id,
  get_json_object(payload, '$.vendor_id') AS vendor_id,
  CAST(get_json_object(payload, '$.payment_date') AS DATE) AS payment_date,
  get_json_object(payload, '$.reference_number') AS reference_number,
  get_json_object(payload, '$.payment_currency') AS currency,
  CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2)) AS payment_amount,
  get_json_object(payload, '$.payment_status') AS payment_status
FROM FINTRACE.payments WHERE ${scope}`;
const bankProjection = `SELECT bank_transaction_id, payment_reference,
  CAST(currency AS STRING) AS currency,
  CAST(amount AS DECIMAL(18,2)) AS settled_amount,
  CAST(status AS STRING) AS settlement_status,
  CAST(posted_date AS DATE) AS posted_date
FROM FINTRACE_BANK.bank_settlements`;
const policyProjection = `SELECT policy.vendor_id, policy.currency,
  CAST(policy.max_unreviewed_payment AS DECIMAL(18,2)) AS max_unreviewed_payment,
  CAST(policy.variance_review_threshold AS DECIMAL(18,2)) AS variance_review_threshold,
  CAST(policy.settlement_grace_days AS INT) AS settlement_grace_days,
  CAST(policy.effective_from AS DATE) AS effective_from,
  CAST(policy.effective_to AS DATE) AS effective_to
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) policy_rows AS policy`;
const explorations: Query[] = [
  {
    id: "ERP-1",
    source: "PostgreSQL / FINTRACE.payments",
    question: "Which nine payment facts are in this scoring scope?",
    sql: erpProjection + "\nORDER BY payment_id",
  },
  {
    id: "ERP-2",
    source: "PostgreSQL / FINTRACE.payments",
    question:
      "How many scoped payments and what ERP amounts belong to each vendor and currency?",
    sql: `SELECT get_json_object(payload, '$.vendor_id') AS vendor_id,
  get_json_object(payload, '$.payment_currency') AS currency,
  COUNT(*) AS payment_count,
  SUM(CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2))) AS payment_amount
FROM FINTRACE.payments WHERE ${scope}
GROUP BY get_json_object(payload, '$.vendor_id'), get_json_object(payload, '$.payment_currency')
ORDER BY vendor_id, currency`,
  },
  {
    id: "BANK-1",
    source: "CSV / FINTRACE_BANK.bank_settlements",
    question:
      "Which bank references were observed, and were they posted or returned?",
    sql: bankProjection + "\nORDER BY bank_transaction_id",
  },
  {
    id: "BANK-2",
    source: "CSV / FINTRACE_BANK.bank_settlements",
    question:
      "What are the bank row counts and amounts by currency and bank status?",
    sql: `SELECT currency, status, COUNT(*) AS record_count,
  SUM(CAST(amount AS DECIMAL(18,2))) AS bank_amount
FROM FINTRACE_BANK.bank_settlements
GROUP BY currency, status ORDER BY currency, status`,
  },
  {
    id: "POLICY-1",
    source: "HTTP / FINTRACE_POLICY.vendor_policy",
    question:
      "What effective supplier review thresholds are supplied by the policy API?",
    sql: policyProjection + "\nORDER BY vendor_id",
  },
  {
    id: "POLICY-2",
    source: "HTTP / FINTRACE_POLICY.vendor_policy",
    question:
      "Do the policy feeds have one row per vendor and consistent declared currency/thresholds?",
    sql: `SELECT policy.currency, COUNT(*) AS policy_count,
  COUNT(DISTINCT policy.vendor_id) AS distinct_vendors,
  MIN(CAST(policy.max_unreviewed_payment AS DECIMAL(18,2))) AS minimum_review_threshold,
  MAX(CAST(policy.max_unreviewed_payment AS DECIMAL(18,2))) AS maximum_review_threshold,
  MIN(CAST(policy.variance_review_threshold AS DECIMAL(18,2))) AS minimum_variance_threshold
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) policy_rows AS policy
GROUP BY policy.currency ORDER BY policy.currency`,
  },
];
const observation = `CASE WHEN b.bank_transaction_id IS NULL THEN 'no_bank_observation'
  WHEN b.settlement_status = 'returned' THEN 'returned'
  WHEN b.settlement_status = 'posted' THEN 'posted' ELSE 'other' END`;
const joinProjection = `SELECT p.payment_id, p.vendor_id, p.currency, p.payment_amount,
  b.bank_transaction_id, b.settlement_status, b.settled_amount,
  ${observation} AS bank_observation,
  CASE WHEN b.settlement_status = 'posted'
    THEN CAST(p.payment_amount - b.settled_amount AS DECIMAL(18,2))
    ELSE CAST(NULL AS DECIMAL(18,2)) END AS observed_variance,
  v.max_unreviewed_payment, v.variance_review_threshold`;
const policyJoin = `LEFT JOIN ${usl}.vendor_policy v ON p.vendor_id = v.vendor_id AND p.currency = v.currency
  AND p.payment_date BETWEEN v.effective_from AND v.effective_to`;
const uslQueries: Query[] = [
  {
    id: "USL-1",
    source: usl,
    question:
      "What bank observation and effective supplier policy belong to each payment?",
    sql: `${joinProjection}
FROM ${usl}.payments p
LEFT JOIN ${usl}.bank_settlements b ON p.payment_id = b.payment_id AND p.currency = b.currency
${policyJoin}
ORDER BY p.payment_id`,
  },
  {
    id: "USL-2",
    source: usl,
    question:
      "How many payments have posted, returned or missing bank observations, without mixing their monetary meaning?",
    sql: `SELECT p.currency, ${observation} AS bank_observation,
  COUNT(*) AS payment_count, SUM(p.payment_amount) AS erp_payment_amount,
  SUM(CASE WHEN b.settlement_status = 'posted' THEN b.settled_amount ELSE CAST(NULL AS DECIMAL(18,2)) END) AS posted_bank_amount,
  SUM(CASE WHEN b.settlement_status = 'posted' THEN p.payment_amount - b.settled_amount ELSE CAST(NULL AS DECIMAL(18,2)) END) AS posted_observed_variance
FROM ${usl}.payments p
LEFT JOIN ${usl}.bank_settlements b ON p.payment_id = b.payment_id AND p.currency = b.currency
GROUP BY p.currency, ${observation}
ORDER BY p.currency, bank_observation`,
  },
  {
    id: "USL-3",
    source: usl,
    question:
      "Which payments exceed the effective policy's illustrative manual-review threshold?",
    sql: `SELECT p.payment_id, p.vendor_id, p.currency, p.payment_amount, v.max_unreviewed_payment
FROM ${usl}.payments p
${policyJoin}
WHERE p.payment_amount > v.max_unreviewed_payment
ORDER BY p.payment_id`,
  },
];
const handwritten: Query = {
  id: "BONUS-MANUAL",
  source: "Direct PostgreSQL + CSV + HTTP source tables",
  question:
    "Does a hand-written source-normalization query return exactly the same rows as USL-1?",
  sql: `WITH erp AS (${erpProjection}),
bank_feed AS (${bankProjection}),
policies AS (${policyProjection})
${joinProjection}
FROM erp p
LEFT JOIN bank_feed b ON p.reference_number = b.payment_reference AND p.currency = b.currency
LEFT JOIN policies v ON p.vendor_id = v.vendor_id AND p.currency = v.currency
  AND p.payment_date BETWEEN v.effective_from AND v.effective_to
ORDER BY p.payment_id`,
};
const dqQueries: Query[] = [
  {
    id: "DQ-PAYMENTS",
    source: usl + ".payments",
    question: "Execute the registered positive-payment amount rule in Zetaris.",
    sql: `RUN DQ positive_payment_amount TABLE ${usl}.payments`,
  },
  {
    id: "DQ-PAYMENTS-INVALID",
    source: usl + ".payments",
    question: "Inspect rows rejected by the positive-payment amount rule.",
    sql: `SHOW DQ INVALID RECORD positive_payment_amount TABLE ${usl}.payments`,
  },
  {
    id: "DQ-POLICY",
    source: usl + ".vendor_policy",
    question:
      "Execute the registered policy-threshold validity rule in Zetaris.",
    sql: `RUN DQ policy_threshold_valid TABLE ${usl}.vendor_policy`,
  },
  {
    id: "DQ-POLICY-INVALID",
    source: usl + ".vendor_policy",
    question: "Inspect rows rejected by the policy-threshold validity rule.",
    sql: `SHOW DQ INVALID RECORD policy_threshold_valid TABLE ${usl}.vendor_policy`,
  },
  {
    id: "DQ-STATUS",
    source: usl,
    question: "Read the USL's native constraint and DQ status after execution.",
    sql: `LIST DQ USL ${usl}`,
  },
];
const sqlFile = (queries: Query[]) =>
  queries
    .map((query) => `-- ${query.id}: ${query.question}\n${query.sql};`)
    .join("\n\n") + "\n";
const assert = (ok: unknown, message: string) => {
  if (!ok) throw new Error(message);
};
const money = (value: unknown) =>
  value === null || value === undefined
    ? null
    : new Decimal(String(value)).toFixed(2);
const monetaryFields = new Set([
  "payment_amount",
  "settled_amount",
  "observed_variance",
  "max_unreviewed_payment",
  "variance_review_threshold",
]);
const canonical = (rows: Row[]) =>
  JSON.stringify(
    rows.map((row) =>
      Object.fromEntries(
        Object.entries(row).map(([key, value]) => [
          key,
          monetaryFields.has(key)
            ? money(value)
            : value === null
              ? null
              : String(value),
        ]),
      ),
    ),
  );
try {
  for (const [name, expected] of Object.entries(manifest.files)) {
    const actual = createHash("sha256")
      .update(await readFile(resolve(directory, name)))
      .digest("hex");
    assert(
      actual === expected.sha256,
      `Synthetic source file changed: ${name}`,
    );
  }
  await writeFile(
    resolve(directory, "02_exploration.sql"),
    sqlFile(explorations),
  );
  await writeFile(
    resolve(directory, "03_usl_queries.sql"),
    sqlFile(uslQueries) + "\n" + sqlFile([handwritten]),
  );
  await writeFile(resolve(directory, "04_quality.sql"), sqlFile(dqQueries));
  const sourceRows: Row[][] = [];
  for (const query of explorations) sourceRows.push(await execute(query));
  const erpFixture = parse(
    await readFile(resolve(directory, "erp_payments_preview.csv"), "utf8"),
    { columns: true, skip_empty_lines: true },
  ) as Record<string, string>[];
  const bankFixture = parse(
    await readFile(resolve(directory, "bank_settlements.csv"), "utf8"),
    { columns: true, skip_empty_lines: true },
  ) as Record<string, string>[];
  const policies = JSON.parse(
    await readFile(resolve(directory, "vendor_policy.json"), "utf8"),
  ) as Record<string, unknown>[];
  assert(
    sourceRows[0].length === 9 &&
      sourceRows[2].length === 7 &&
      sourceRows[4].length === 8,
    "Unexpected actual source cardinality",
  );
  assert(erpFixture.length === 9, "ERP fixture scope changed");
  for (const expected of erpFixture) {
    const row = sourceRows[0].find(
      (item) => item.payment_id === expected.payment_id,
    );
    assert(
      row &&
        row.vendor_id === expected.vendor_id &&
        row.reference_number === expected.reference_number &&
        row.currency === expected.payment_currency &&
        money(row.payment_amount) === money(expected.payment_amount),
      "Actual ERP source differs from the inspectable synthetic fixture",
    );
  }
  const joined = await execute(uslQueries[0]);
  const summary = await execute(uslQueries[1]);
  const thresholdRows = await execute(uslQueries[2]);
  assert(
    joined.length === 9 &&
      new Set(joined.map((row) => row.payment_id)).size === 9,
    "USL join lost or multiplied a payment",
  );
  for (const expected of erpFixture) {
    const actual = joined.find(
      (row) => row.payment_id === expected.payment_id,
    )!;
    const bankMatches = bankFixture.filter(
      (row) =>
        row.payment_reference === expected.reference_number &&
        row.currency === expected.payment_currency,
    );
    const policyMatches = policies.filter(
      (row) =>
        row.vendor_id === expected.vendor_id &&
        row.currency === expected.payment_currency &&
        expected.payment_date >= String(row.effective_from) &&
        expected.payment_date <= String(row.effective_to),
    );
    assert(
      bankMatches.length <= 1 && policyMatches.length === 1,
      "Synthetic input does not have the declared join grain",
    );
    const bank = bankMatches[0];
    const status = !bank
      ? "no_bank_observation"
      : bank.status === "posted"
        ? "posted"
        : bank.status === "returned"
          ? "returned"
          : "other";
    const variance =
      bank?.status === "posted"
        ? new Decimal(expected.payment_amount).minus(bank.amount).toFixed(2)
        : null;
    assert(
      actual.bank_observation === status &&
        money(actual.observed_variance) === variance,
      "USL bank observation or NULL interpretation differs from independent source calculation",
    );
    assert(
      (actual.bank_transaction_id ?? null) ===
        (bank?.bank_transaction_id ?? null),
      "USL bank lineage differs from the CSV",
    );
    assert(
      money(actual.max_unreviewed_payment) ===
        money(policyMatches[0].max_unreviewed_payment),
      "USL effective policy differs from the API fixture",
    );
  }
  assert(
    thresholdRows.length === 2 &&
      thresholdRows.every((row) =>
        new Decimal(String(row.payment_amount)).gt(
          String(row.max_unreviewed_payment),
        ),
      ),
    "Policy review query differs from the declared threshold",
  );
  const manualRows = await execute(handwritten);
  assert(
    canonical(joined) === canonical(manualRows),
    "Hand-written normalization and USL query do not agree",
  );
  const quality: Row[][] = [];
  for (const query of dqQueries) quality.push(await execute(query));
  const checkedRule = (rows: Row[], total: number) =>
    rows.length === 1 &&
    Number(rows[0].total_record) === total &&
    Number(rows[0].valid_record) === total &&
    Number(rows[0].invalid_record) === 0;
  assert(
    checkedRule(quality[0], 9) &&
      checkedRule(quality[2], 8) &&
      quality[1].length === 0 &&
      quality[3].length === 0,
    "Native Zetaris DQ counts or invalid records differ from the source population",
  );
  const constraints = [
    { table: "vendor_policy", name: "vendor_id", total: 8 },
    { table: "payments", name: "payment_id", total: 9 },
    { table: "payments", name: "vendor_id", total: 9 },
    { table: "bank_settlements", name: "bank_transaction_id", total: 7 },
    { table: "bank_settlements", name: "payment_id", total: 7 },
  ];
  for (const rule of constraints) {
    assert(
      quality[4].some(
        (row) => row.table === rule.table && row.name === rule.name,
      ),
      "Expected USL key constraint is missing",
    );
    const rows = await execute({
      id: `DQ-KEY-${rule.table}-${rule.name}`,
      source: `${usl}.${rule.table}`,
      question: "Execute the USL-generated primary or foreign key constraint.",
      sql: `RUN DQ ${rule.name} TABLE ${usl}.${rule.table}`,
    });
    assert(
      checkedRule(rows, rule.total),
      "Native USL key constraint failed or evaluated the wrong population",
    );
  }
  await writeFile(
    resolve(directory, "04_quality.sql"),
    sqlFile(evidence.filter((query) => query.id.startsWith("DQ-"))),
  );
  const counts = joined.reduce<Record<string, number>>(
    (counts, row) => {
      const key = String(row.bank_observation);
      counts[key] = (counts[key] || 0) + 1;
      return counts;
    },
    {} as Record<string, number>,
  );
  report.checks = {
    threeSourceTransports: ["PostgreSQL", "CSV", "HTTP API"],
    actualSourceRows: {
      erp: sourceRows[0].length,
      bank: sourceRows[2].length,
      policy: sourceRows[4].length,
    },
    joinedRows: joined.length,
    uniquePayments: new Set(joined.map((row) => row.payment_id)).size,
    bankObservations: counts,
    effectivePolicyMatches: 9,
    nullPreservedForMissingAndReturned: true,
    sourceFixtureComparison: "passed",
    policyReviewRows: thresholdRows.length,
    handwrittenMatchesUsl: true,
    sourceSqlCharacters: handwritten.sql.length,
    uslConsumerSqlCharacters: uslQueries[0].sql.length,
    measuredDevelopmentTimeSaving: null,
    qualityInvalidRows: {
      positive_payment_amount: quality[1].length,
      policy_threshold_valid: quality[3].length,
    },
    nativeQualityRulesExecuted: 7,
    summaryRows: summary.length,
  };
  report.passed = true;
  report.completedAt = new Date().toISOString();
  await persist();
  console.log(
    JSON.stringify({
      passed: true,
      report: "data/zetaris-scoring/results.json",
      checks: report.checks,
    }),
  );
} catch (error) {
  report.failedAt = new Date().toISOString();
  report.failure =
    error instanceof Error ? error.message : "Scoring verification failed";
  await persist();
  throw error;
}
