import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildManualPackets } from "./prepare_openai_manual.ts";
import { packageToCsv, parseCsvPackage } from "../packages/data/src/index.ts";
import { PostgresStore } from "../apps/api/src/store.ts";
import type { Row } from "../packages/contracts/src/index.ts";

const root = fileURLToPath(new URL("../", import.meta.url));
const directory = resolve(root, "data/zetaris-scoring");
const bindingPath = resolve(
  root,
  ".local/zetaris-runtime/scoring-binding.json",
);
const digest = (text: string) =>
  createHash("sha256").update(text).digest("hex");
const json = (value: unknown) => JSON.stringify(value, null, 2) + "\n";

export function buildScoringSources() {
  const packet = buildManualPackets().main;
  packet.manifest.name = "FinTrace USL scoring synthetic sample";
  parseCsvPackage(packageToCsv(packet));
  const focus = new Set([
    ...packet.manifest.focusPaymentIds!,
    "PAY_DEMO_DUP_OTHER",
  ]);
  const payments = packet.tables.payments.filter((row) =>
    focus.has(row.payment_id),
  );
  const references = new Set(payments.map((row) => row.reference_number));
  const bank: Row[] = packet.tables.bank_transactions
    .filter((row) => references.has(row.payment_reference))
    .map((row) => ({ ...row, source_system: "FinTrace-Synthetic-BankFeed" }));
  const vendorIds = [...new Set(payments.map((row) => row.vendor_id))];
  const policies = vendorIds.map((vendorId, index) => ({
    vendor_id: vendorId,
    policy_id: `SYNTHETIC-CTRL-${String(index + 1).padStart(3, "0")}`,
    policy_version: "2026-08-01",
    currency: "USD",
    max_unreviewed_payment: "1000.00",
    variance_review_threshold: "25.00",
    settlement_grace_days: 10,
    bank_change_review_required: true,
    effective_from: "2026-08-01",
    effective_to: "2026-12-31",
    source_system: "FinTrace-Synthetic-VendorControls",
  }));
  const unique = (values: string[]) =>
    values.every((value) => value.trim()) &&
    new Set(values).size === values.length;
  if (
    payments.length !== 9 ||
    bank.length !== 7 ||
    policies.length !== 8 ||
    !unique(payments.map((row) => row.payment_id)) ||
    !unique(bank.map((row) => row.bank_transaction_id)) ||
    !unique(bank.map((row) => `${row.payment_reference}:${row.currency}`)) ||
    !unique(policies.map((row) => row.vendor_id)) ||
    bank.some((row) => !references.has(row.payment_reference))
  )
    throw new Error("Scoring source grain, row count or relationship changed");

  const bankColumns = [
    "bank_transaction_id",
    "payment_reference",
    "transaction_date",
    "posted_date",
    "transaction_type",
    "amount",
    "currency",
    "direction",
    "status",
    "source_system",
  ];
  const cell = (value: string) =>
    /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
  const bankCsv =
    [
      bankColumns.join(","),
      ...bank.map((row) => bankColumns.map((key) => cell(row[key])).join(",")),
    ].join("\r\n") + "\r\n";
  const policyJson = json(policies);
  const previewColumns = [
    "payment_id",
    "vendor_id",
    "payment_date",
    "payment_currency",
    "payment_amount",
    "payment_status",
    "settlement_status",
    "reference_number",
  ];
  const erpPreviewCsv =
    [
      previewColumns.join(","),
      ...payments.map((row) =>
        previewColumns.map((key) => cell(row[key])).join(","),
      ),
    ].join("\r\n") + "\r\n";
  const datasetVersion = digest(JSON.stringify(packet));
  const expectedDatasetId = `ds-${datasetVersion.slice(0, 16)}`;
  const manifest = {
    syntheticDataOnly: true,
    generator: {
      path: "scripts/prepare_openai_manual.ts",
      export: "buildManualPackets().main",
    },
    datasetName: packet.manifest.name,
    expectedDatasetId,
    datasetVersion,
    cutoff: packet.manifest.asOf,
    rowCounts: {
      erp_payments: payments.length,
      bank_settlements: bank.length,
      vendor_policy: policies.length,
    },
    paymentIds: payments.map((row) => row.payment_id),
    vendorIds,
    sources: [
      {
        role: "ERP payment facts",
        transport: "PostgreSQL connector",
        grain: "dataset_id + payment_id",
        origin:
          "Full immutable synthetic manual packet saved as a separate scoring dataset; USL selects only the nine listed payments.",
      },
      {
        role: "Bank settlement feed",
        transport: "CSV file connector",
        path: "bank_settlements.csv",
        grain: "bank_transaction_id",
        origin:
          "Bank-domain projection from the same synthetic scenario generator. Simulates a separately delivered bank feed; not independent real-world evidence or a copy of the ERP payment table. USL reads the file source, not FINTRACE.bank_transactions.",
      },
      {
        role: "Supplier control policy",
        transport: "Read-only local HTTP API",
        path: "vendor_policy.json",
        endpointPath: "/vendor-policy",
        envelope: "{data: policies}",
        grain: "One active policy per vendor_id/currency/effective interval",
        origin:
          "New synthetic operational policies. Uniform thresholds are declared demonstration assumptions, not evaluation labels. A local server simulates a supplier-control system; no external supplier is contacted.",
      },
    ],
    joins: [
      {
        left: "ERP.reference_number + ERP.payment_currency",
        right: "bank.payment_reference + bank.currency",
        shape:
          "LEFT JOIN; at most one bank row per reference/currency in this sample",
        warning:
          "Missing bank observations remain NULL. A returned transaction is not a posted settlement.",
      },
      {
        left: "ERP.vendor_id + ERP.payment_currency + ERP.payment_date",
        right:
          "policy.vendor_id + policy.currency + effective_from/effective_to",
        shape:
          "LEFT JOIN to the effective policy; one interval per vendor in this sample",
      },
    ],
    files: {
      "erp_payments_preview.csv": {
        sha256: digest(erpPreviewCsv),
        bytes: Buffer.byteLength(erpPreviewCsv),
        purpose:
          "Inspection fixture only; not registered as an additional source or read by the USL",
      },
      "bank_settlements.csv": {
        sha256: digest(bankCsv),
        bytes: Buffer.byteLength(bankCsv),
      },
      "vendor_policy.json": {
        sha256: digest(policyJson),
        bytes: Buffer.byteLength(policyJson),
      },
    },
    notEvidenceOf: [
      "Independent enterprise systems or real customer data",
      "Held-out model accuracy",
      "Proof that an observed amount difference is a bank fee",
    ],
  };
  const dictionary = {
    scope:
      "Synthetic FinTrace three-source scoring demonstration; no real customer data",
    erp_payments: {
      grain: "dataset_id + payment_id",
      row_count: 9,
      columns: {
        payment_id: "Required unique payment identifier within dataset",
        vendor_id: "Required vendor/policy join key",
        payment_date: "ISO date used for the effective-policy join",
        payment_currency:
          "ISO currency code; monetary joins must match currency",
        payment_amount: "Decimal string; cast DECIMAL(18,2) for arithmetic",
        payment_status: "ERP operational status",
        settlement_status:
          "ERP reported status, distinct from bank observation",
        reference_number: "Required bank-reference join key",
      },
    },
    bank_settlements: {
      grain: "bank_transaction_id",
      row_count: 7,
      columns: {
        bank_transaction_id: "Required unique transaction identifier",
        payment_reference:
          "Required ERP reference join key; unique per currency only in this sample",
        transaction_date: "ISO date",
        posted_date: "ISO date; respect observation cutoff",
        transaction_type: "payment in this sample",
        amount: "Positive decimal string; direction is separate",
        currency: "ISO currency code",
        direction: "debit in this sample",
        status:
          "posted or returned; returned does not count as posted settlement",
        source_system: "FinTrace-Synthetic-BankFeed simulation label",
      },
    },
    vendor_policy: {
      grain: "One active vendor/currency/effective interval",
      row_count: 8,
      columns: {
        vendor_id: "Required policy join key",
        policy_id: "Required unique policy identifier",
        policy_version: "ISO date/version marker",
        currency: "ISO currency code for threshold amounts",
        max_unreviewed_payment:
          "Decimal string; 1000.00 demonstration review threshold",
        variance_review_threshold:
          "Decimal string; 25.00 demonstration threshold, not evidence that a difference is a fee",
        settlement_grace_days:
          "Integer 10; illustrative calendar-day parameter",
        bank_change_review_required: "Boolean true; demonstration procedure",
        effective_from: "Inclusive ISO date start",
        effective_to: "Inclusive ISO date end",
        source_system: "FinTrace-Synthetic-VendorControls simulation label",
      },
    },
    quality_expectations: [
      "Required identifiers must be present and unique at their declared grain.",
      "Bank payment_reference and currency must be present for a safe join.",
      "Keep absent bank rows NULL; do not silently substitute amount zero.",
      "Avoid overlapping effective policies and aggregate one-to-many bank feeds before joining.",
      "Include currency in monetary joins and aggregation groups.",
    ],
    publication_caveat:
      "Three separately connected simulated business feeds, not three independent real enterprise systems. Bank and ERP mock records share a scenario generator.",
  };
  return {
    packet,
    expectedDatasetId,
    manifest,
    assets: {
      "erp_payments_preview.csv": erpPreviewCsv,
      "bank_settlements.csv": bankCsv,
      "vendor_policy.json": policyJson,
      "source-manifest.json": json(manifest),
      "data-dictionary.json": json(dictionary),
    },
  };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.some((arg) => !["--connect", "--check"].includes(arg)))
    throw new Error("Usage: prepare_zetaris_scoring.ts [--check] [--connect]");
  const { packet, expectedDatasetId, manifest, assets } = buildScoringSources();
  await mkdir(directory, { recursive: true });
  for (const [name, content] of Object.entries(assets)) {
    const path = resolve(directory, name);
    if (args.includes("--check")) {
      if ((await readFile(path, "utf8")) !== content)
        throw new Error(`Scoring asset differs from its generator: ${name}`);
    } else await writeFile(path, content);
  }
  let datasetId: string | null = null;
  if (args.includes("--connect")) {
    if (!process.env.DATABASE_URL?.trim())
      throw new Error(
        "--connect requires DATABASE_URL in the private environment",
      );
    const store = new PostgresStore(process.env.DATABASE_URL);
    try {
      await store.init();
      const stored = await store.saveDataset(packet);
      if (stored.info.id !== expectedDatasetId)
        throw new Error(
          "Imported scoring snapshot does not match its expected ID",
        );
      datasetId = stored.info.id;
      await mkdir(resolve(root, ".local/zetaris-runtime"), { recursive: true });
      await writeFile(
        bindingPath,
        json({
          preparedAt: new Date().toISOString(),
          syntheticDataOnly: true,
          datasetId,
          datasetVersion: stored.info.version,
          datasetName: stored.info.name,
          focusPaymentIds: manifest.paymentIds,
          cutoff: stored.info.asOf,
          sourceManifest: "data/zetaris-scoring/source-manifest.json",
          bankCsv: "data/zetaris-scoring/bank_settlements.csv",
          policyJson: "data/zetaris-scoring/vendor_policy.json",
        }),
        { mode: 0o600 },
      );
    } finally {
      await store.close();
    }
  }
  console.log(
    JSON.stringify({
      syntheticDataOnly: true,
      assets: "data/zetaris-scoring",
      checked: args.includes("--check"),
      connected: !!datasetId,
      datasetId,
      expectedDatasetId,
      rowCounts: manifest.rowCounts,
      ...(datasetId
        ? { binding: ".local/zetaris-runtime/scoring-binding.json" }
        : {}),
    }),
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
)
  await main();
