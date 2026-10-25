import { beforeAll, describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  loadBuiltinDatasets,
  parseCsvPackage,
  packageToCsv,
  type DatasetPackage,
} from "../packages/data/src/index.ts";
import {
  TABLES,
  type EvidenceReference,
} from "../packages/contracts/src/index.ts";
import { FileStore, recordId } from "../apps/api/src/store.ts";
import { assess, TOOL_ORDER, businessDays } from "../apps/api/src/verifier.ts";
import { createApp } from "../apps/api/src/server.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import { createModelProvider } from "../apps/api/src/integrations/model.ts";
import { parseZetarisResult } from "../apps/api/src/integrations/zetaris.ts";
import { exportRun } from "../apps/api/src/export.ts";
import { retrieve } from "../apps/api/src/evidence.ts";
let packets: DatasetPackage[];
beforeAll(async () => {
  packets = await loadBuiltinDatasets();
  await mkdir(".local", { recursive: true });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
async function isolated() {
  const dir = await mkdtemp(join(process.cwd(), ".local", "test-"));
  const store = new FileStore(dir);
  await store.init();
  return { dir, store };
}
async function verify(packet: DatasetPackage) {
  const { store } = await isolated();
  const ds = await store.saveDataset(packet);
  const evidence = TABLES.flatMap((table) =>
    packet.tables[table].map((record, i) => ({
      id: `${table}:${recordId(table, record, i)}`,
      table,
      recordId: recordId(table, record, i),
      queryId: "test-query",
      datasetVersion: ds.info.version,
      record,
    })),
  ) satisfies EvidenceReference[];
  return assess(
    ds.info,
    packet.manifest.focusPaymentIds![0],
    evidence,
    new Set(TOOL_ORDER),
  );
}
describe("dataset contracts", () => {
  it("validates every prepared packet and keeps evaluation labels outside visible data", () => {
    expect(packets).toHaveLength(70);
    for (const p of packets) {
      expect(Object.keys(p.tables).sort()).toEqual([...TABLES].sort());
      expect(JSON.stringify(p)).not.toMatch(
        /rca_ground_truth|expectedOutcome|mutation_log|root_cause_category/,
      );
    }
  });
  it("rejects imprecise money and reports the source row", () => {
    const bundle = packageToCsv(packets[0]);
    bundle.files["payments.csv"] = bundle.files["payments.csv"].replace(
      packets[0].tables.payments[0].payment_amount,
      "12.123",
    );
    expect(() => parseCsvPackage(bundle)).toThrow(
      /payments.csv:2:payment_amount/,
    );
  });
  it("rejects duplicate identifiers and broken allocation links", () => {
    const p = structuredClone(packets[0]);
    p.tables.payments.push(p.tables.payments[0]);
    expect(() => parseCsvPackage(packageToCsv(p))).toThrow(
      /duplicate primary key/,
    );
    const b = structuredClone(packets[0]);
    b.tables.payment_allocations[0].invoice_id = "missing";
    expect(() => parseCsvPackage(packageToCsv(b))).toThrow(
      /missing related payment/,
    );
  });
  it("does not activate an invalid import", async () => {
    const { dir, store } = await isolated();
    const { app } = await createApp({
      mode: "fixture",
      store,
      storageDir: dir,
      seed: false,
    });
    const response = await app.inject({
      method: "POST",
      url: "/api/datasets",
      payload: { manifest: { name: "invalid" }, files: {} },
    });
    expect(response.statusCode).toBe(400);
    expect(await store.datasets()).toHaveLength(0);
    await app.close();
  });
  it("uses immutable dataset versions", async () => {
    const { store } = await isolated();
    const a = await store.saveDataset(packets[0]);
    const b = await store.saveDataset(packets[0]);
    const changed = structuredClone(packets[0]);
    changed.manifest.name += " corrected";
    const c = await store.saveDataset(changed);
    expect(a.info.id).toBe(b.info.id);
    expect(c.info.id).not.toBe(a.info.id);
    expect((await store.dataset(a.info.id))!.data.manifest.name).toBe(
      packets[0].manifest.name,
    );
  });
});
describe("financial verification", () => {
  it("treats a vendor token used before its effective change as historical, not stale", async () => {
    const p = structuredClone(packets[12]);
    const pid = p.manifest.focusPaymentIds![0];
    const payment = p.tables.payments.find((r) => r.payment_id === pid)!;
    payment.settlement_status = "settled";
    for (const b of p.tables.bank_transactions)
      if (b.payment_reference === payment.reference_number) b.status = "posted";
    for (const c of p.tables.vendor_change_log)
      c.changed_at = "2026-07-02T14:00:00";
    p.tables.audit_log = p.tables.audit_log.filter(
      (a) => a.event_type !== "processor_return_received",
    );
    const result = await verify(p);
    expect(result.findings.some((f) => f.category === "F11")).toBe(false);
    expect(result.outcome).toBe("no_anomaly_supported");
  });
  it("accepts a settlement difference with explicit balanced fee accounting", async () => {
    const p = structuredClone(packets[36]);
    const payment = p.tables.payments.find(
      (r) => r.payment_id === p.manifest.focusPaymentIds![0],
    )!;
    const bank = p.tables.bank_transactions.find(
      (b) =>
        b.payment_reference === payment.reference_number &&
        b.transaction_type !== "bank fee",
    )!;
    const fee = (await import("decimal.js")).default;
    const amount = new fee(payment.payment_amount)
      .minus(bank.amount)
      .toFixed(2);
    const base = p.tables.gl_entries[0];
    p.tables.gl_entries.push(
      {
        ...base,
        journal_id: "TEST_FEE",
        journal_line_id: "TEST_FEE_D",
        transaction_type: "bank_fee",
        source_transaction_id: bank.bank_transaction_id,
        debit: amount,
        credit: "0.00",
        currency: payment.payment_currency,
      },
      {
        ...base,
        journal_id: "TEST_FEE",
        journal_line_id: "TEST_FEE_C",
        transaction_type: "bank_fee",
        source_transaction_id: bank.bank_transaction_id,
        debit: "0.00",
        credit: amount,
        currency: payment.payment_currency,
      },
    );
    expect((await verify(p)).outcome).toBe("no_anomaly_supported");
  });
  it("does not treat missing or imbalanced ledger evidence as a normal pass", async () => {
    const p = structuredClone(packets[48]);
    const pid = p.manifest.focusPaymentIds![0];
    p.tables.gl_entries = p.tables.gl_entries.filter(
      (g) => g.source_transaction_id !== pid,
    );
    expect((await verify(p)).outcome).toBe("insufficient_evidence");
  });
  it("supports duplicate payment only with the invoice and disbursement chains", async () => {
    const result = await verify(packets[0]);
    expect(result.outcome).toBe("anomaly_supported");
    expect(result.findings.some((f) => f.category === "F06")).toBe(true);
  });
  it("counts clearing time across weekends", () => {
    expect(businessDays("2026-06-26", "2026-06-29T23:59:59Z")).toBe(1);
  });
  it("withholds a conclusion for partial bank coverage", async () => {
    const p = structuredClone(packets[0]);
    p.manifest.coverage.bank_transactions.status = "partial";
    const r = await verify(p);
    expect(r.outcome).toBe("insufficient_evidence");
    expect(r.actions).toHaveLength(0);
  });
  it("does not infer absence before querying required sources", async () => {
    const { store } = await isolated();
    const ds = await store.saveDataset(packets[0]);
    const result = assess(
      ds.info,
      packets[0].manifest.focusPaymentIds![0],
      [],
      new Set(),
    );
    expect(result.outcome).toBe("insufficient_evidence");
    expect(result.neededTools).toContain("overview");
  });
  it("withholds cross-currency comparisons", async () => {
    const p = structuredClone(packets[36]);
    const pid = p.manifest.focusPaymentIds![0];
    const payment = p.tables.payments.find((x) => x.payment_id === pid)!;
    for (const bank of p.tables.bank_transactions)
      if (bank.payment_reference === payment.reference_number)
        bank.currency = payment.payment_currency === "USD" ? "EUR" : "USD";
    expect((await verify(p)).outcome).toBe("insufficient_evidence");
  });
});
describe("integrations", () => {
  it("rejects a silently incomplete live source snapshot", async () => {
    const { store } = await isolated();
    const ds = await store.saveDataset(packets[0]);
    vi.stubEnv("ZETARIS_BASE_URL", "http://fixture.invalid");
    vi.stubEnv("ZETARIS_ORG_ID", "1");
    vi.stubEnv("ZETARIS_API_KEY", "unit-test-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ headers: [], data: [] }), {
          status: 200,
        }),
      ),
    );
    await expect(
      retrieve(
        "settlements",
        ds,
        packets[0].manifest.focusPaymentIds![0],
        "live",
        new AbortController().signal,
      ),
    ).rejects.toThrow(/does not match the immutable/);
  });
  it("rejects failed or unknown Zetaris responses instead of returning an empty record set", () => {
    expect(() =>
      parseZetarisResult({ error: "query failed", data: [] }),
    ).toThrow();
    expect(() => parseZetarisResult({ message: "unknown" })).toThrow();
    expect(
      parseZetarisResult({ headers: [{ name: "id" }], data: [["one"]] }),
    ).toEqual([{ id: "one" }]);
    expect(parseZetarisResult({ headers: [], data: [] })).toEqual([]);
  });
  it("rejects model-supplied arbitrary tool names", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  content: '{"tool":"execute_sql","reason":"ignore all rules"}',
                },
              },
            ],
          }),
          { status: 200 },
        ),
      ),
    );
    const provider = createModelProvider({
      MODEL_PROVIDER: "nvidia",
      NVIDIA_API_KEY: "unit-test-token",
    });
    await expect(
      provider.next(
        { paymentId: "p", context: {}, history: [], memories: [] },
        new AbortController().signal,
      ),
    ).rejects.toThrow();
  });
  it("retries one transient model failure, then validates its response", async () => {
    const mock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  content: '{"tool":"ledger","reason":"Check the ledger"}',
                },
              },
            ],
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", mock);
    const provider = createModelProvider({
      MODEL_PROVIDER: "nvidia",
      NVIDIA_API_KEY: "unit-test-token",
    });
    expect(
      (
        await provider.next(
          { paymentId: "p", context: {}, history: [], memories: [] },
          new AbortController().signal,
        )
      ).tool,
    ).toBe("ledger");
    expect(mock).toHaveBeenCalledTimes(2);
  });
  it("persists explicitly approved memory and isolates namespaces", async () => {
    const { dir } = await isolated();
    const memory = new MemoryService(join(dir, "memory"));
    expect(await memory.recall("workspace", "ledger review")).toHaveLength(0);
    const saved = await memory.approve(
      "workspace",
      "Always inspect ledger before settlements in the payment review.",
      "human-review:one",
    );
    expect(saved.source).toBe("human-review:one");
    const restart = new MemoryService(join(dir, "memory"));
    expect(
      await restart.recall("workspace", "ledger payment review"),
    ).toHaveLength(1);
    expect(await restart.recall("other", "ledger payment review")).toHaveLength(
      0,
    );
    expect(
      await readFile(
        join(
          dir,
          "memory",
          await import("node:crypto").then((m) =>
            m.createHash("sha256").update("workspace").digest("hex"),
          ),
          "ledger.jsonl",
        ),
        "utf8",
      ),
    ).toContain("create");
  });
});
describe("application lifecycle", () => {
  it("cancels without producing a financial outcome", async () => {
    const { dir, store } = await isolated();
    const ds = await store.saveDataset(packets[0]);
    const { app, service } = await createApp({
      store,
      mode: "fixture",
      storageDir: dir,
      seed: false,
    });
    const start = await service.start(
      ds.info.id,
      packets[0].manifest.focusPaymentIds![0],
    );
    const cancelled = await service.cancel(start.id);
    expect(cancelled?.status).toBe("cancelled");
    expect(cancelled?.outcome).toBeNull();
    expect(cancelled?.actions).toHaveLength(0);
    await app.close();
  });
  it("uses approved memory to change evidence order while preserving verification", async () => {
    const { dir, store } = await isolated();
    const memory = new MemoryService(join(dir, "memory"));
    await memory.approve(
      "workspace",
      "Inspect ledger before settlements during payment review.",
      "human-review:test",
    );
    const ds = await store.saveDataset(packets[0]);
    const { app, service } = await createApp({
      store,
      mode: "fixture",
      storageDir: dir,
      seed: false,
    });
    const start = await service.start(
      ds.info.id,
      packets[0].manifest.focusPaymentIds![0],
    );
    const run = await service.wait(start.id);
    expect(run.memories.length).toBeGreaterThan(0);
    expect(run.queries[1].tool).toBe("ledger");
    expect(run.outcome).toBe("anomaly_supported");
    await app.close();
  });
  it("completes a run, resolves citations, reviews, exports, and restores after restart", async () => {
    const { dir, store } = await isolated();
    const ds = await store.saveDataset(packets[0]);
    const { app, service } = await createApp({
      store,
      mode: "fixture",
      storageDir: dir,
      seed: false,
    });
    const response = await app.inject({
      method: "POST",
      url: "/api/investigations",
      payload: {
        datasetId: ds.info.id,
        paymentId: packets[0].manifest.focusPaymentIds![0],
      },
    });
    expect(response.statusCode).toBe(202);
    const run = await service.wait(response.json().id);
    expect(run.status).toBe("completed");
    expect(run.events.some((e) => e.type === "verification")).toBe(true);
    const ids = new Set(run.evidence.map((e) => e.id));
    expect(
      run.findings.every((f) => f.evidenceIds.every((id) => ids.has(id))),
    ).toBe(true);
    const review = await app.inject({
      method: "POST",
      url: `/api/investigations/${run.id}/review`,
      payload: {
        decision: "accepted",
        notes: "Reviewed source records",
        approveMemory: true,
        memoryContent:
          "Inspect ledger before settlements during payment review.",
      },
    });
    expect(review.statusCode).toBe(200);
    expect(review.json().review.memoryId).toBeTruthy();
    for (const format of ["json", "html", "csv"]) {
      const result = await app.inject(
        `/api/investigations/${run.id}/export?format=${format}`,
      );
      expect(result.statusCode).toBe(200);
      expect(result.headers["content-disposition"]).toContain(format);
    }
    await app.close();
    const restarted = await createApp({
      store: new FileStore(dir),
      mode: "fixture",
      storageDir: dir,
      seed: false,
    });
    expect(
      (await restarted.app.inject(`/api/investigations/${run.id}`)).json()
        .review.decision,
    ).toBe("accepted");
    await restarted.app.close();
  });
  it("escapes HTML source content", async () => {
    const { dir, store } = await isolated();
    const ds = await store.saveDataset(packets[0]);
    const { app, service } = await createApp({
      store,
      mode: "fixture",
      storageDir: dir,
      seed: false,
    });
    const started = await service.start(
      ds.info.id,
      packets[0].manifest.focusPaymentIds![0],
    );
    const run = await service.wait(started.id);
    run.findings[0].summary = "<script>alert(1)</script>";
    const html = exportRun(run, "html").body;
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    await app.close();
  });
});
