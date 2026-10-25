import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { TABLES, type Row } from "../packages/contracts/src/index.ts";
import {
  packageToCsv,
  parseCsvPackage,
  type DatasetPackage,
} from "../packages/data/src/index.ts";
import { createApp } from "../apps/api/src/server.ts";

const root = "data/fresh-manual";
const tables: Record<string, Row[]> = Object.fromEntries(
  TABLES.map((table) => [table, []]),
);
const asOf = "2026-10-22T23:59:59Z";
const source = "Synthetic-Manual-Test";
const cases = [
  {
    code: "NORMAL",
    vendor: "Synthetic Cedar Supplies",
    amount: "600.00",
    outcome: "no_anomaly_supported",
    category: "NO_FAILURE",
  },
  {
    code: "DUP",
    vendor: "Synthetic Maple Components",
    amount: "1000.00",
    outcome: "anomaly_supported",
    category: "F06",
  },
  {
    code: "MISSING",
    vendor: "Synthetic Pine Logistics",
    amount: "800.00",
    outcome: "anomaly_supported",
    category: "F12",
  },
  {
    code: "FEE",
    vendor: "Synthetic Birch Services",
    amount: "1200.00",
    outcome: "anomaly_supported",
    category: "F14",
  },
];

for (const item of cases) {
  const vendorId = `VND_NEW_${item.code}`;
  const invoiceId = `INV_NEW_${item.code}`;
  const account = `SYNTHETIC_ACCOUNT_${item.code}`;
  tables.vendors.push({
    vendor_id: vendorId,
    vendor_name: item.vendor,
    vendor_type: "supplier",
    tax_id_hash: `synthetic_${item.code.toLowerCase()}`,
    country: "US",
    currency: "USD",
    payment_terms: "NET30",
    default_payment_method: "wire",
    bank_account_token: account,
    bank_routing_token: "SYNTHETIC_ROUTING",
    vendor_status: "active",
    created_at: "2026-08-01T09:00:00Z",
    updated_at: "2026-08-01T09:00:00Z",
    source_system: source,
  });
  tables.invoices.push({
    invoice_id: invoiceId,
    vendor_id: vendorId,
    po_id: `PO_NEW_${item.code}`,
    invoice_number: `NEW-2026-${item.code}`,
    invoice_date: "2026-08-15",
    received_date: "2026-08-15",
    due_date: "2026-09-14",
    currency: "USD",
    subtotal: item.amount,
    tax: "0.00",
    shipping: "0.00",
    invoice_total: item.amount,
    payment_terms: "NET30",
    status: "paid",
    duplicate_reference: "",
    created_at: "2026-08-15T09:00:00Z",
    source_system: source,
  });
  let bankTotal = 0;
  for (let index = 1; index <= (item.code === "DUP" ? 2 : 1); index++) {
    const paymentId = `PAY_NEW_${item.code}_${String(index).padStart(2, "0")}`;
    const date = index === 2 ? "2026-09-10" : "2026-09-07";
    const reference = `REF_NEW_${item.code}_${index}`;
    const bankId = `BT_NEW_${item.code}_${index}`;
    tables.payments.push({
      payment_id: paymentId,
      vendor_id: vendorId,
      payment_date: date,
      payment_method: "wire",
      payment_currency: "USD",
      payment_amount: item.amount,
      bank_account_id: account,
      payment_status: "completed",
      settlement_status: item.code === "MISSING" ? "pending" : "settled",
      reference_number: reference,
      created_at: `${date}T09:00:00Z`,
      source_system: source,
    });
    tables.payment_allocations.push({
      payment_id: paymentId,
      invoice_id: invoiceId,
      allocated_amount: item.amount,
      allocation_date: date,
      source_system: source,
    });
    for (const [side, glAccount] of [
      ["debit", "200000-ACCOUNTS-PAYABLE"],
      ["credit", "100000-CASH"],
    ]) {
      tables.gl_entries.push({
        journal_id: `JE_NEW_${item.code}_${index}`,
        journal_line_id: `JEL_NEW_${item.code}_${index}_${side}`,
        transaction_type: "payment",
        source_transaction_id: paymentId,
        posting_date: date,
        accounting_period: "2026-09",
        gl_account: glAccount,
        debit: side === "debit" ? item.amount : "0.00",
        credit: side === "credit" ? item.amount : "0.00",
        currency: "USD",
        department: "Operations",
        cost_center: "TEST",
        memo: "Synthetic payment journal",
        source_system: source,
      });
    }
    if (item.code !== "MISSING") {
      const settledAmount = item.code === "FEE" ? "1180.00" : item.amount;
      bankTotal += Number(settledAmount);
      tables.bank_transactions.push({
        bank_transaction_id: bankId,
        bank_account_id: account,
        transaction_date: date,
        posted_date: date,
        transaction_type: "payment",
        amount: settledAmount,
        currency: "USD",
        direction: "debit",
        bank_reference: `BANK_REF_${item.code}_${index}`,
        counterparty_token: account,
        payment_reference: reference,
        status: "posted",
        source_system: source,
      });
    }
    if (["MISSING", "FEE"].includes(item.code)) {
      tables.audit_log.push({
        event_id: `EVT_NEW_${item.code}`,
        entity_type: "payment",
        entity_id: paymentId,
        event_type:
          item.code === "MISSING"
            ? "payment_file_not_transmitted"
            : "net_settlement_received",
        timestamp: `${date}T10:00:00Z`,
        actor_id: "synthetic_processor",
        field: "settlement_status",
        old_value: "submitted",
        new_value:
          item.code === "MISSING" ? "transmission_failed" : "net_1180_fee_20",
        source_system: source,
      });
    }
  }
  tables.bank_statements.push({
    bank_statement_id: `BS_NEW_${item.code}`,
    bank_account_id: account,
    statement_date: "2026-10-22",
    opening_balance: "10000.00",
    closing_balance: (10000 - bankTotal).toFixed(2),
    total_debits: bankTotal.toFixed(2),
    total_credits: "0.00",
    source_system: source,
  });
}

const packet: DatasetPackage = {
  manifest: {
    name: "Fresh manual test - 2026-10-22",
    asOf,
    clearingDays: 10,
    currency: "USD",
    coverage: Object.fromEntries(
      TABLES.map((table) => [
        table,
        { status: "complete" as const, from: "2026-08-01T00:00:00Z", to: asOf },
      ]),
    ),
    focusPaymentIds: cases.map(
      (item) => `PAY_NEW_${item.code}_${item.code === "DUP" ? "02" : "01"}`,
    ),
  },
  tables,
};
const bundle = packageToCsv(packet);
parseCsvPackage(bundle);
await mkdir(join(root, "csv"), { recursive: true });
await writeFile(
  join(root, "fresh-test-bundle.json"),
  JSON.stringify(bundle, null, 2) + "\n",
);
await writeFile(
  join(root, "csv", "manifest.json"),
  JSON.stringify(bundle.manifest, null, 2) + "\n",
);
for (const [name, text] of Object.entries(bundle.files))
  await writeFile(join(root, "csv", name), text);

await mkdir(".local", { recursive: true });
const storageDir = await mkdtemp(
  join(process.cwd(), ".local", "fresh-validation-"),
);
const { app, service } = await createApp({
  mode: "fixture",
  storageDir,
  seed: false,
});
const results = [];
try {
  const imported = await app.inject({
    method: "POST",
    url: "/api/datasets",
    payload: bundle,
  });
  if (imported.statusCode !== 201)
    throw new Error(`Import failed: ${imported.body}`);
  const datasetId = imported.json().dataset.id as string;
  const queued = (await app.inject(`/api/cases?datasetId=${datasetId}`)).json()
    .cases;
  if (queued.length !== 4)
    throw new Error("Expected exactly four visible cases");
  for (const item of cases) {
    const paymentId = `PAY_NEW_${item.code}_${item.code === "DUP" ? "02" : "01"}`;
    const started = await app.inject({
      method: "POST",
      url: "/api/investigations",
      payload: { datasetId, paymentId },
    });
    if (started.statusCode !== 202)
      throw new Error(`Could not start ${paymentId}`);
    const run = await service.wait(started.json().id);
    const passed =
      run.status === "completed" &&
      run.outcome === item.outcome &&
      run.findings.some((finding) => finding.category === item.category);
    results.push({
      paymentId,
      status: run.status,
      outcome: run.outcome,
      categories: run.findings.map((finding) => finding.category),
      passed,
    });
    if (!passed)
      throw new Error(
        `Unexpected outcome for ${paymentId}: ${JSON.stringify(results.at(-1))}`,
      );
  }
  const report = {
    verifiedAt: new Date().toISOString(),
    mode: "fixture",
    modelCalls: 0,
    importStatus: 201,
    visibleCases: queued.length,
    results,
    notice:
      "Offline verification only; no real model or external financial service was called. No dataset was imported into the user's application.",
  };
  await writeFile(
    join(root, "validation.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log(JSON.stringify(report, null, 2));
} finally {
  await app.close();
}
