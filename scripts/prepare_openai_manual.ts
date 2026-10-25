import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import schema from "../packages/data/src/schema.json";
import {
  TABLES,
  type Row,
  type TableName,
} from "../packages/contracts/src/index.ts";
import {
  packageToCsv,
  parseCsvPackage,
  type DatasetPackage,
} from "../packages/data/src/index.ts";
import { createApp } from "../apps/api/src/server.ts";

export const manualCases = [
  {
    code: "NORMAL",
    amount: "600.00",
    outcome: "no_anomaly_supported",
    category: "NO_FAILURE",
  },
  {
    code: "DUP",
    amount: "1000.00",
    outcome: "anomaly_supported",
    category: "F06",
  },
  {
    code: "STALE",
    amount: "900.00",
    outcome: "anomaly_supported",
    category: "F11",
  },
  {
    code: "MISSING",
    amount: "800.00",
    outcome: "anomaly_supported",
    category: "F12",
  },
  {
    code: "FEE",
    amount: "1200.00",
    outcome: "anomaly_supported",
    category: "F14",
  },
  {
    code: "FUTURE_EVENT",
    amount: "700.00",
    outcome: "insufficient_evidence",
    category: "EVIDENCE_GAP",
  },
  {
    code: "FUTURE_FEE",
    amount: "1200.00",
    outcome: "anomaly_supported",
    category: "F14",
  },
  {
    code: "CONTEXT_TAIL",
    amount: "350.00",
    outcome: "no_anomaly_supported",
    category: "NO_FAILURE",
  },
] as const;

export function buildManualPackets() {
  const tables: Record<string, Row[]> = Object.fromEntries(
    TABLES.map((t) => [t, []]),
  );
  const add = (table: TableName, values: Row) => {
    const row = Object.fromEntries(
      schema[table].columns.map((column) => [
        column,
        (schema[table].money as readonly string[]).includes(column)
          ? "0.00"
          : "",
      ]),
    );
    Object.assign(row, { source_system: "FinTrace-Synthetic-Manual" }, values);
    tables[table].push(row);
    return row;
  };
  const journal = (
    code: string,
    paymentId: string,
    amount: string,
    type = "payment",
    date = "2026-09-07",
  ) => {
    for (const side of ["debit", "credit"])
      add("gl_entries", {
        journal_id: `JE_${code}`,
        journal_line_id: `JEL_${code}_${side}`,
        transaction_type: type,
        source_transaction_id: paymentId,
        posting_date: date,
        accounting_period: date.slice(0, 7),
        gl_account: side === "debit" ? "200000" : "100000",
        debit: side === "debit" ? amount : "0.00",
        credit: side === "credit" ? amount : "0.00",
        currency: "USD",
      });
  };
  const makeCase = (code: string, amount: string) => {
    const vendor = `VND_DEMO_${code}`,
      invoice = `INV_DEMO_${code}`;
    const account = `SYNTHETIC_ACCOUNT_${code}`;
    add("vendors", {
      vendor_id: vendor,
      vendor_name: `Synthetic ${code} Supplier`,
      vendor_type: "supplier",
      country: "US",
      currency: "USD",
      bank_account_token: code === "STALE" ? `${account}_NEW` : account,
      created_at: "2026-08-01T09:00:00Z",
      updated_at:
        code === "STALE" ? "2026-08-25T09:00:00Z" : "2026-08-01T09:00:00Z",
    });
    add("invoices", {
      invoice_id: invoice,
      vendor_id: vendor,
      invoice_number: `DEMO-${code}`,
      invoice_date: "2026-08-15",
      received_date: "2026-08-15",
      due_date: "2026-09-14",
      currency: "USD",
      subtotal: amount,
      invoice_total: amount,
      status: "paid",
      created_at: "2026-08-15T09:00:00Z",
    });
    const missing = code === "MISSING" || code === "FUTURE_EVENT";
    const fee = code === "FEE" || code === "FUTURE_FEE";
    if (code === "STALE")
      add("vendor_change_log", {
        change_id: "CHANGE_DEMO_STALE",
        vendor_id: vendor,
        field_changed: "bank_account_token",
        old_value: account,
        new_value: `${account}_NEW`,
        changed_at: "2026-08-25T09:00:00Z",
      });
    for (const suffix of code === "DUP" ? ["_OTHER", ""] : [""]) {
      const paymentId = `PAY_DEMO_${code}${suffix}`;
      const reference = `REF_${code}${suffix}`;
      add("payments", {
        payment_id: paymentId,
        vendor_id: vendor,
        payment_date: "2026-09-07",
        payment_method: "wire",
        payment_currency: "USD",
        payment_amount: amount,
        bank_account_id: account,
        payment_status: "completed",
        settlement_status: missing ? "pending" : "settled",
        reference_number: reference,
        created_at: "2026-09-07T09:00:00Z",
      });
      add("payment_allocations", {
        payment_id: paymentId,
        invoice_id: invoice,
        allocated_amount: amount,
        allocation_date: "2026-09-07",
      });
      journal(`${code}${suffix}`, paymentId, amount);
      if (!missing)
        add("bank_transactions", {
          bank_transaction_id: `BT_${code}${suffix}`,
          bank_account_id: account,
          transaction_date: "2026-09-07",
          posted_date: "2026-09-07",
          transaction_type: "payment",
          amount: fee ? "1180.00" : amount,
          currency: "USD",
          direction: "debit",
          counterparty_token: account,
          payment_reference: reference,
          status: code === "STALE" ? "returned" : "posted",
        });
      if (missing || fee || code === "STALE")
        add("audit_log", {
          event_id: `EVT_${code}`,
          entity_type: "payment",
          entity_id: paymentId,
          event_type: missing
            ? "payment_file_not_transmitted"
            : fee
              ? "net_settlement_received"
              : "processor_return_received",
          timestamp:
            code === "FUTURE_EVENT"
              ? "2026-11-01T10:00:00Z"
              : "2026-09-07T10:00:00Z",
        });
      if (code === "FUTURE_FEE")
        journal(
          "FUTURE_FEE_ADJUSTMENT",
          paymentId,
          "20.00",
          "bank_fee",
          "2026-11-01",
        );
    }
  };
  // Deliberately put unrelated records first; none are visible in the case inbox.
  for (let i = 0; i < 120; i++)
    makeCase(`BACKGROUND_${String(i).padStart(3, "0")}`, "10.00");
  for (const item of manualCases) makeCase(item.code, item.amount);
  const asOf = "2026-10-22T23:59:59Z";
  const main: DatasetPackage = {
    manifest: {
      name: "FinTrace OpenAI manual - 8 cases",
      asOf,
      clearingDays: 10,
      currency: "USD",
      focusPaymentIds: manualCases.map((c) => `PAY_DEMO_${c.code}`),
      coverage: Object.fromEntries(
        TABLES.map((t) => [
          t,
          {
            status: "complete" as const,
            from: "2026-08-01T00:00:00Z",
            to: asOf,
          },
        ]),
      ),
    },
    tables,
  };
  const partial = structuredClone(main);
  partial.manifest.name = "FinTrace OpenAI manual - partial coverage";
  partial.manifest.focusPaymentIds = ["PAY_DEMO_NORMAL"];
  partial.manifest.coverage.bank_transactions.status = "partial";
  const revised = structuredClone(main);
  revised.manifest.clearingDays = 11;
  const invalid = packageToCsv(main);
  delete invalid.files["payments.csv"];
  return { main, partial, revised, invalid };
}

async function prepare() {
  const root = resolve("data/openai-manual");
  const packets = buildManualPackets();
  await mkdir(root, { recursive: true });
  for (const [file, packet] of [
    ["01-main-bundle.json", packets.main],
    ["02-partial-coverage.json", packets.partial],
    ["04-revised-bundle.json", packets.revised],
  ] as const) {
    const bundle = packageToCsv(packet);
    parseCsvPackage(bundle);
    await writeFile(join(root, file), JSON.stringify(bundle, null, 2) + "\n");
  }
  await writeFile(
    join(root, "03-invalid-missing-payments.json"),
    JSON.stringify(packets.invalid, null, 2) + "\n",
  );
  const results: unknown[] = [];
  const originalFetch = globalThis.fetch;
  let mockCalls = 0;
  globalThis.fetch = async (_url, options) => {
    mockCalls++;
    const body = JSON.parse(String(options?.body));
    const input = JSON.parse(body.messages[1].content);
    const tool = input.context.availableTools[0];
    return new Response(
      JSON.stringify({
        model: "mock-openai",
        choices: [
          {
            message: {
              content: JSON.stringify({
                tool,
                reason: "Retrieve the next missing source.",
                finish: false,
              }),
            },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 },
      }),
      {
        headers: {
          "Content-Type": "application/json",
          "x-request-id": `mock-manual-${mockCalls}`,
        },
      },
    );
  };
  const envBefore = {
    provider: process.env.MODEL_PROVIDER,
    key: process.env.OPENAI_API_KEY,
    model: process.env.OPENAI_MODEL,
  };
  process.env.MODEL_PROVIDER = "openai";
  process.env.OPENAI_API_KEY = "mock-only-no-network";
  process.env.OPENAI_MODEL = "mock-openai";
  try {
    for (const mode of ["fixture", "local-model"] as const) {
      await mkdir(".local", { recursive: true });
      const storageDir = await mkdtemp(
        resolve(".local/openai-manual-validation-"),
      );
      const { app, service } = await createApp({
        mode,
        storageDir,
        seed: false,
      });
      try {
        const imported = await app.inject({
          method: "POST",
          url: "/api/datasets",
          payload: packageToCsv(packets.main),
        });
        if (imported.statusCode !== 201) throw new Error("Main import failed");
        const id = imported.json().dataset.id;
        const cases = (await app.inject(`/api/cases?datasetId=${id}`)).json()
          .cases;
        if (cases.length !== 8) throw new Error("Expected eight visible cases");
        for (const item of manualCases) {
          const run = await service.wait(
            (await service.start(id, `PAY_DEMO_${item.code}`)).id,
          );
          if (
            run.status !== "completed" ||
            run.outcome !== item.outcome ||
            !run.findings.some((f) => f.category === item.category)
          )
            throw new Error(
              `Unexpected ${mode} result for ${item.code}: ${run.outcome} ${run.error || ""}`,
            );
          results.push({
            mode: mode === "fixture" ? "fixture" : "mocked-openai",
            paymentId: run.paymentId,
            status: run.status,
            outcome: run.outcome,
            categories: run.findings.map((f) => f.category),
            modelRequests: run.modelRequests?.length || 0,
          });
        }
        const partial = await app.inject({
          method: "POST",
          url: "/api/datasets",
          payload: packageToCsv(packets.partial),
        });
        const partialRun = await service.wait(
          (await service.start(partial.json().dataset.id, "PAY_DEMO_NORMAL"))
            .id,
        );
        if (partialRun.outcome !== "insufficient_evidence")
          throw new Error("Partial coverage was not withheld");
        const invalid = await app.inject({
          method: "POST",
          url: "/api/datasets",
          payload: packets.invalid,
        });
        if (invalid.statusCode !== 400)
          throw new Error("Invalid package was not rejected");
        const revised = await app.inject({
          method: "POST",
          url: "/api/datasets",
          payload: packageToCsv(packets.revised),
        });
        if (revised.statusCode !== 201 || revised.json().dataset.id === id)
          throw new Error("Revision did not create a new version");
        results.push({
          mode,
          partialCoverage: partialRun.outcome,
          invalidImportStatus: invalid.statusCode,
          revisedVersionCreated: true,
        });
      } finally {
        await app.close();
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
    for (const [key, value] of [
      ["MODEL_PROVIDER", envBefore.provider],
      ["OPENAI_API_KEY", envBefore.key],
      ["OPENAI_MODEL", envBefore.model],
    ]) {
      if (value === undefined) delete process.env[key!];
      else process.env[key!] = value;
    }
  }
  await writeFile(
    join(root, "validation.json"),
    JSON.stringify(
      {
        verifiedAt: new Date().toISOString(),
        realApiCalls: 0,
        mockedHttpAttempts: mockCalls,
        visibleCases: 8,
        results,
        notice:
          "Fixture and mocked OpenAI only. Expected results are outside the import bundles. No real account connectivity was tested; no imports were made into the user workspace.",
      },
      null,
      2,
    ) + "\n",
  );
  console.log(
    JSON.stringify({
      directory: root,
      visibleCases: 8,
      realApiCalls: 0,
      mockedHttpAttempts: mockCalls,
    }),
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
)
  await prepare();
