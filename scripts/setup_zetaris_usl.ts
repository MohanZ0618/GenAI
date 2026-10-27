import { createHash, randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { parseZetarisResult } from "../apps/api/src/integrations/zetaris.ts";

// Provisioning is deliberately separate from the investigation's SELECT-only adapter.
// Run prepare_zetaris_scoring.ts and serve_zetaris_policy.ts first. No model calls.
const args = process.argv.slice(2);
if (args.some((arg) => arg !== "--apply"))
  throw new Error(
    "Usage: node --env-file=.env.zetaris.local --import tsx scripts/setup_zetaris_usl.ts [--apply]",
  );
const apply = args.includes("--apply");
const root = process.cwd();
const assets = resolve("data/zetaris-scoring");
const local = resolve(".local/zetaris-runtime");
const binding = JSON.parse(
  await readFile(join(local, "scoring-binding.json"), "utf8"),
) as {
  datasetId: string;
  focusPaymentIds: string[];
  cutoff: string;
};
if (!binding.datasetId || binding.focusPaymentIds?.length !== 9)
  throw new Error(
    "Prepare the independent scoring dataset with nine focus payments first",
  );
const namespace = "lightning.metastore.fintrace_scoring";
const model = "payment_review";
const usl = `${namespace}.${model}`;
const driver =
  process.env.ZETARIS_DRIVER_CONTAINER || "fintrace-zetaris-driver-1";
const bankPath =
  "/home/zetaris/customer-data/shared/fintrace-scoring/bank_settlements.csv";
const policyPort = process.env.ZETARIS_POLICY_PORT || "4315";
if (
  !/^\d+$/.test(policyPort) ||
  Number(policyPort) < 1 ||
  Number(policyPort) > 65535
)
  throw new Error("ZETARIS_POLICY_PORT must be an integer from 1 to 65535");
const policyUrl =
  process.env.ZETARIS_SCORING_POLICY_URL ||
  `http://host.docker.internal:${policyPort}/vendor-policy`;
const policyProbeUrl = new URL(policyUrl);
if (policyProbeUrl.hostname === "host.docker.internal")
  policyProbeUrl.hostname = "127.0.0.1";
const bankContents = await readFile(join(assets, "bank_settlements.csv"));
const policyContents = await readFile(join(assets, "vendor_policy.json"));
const literal = (value: string) => `'${value.replaceAll("'", "''")}'`;
const ids = binding.focusPaymentIds.map(literal).join(", ");
const scope = `dataset_id = ${literal(binding.datasetId)} AND get_json_object(payload, '$.payment_id') IN (${ids})`;
const ddl = `CREATE TABLE vendor_policy (
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
);`;
const activation: Record<string, string> = {
  vendor_policy: `ACTIVATE USL TABLE ${usl}.vendor_policy AS
SELECT COALESCE(CAST(p.vendor_id AS STRING), '') AS vendor_id,
  CAST(p.currency AS STRING) AS currency,
  CAST(p.max_unreviewed_payment AS DECIMAL(18,2)) AS max_unreviewed_payment,
  CAST(p.variance_review_threshold AS DECIMAL(18,2)) AS variance_review_threshold,
  CAST(p.settlement_grace_days AS INT) AS settlement_grace_days,
  CAST(p.bank_change_review_required AS BOOLEAN) AS bank_change_review_required,
  CAST(p.effective_from AS DATE) AS effective_from,
  CAST(p.effective_to AS DATE) AS effective_to
FROM FINTRACE_POLICY.vendor_policy
LATERAL VIEW explode(data) AS p`,
  payments: `ACTIVATE USL TABLE ${usl}.payments AS
SELECT COALESCE(get_json_object(payload, '$.payment_id'), '') AS payment_id,
  get_json_object(payload, '$.vendor_id') AS vendor_id,
  CAST(get_json_object(payload, '$.payment_date') AS DATE) AS payment_date,
  get_json_object(payload, '$.reference_number') AS reference_number,
  get_json_object(payload, '$.payment_currency') AS currency,
  CAST(get_json_object(payload, '$.payment_amount') AS DECIMAL(18,2)) AS payment_amount,
  get_json_object(payload, '$.payment_status') AS payment_status
FROM FINTRACE.payments WHERE ${scope}`,
  bank_settlements: `ACTIVATE USL TABLE ${usl}.bank_settlements AS
SELECT COALESCE(CAST(b.bank_transaction_id AS STRING), '') AS bank_transaction_id,
  p.payment_id AS payment_id,
  CAST(b.payment_reference AS STRING) AS payment_reference,
  CAST(b.currency AS STRING) AS currency,
  CAST(b.amount AS DECIMAL(18,2)) AS settled_amount,
  CAST(b.status AS STRING) AS settlement_status,
  CAST(b.posted_date AS DATE) AS posted_date
FROM FINTRACE_BANK.bank_settlements b
LEFT JOIN ${usl}.payments p
  ON b.payment_reference = p.reference_number AND b.currency = p.currency`,
};
const rules = [
  {
    name: "positive_payment_amount",
    table: "payments",
    expression: "payment_amount IS NOT NULL AND payment_amount > 0",
  },
  {
    name: "policy_threshold_valid",
    table: "vendor_policy",
    expression:
      "max_unreviewed_payment IS NOT NULL AND max_unreviewed_payment >= 0 AND variance_review_threshold IS NOT NULL AND variance_review_threshold >= 0 AND settlement_grace_days IS NOT NULL AND settlement_grace_days >= 0 AND effective_from IS NOT NULL AND effective_to IS NOT NULL AND effective_to >= effective_from",
  },
];
const sourceSql = {
  FINTRACE_BANK: [
    "CREATE LIGHTNING DATABASE FINTRACE_BANK DESCRIBE BY 'FinTrace synthetic bank CSV'",
    `CREATE LIGHTNING FILESTORE TABLE bank_settlements FROM FINTRACE_BANK FORMAT CSV OPTIONS (path ${literal(`file://${bankPath}`)}, header 'true', inferSchema 'true')`,
  ],
  FINTRACE_POLICY: [
    "CREATE LIGHTNING DATABASE FINTRACE_POLICY DESCRIBE BY 'FinTrace synthetic vendor policy API'",
    `CREATE LIGHTNING REST TABLE vendor_policy FROM FINTRACE_POLICY REQUEST (endpoint ${literal(policyUrl)}, method 'GET', http_encoding 'URLENCODED', response_type 'JSON', insecure_ssl 'false') HEADER () BODY ()`,
  ],
};
const compile = `COMPILE USL IF NOT EXISTS ${model} DEPLOY NAMESPACE ${namespace} DDL\n${ddl}`;
const statements = [
  ...Object.values(sourceSql).flat(),
  "CREATE NAMESPACE IF NOT EXISTS lightning.metastore",
  `CREATE NAMESPACE IF NOT EXISTS ${namespace}`,
  compile,
  ...Object.values(activation),
  ...rules.flatMap((rule) => [
    `REGISTER DQ ${rule.name} TABLE ${usl}.${rule.table} AS ${rule.expression}`,
    `RUN DQ ${rule.name} TABLE ${usl}.${rule.table}`,
    `SHOW DQ INVALID RECORD ${rule.name} TABLE ${usl}.${rule.table}`,
  ]),
  `LIST DQ USL ${usl}`,
];
await mkdir(assets, { recursive: true });
await writeFile(
  join(assets, "01_setup.sql"),
  [
    "-- Synthetic FinTrace scoring demonstration. Credentials excluded.",
    "-- Execute with scripts/setup_zetaris_usl.ts --apply; it checks object ownership.",
    "-- Multi-table COMPILE below MUST be sent intact in one HTTP/JDBC request.",
    "-- Do not split this file mechanically at semicolons. Copy bank CSV into the shared driver volume first.",
    ...statements.map(
      (sql, index) =>
        `\n-- Statement ${index + 1}\n${sql.trimEnd().replace(/;+$/, "")};`,
    ),
  ].join("\n") + "\n",
);
if (!apply) {
  console.log(
    JSON.stringify({
      apply: false,
      generatedSql: "data/zetaris-scoring/01_setup.sql",
      namespace,
      model,
      sourceNames: ["FINTRACE", "FINTRACE_BANK", "FINTRACE_POLICY"],
      notice:
        "No service requests or platform mutations. Use --apply for actual provisioning.",
    }),
  );
  process.exit(0);
}

const base = process.env.ZETARIS_BASE_URL;
const org = process.env.ZETARIS_ORG_ID;
const token = process.env.ZETARIS_API_KEY;
if (
  !base ||
  !/^https?:\/\/[^/]+\/?$/.test(base) ||
  !org ||
  !/^\d+$/.test(org) ||
  !token
)
  throw new Error(
    "Configure the Zetaris UI origin, numeric organisation and private API credential",
  );
await mkdir(local, { recursive: true });
const statePath = join(local, "scoring-setup-state.json");
const privateReport = join(local, "scoring-setup-report.json");
const publicReport = join(assets, "evidence", "setup-result.json");
const fingerprint = createHash("sha256")
  .update(
    JSON.stringify({
      base,
      org,
      datasetId: binding.datasetId,
      ids,
      bank: bankContents.toString("base64"),
      policy: policyContents.toString("base64"),
      policyUrl,
      ddl,
    }),
  )
  .digest("hex");
type State = {
  fingerprint: string;
  namespace?: boolean;
  modelId?: string;
  activated: string[];
  rules: string[];
  bankFile?: boolean;
  databases: Record<string, { id: string; tables: string[] }>;
};
let state: State;
try {
  state = JSON.parse(await readFile(statePath, "utf8")) as State;
} catch (error) {
  if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  state = { fingerprint, activated: [], rules: [], databases: {} };
}
if (state.fingerprint !== fingerprint)
  throw new Error(
    "Scoring inputs or platform differ from the ownership receipt; refusing to overwrite existing objects",
  );
const report: { [key: string]: unknown; operations: unknown[] } = {
  startedAt: new Date().toISOString(),
  syntheticDataOnly: true,
  namespace,
  model,
  datasetId: binding.datasetId,
  sourceNames: ["FINTRACE", "FINTRACE_BANK", "FINTRACE_POLICY"],
  operations: [],
  success: false,
};
const persist = async () => {
  await writeFile(statePath, JSON.stringify(state, null, 2) + "\n", {
    mode: 0o600,
  });
  await writeFile(privateReport, JSON.stringify(report, null, 2) + "\n", {
    mode: 0o600,
  });
};
const query = async (sql: string, operation: string) => {
  const response = await fetch(
    base!.replace(/\/$/, "") + "/api/proxy/sql-editor/sqls/run-query",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Org-ID": org!,
        "X-Request-ID": randomUUID(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ sql, limit: 1001 }),
      signal: AbortSignal.timeout(90000),
    },
  );
  const body: unknown = await response.json();
  if (!response.ok) {
    const message =
      typeof body === "object" && body && "msg" in body
        ? String((body as { msg: unknown }).msg).split("\n")[0]
        : "No provider details recorded";
    report.operations.push({
      operation,
      httpStatus: response.status,
      error: message.replaceAll(token!, "[redacted]"),
    });
    await persist();
    throw new Error(
      `Zetaris ${operation} failed (${response.status}); inspect the private sanitized report`,
    );
  }
  const records = parseZetarisResult(body);
  report.operations.push({
    operation,
    httpStatus: response.status,
    rows: records,
  });
  await persist();
  return records;
};
const name = (row: Record<string, unknown>) =>
  String(row.name ?? row.Name ?? Object.values(row)[0]);
const run = promisify(execFile);
try {
  const pgSources = await query(
    "SHOW DATASOURCES",
    "verify-existing-erp-source",
  );
  if (!pgSources.some((row) => name(row).toUpperCase() === "FINTRACE"))
    throw new Error(
      "Connect the dedicated existing FINTRACE PostgreSQL source first",
    );
  const policyProbe = await fetch(policyProbeUrl, {
    signal: AbortSignal.timeout(5000),
  });
  const policyData = (await policyProbe.json()) as { data?: unknown[] };
  if (!policyProbe.ok || policyData.data?.length !== 8)
    throw new Error("Start the synthetic policy API with eight rows first");
  if (!state.bankFile) {
    let exists = false;
    try {
      await run("docker", ["exec", driver, "test", "-e", bankPath]);
      exists = true;
    } catch {
      /* Expected on a fresh owned path. */
    }
    if (exists)
      throw new Error(
        "Existing bank file has no ownership receipt; refusing to replace it",
      );
    await run("docker", [
      "exec",
      driver,
      "mkdir",
      "-p",
      bankPath.slice(0, bankPath.lastIndexOf("/")),
    ]);
    await run("docker", [
      "cp",
      join(assets, "bank_settlements.csv"),
      `${driver}:${bankPath}`,
    ]);
    state.bankFile = true;
    await persist();
  }
  await run("docker", ["exec", driver, "test", "-r", bankPath]);
  for (const [database, sql] of Object.entries(sourceSql)) {
    const databases = await query(
      "SHOW LIGHTNING DATABASES",
      `inspect-${database}`,
    );
    let existing = databases.find(
      (row) => name(row).toUpperCase() === database,
    );
    if (existing) {
      if (state.databases[database]?.id !== String(existing.id))
        throw new Error(
          `Existing ${database} is not owned by this setup receipt`,
        );
    } else {
      await query(sql[0], `create-${database}`);
      existing = (
        await query("SHOW LIGHTNING DATABASES", `confirm-${database}`)
      ).find((row) => name(row).toUpperCase() === database);
      if (!existing) throw new Error(`Cannot confirm ${database}`);
      state.databases[database] = { id: String(existing.id), tables: [] };
      await persist();
    }
    const table =
      database === "FINTRACE_BANK" ? "bank_settlements" : "vendor_policy";
    const tables = await query(
      `SHOW LIGHTNING TABLES ${database}`,
      `inspect-${database}-tables`,
    );
    if (tables.some((row) => name(row).toLowerCase() === table)) {
      if (!state.databases[database].tables.includes(table))
        throw new Error(`Existing ${database}.${table} is not owned`);
    } else {
      await query(sql[1], `register-${database}-${table}`);
      state.databases[database].tables.push(table);
      await persist();
    }
    await query(
      `DESCRIBE DATASOURCE TABLE ${database}.${table}`,
      `describe-${database}-${table}`,
    );
    await query(
      `SELECT * FROM ${database}.${table} LIMIT 2`,
      `sample-${database}-${table}`,
    );
  }
  await query(
    "CREATE NAMESPACE IF NOT EXISTS lightning.metastore",
    "ensure-parent-metastore",
  );
  const namespaces = await query(
    "SHOW NAMESPACES OR TABLES IN lightning.metastore",
    "inspect-scoring-namespace",
  );
  if (namespaces.some((row) => name(row) === "fintrace_scoring")) {
    if (!state.namespace)
      throw new Error("Existing scoring namespace has no ownership receipt");
  } else {
    await query(
      `CREATE NAMESPACE IF NOT EXISTS ${namespace}`,
      "create-scoring-namespace",
    );
    state.namespace = true;
    await persist();
  }
  let existingModel = (
    await query(`SHOW NAMESPACES OR TABLES IN ${namespace}`, "inspect-model")
  ).find((row) => name(row) === model);
  if (existingModel) {
    if (!state.modelId || state.modelId !== String(existingModel.usl_id))
      throw new Error("Existing scoring USL has no matching ownership receipt");
  } else {
    await query(compile, "compile-deploy-usl");
    existingModel = (
      await query(`SHOW NAMESPACES OR TABLES IN ${namespace}`, "confirm-model")
    ).find((row) => name(row) === model);
    if (!existingModel) throw new Error("Deployed USL not found");
    state.modelId = String(existingModel.usl_id);
    await persist();
  }
  for (const [table, sql] of Object.entries(activation)) {
    if (!state.activated.includes(table)) {
      await query(sql, `activate-${table}`);
      state.activated.push(table);
      await persist();
    }
    const count = await query(
      `SELECT COUNT(*) AS row_count FROM ${usl}.${table}`,
      `count-${table}`,
    );
    const expected =
      table === "payments" ? 9 : table === "vendor_policy" ? 8 : 7;
    if (Number(count[0]?.row_count) !== expected)
      throw new Error(
        `Unexpected ${table} row count; do not use a truncated or fanout source`,
      );
  }
  report.modelDefinition = await query(
    `LOAD USL ${model} NAMESPACE ${namespace}`,
    "load-usl-definition",
  );
  for (const rule of rules) {
    const existingRules = await query(
      `LIST DQ USL ${usl}`,
      `inspect-rule-${rule.name}`,
    );
    if (
      existingRules.some(
        (row) => name(row) === rule.name || Object.values(row)[0] === rule.name,
      )
    ) {
      if (!state.rules.includes(rule.name))
        throw new Error(`Existing rule ${rule.name} has no ownership receipt`);
    } else {
      await query(
        `REGISTER DQ ${rule.name} TABLE ${usl}.${rule.table} AS ${rule.expression}`,
        `register-rule-${rule.name}`,
      );
      state.rules.push(rule.name);
      await persist();
    }
    await query(
      `RUN DQ ${rule.name} TABLE ${usl}.${rule.table}`,
      `run-rule-${rule.name}`,
    );
    await query(
      `SHOW DQ INVALID RECORD ${rule.name} TABLE ${usl}.${rule.table}`,
      `invalid-records-${rule.name}`,
    );
  }
  report.rules = await query(
    `LIST DQ USL ${usl}`,
    "list-all-usl-quality-rules",
  );
  report.completedAt = new Date().toISOString();
  report.success = true;
  await persist();
  await mkdir(join(assets, "evidence"), { recursive: true });
  await writeFile(publicReport, JSON.stringify(report, null, 2) + "\n");
  console.log(
    JSON.stringify({
      success: true,
      namespace,
      model,
      modelId: state.modelId,
      tables: state.activated,
      rules: state.rules,
      report: "data/zetaris-scoring/evidence/setup-result.json",
      noModelCalls: true,
    }),
  );
} catch (error) {
  report.failure = error instanceof Error ? error.message : "Setup failed";
  await persist();
  throw error;
}
