import { describe, expect, it, vi } from "vitest";
import { mkdir, mkdtemp } from "node:fs/promises";
import { resolve } from "node:path";
import {
  buildManualPackets,
  manualCases,
} from "../scripts/prepare_openai_manual.ts";
import {
  TABLES,
  type Dataset,
  type EvidenceReference,
  type ModelRequestTrace,
} from "../packages/contracts/src/index.ts";
import {
  packageToCsv,
  parseCsvPackage,
  type DatasetPackage,
} from "../packages/data/src/index.ts";
import { recordId } from "../apps/api/src/store.ts";
import { assess, TOOL_ORDER } from "../apps/api/src/verifier.ts";
import {
  planningEvidence,
  CONTEXT_BUDGET_BYTES,
} from "../apps/api/src/context.ts";
import { createModelProvider } from "../apps/api/src/integrations/model.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";

function evidenceFor(packet: DatasetPackage): EvidenceReference[] {
  return TABLES.flatMap((table) =>
    packet.tables[table].map((record, i) => ({
      id: `${table}:${recordId(table, record, i)}`,
      table,
      recordId: recordId(table, record, i),
      queryId: "regression",
      datasetVersion: "regression",
      record,
    })),
  );
}
function assessment(packet: DatasetPackage, paymentId: string) {
  const dataset: Dataset = {
    ...packet.manifest,
    id: "regression",
    version: "regression",
    caseCount: 8,
    createdAt: "",
    builtin: false,
  };
  return assess(dataset, paymentId, evidenceFor(packet), new Set(TOOL_ORDER));
}

describe("review regressions", () => {
  it.each([
    ["payments", "created_at", "payment_id", "PAY_DEMO_NORMAL"],
    ["invoices", "created_at", "invoice_id", "INV_DEMO_NORMAL"],
    ["payment_allocations", "allocation_date", "payment_id", "PAY_DEMO_NORMAL"],
    ["bank_transactions", "posted_date", "payment_reference", "REF_NORMAL"],
    ["gl_entries", "posting_date", "source_transaction_id", "PAY_DEMO_NORMAL"],
    ["vendors", "created_at", "vendor_id", "VND_DEMO_NORMAL"],
  ])(
    "excludes future %s facts from a normal-case decision",
    (table, field, key, value) => {
      const { main } = buildManualPackets();
      main.tables[table].find((row) => row[key] === value)![field] =
        "2026-11-01T00:00:00Z";
      expect(assessment(main, "PAY_DEMO_NORMAL").outcome).toBe(
        "insufficient_evidence",
      );
    },
  );
  it.each(manualCases)(
    "matches the isolated $code reference scenario",
    (item) => {
      const packet = parseCsvPackage(packageToCsv(buildManualPackets().main));
      const result = assessment(packet, `PAY_DEMO_${item.code}`);
      expect(result.outcome).toBe(item.outcome);
      expect(result.findings.some((f) => f.category === item.category)).toBe(
        true,
      );
      if (item.code.startsWith("FUTURE_"))
        expect(
          result.checks.find((c) => c.id === "observation-cutoff")?.detail,
        ).toContain("excluded");
    },
  );

  it("withholds a future vendor snapshot and excludes future duplicate obligations", () => {
    const { main } = buildManualPackets();
    main.tables.vendors.find(
      (v) => v.vendor_id === "VND_DEMO_STALE",
    )!.updated_at = "2026-11-01T00:00:00Z";
    expect(assessment(main, "PAY_DEMO_STALE").outcome).toBe(
      "insufficient_evidence",
    );
    for (const allocation of main.tables.payment_allocations.filter(
      (r) => r.payment_id === "PAY_DEMO_DUP_OTHER",
    ))
      allocation.allocation_date = "2026-11-01";
    for (const payment of main.tables.payments.filter(
      (r) => r.payment_id === "PAY_DEMO_DUP_OTHER",
    )) {
      payment.payment_date = "2026-11-01";
      payment.created_at = "2026-11-01T00:00:00Z";
    }
    expect(
      assessment(main, "PAY_DEMO_DUP").findings.some(
        (f) => f.category === "F06",
      ),
    ).toBe(false);
  });

  it("selects the target beyond 100 unrelated records and retains duplicate links without private fields", () => {
    const { main } = buildManualPackets();
    main.tables.vendors.at(-1)!.tax_id_hash = "not-for-model";
    const context = planningEvidence(
      evidenceFor(main),
      "PAY_DEMO_CONTEXT_TAIL",
      main.manifest.asOf,
    );
    expect(
      context.evidence.some(
        (e) => e.record.payment_id === "PAY_DEMO_CONTEXT_TAIL",
      ),
    ).toBe(true);
    expect(context.evidence.some((e) => e.table === "bank_transactions")).toBe(
      true,
    );
    expect(JSON.stringify(context)).not.toMatch(
      /BACKGROUND|not-for-model|tax_id_hash/,
    );
    const duplicate = planningEvidence(
      evidenceFor(main),
      "PAY_DEMO_DUP",
      main.manifest.asOf,
    );
    expect(
      duplicate.evidence.filter((e) => e.table === "payments"),
    ).toHaveLength(2);
  });

  it("bounds context bytes and reports omissions while keeping multiple sources", () => {
    const { main } = buildManualPackets();
    const evidence = evidenceFor(main);
    const related = evidence.find(
      (e) => e.record.payment_id === "PAY_DEMO_DUP",
    )!;
    for (let i = 0; i < 200; i++)
      evidence.push({
        ...related,
        id: `extra-${i}`,
        record: { ...related.record, bank_account_id: "x".repeat(1000) },
      });
    const context = planningEvidence(
      evidence,
      "PAY_DEMO_DUP",
      main.manifest.asOf,
    );
    expect(Buffer.byteLength(JSON.stringify(context.evidence))).toBe(
      context.bytes,
    );
    expect(context.bytes).toBeLessThanOrEqual(CONTEXT_BUDGET_BYTES);
    expect(context.omitted).toBeGreaterThan(0);
    expect(context.evidence.some((e) => e.table === "gl_entries")).toBe(true);
  });

  it("accepts 1000 rows and rejects 1001 before activation", () => {
    const { main } = buildManualPackets();
    const original = main.tables.audit_log[0];
    main.tables.audit_log = Array.from({ length: 1000 }, (_, i) => ({
      ...original,
      event_id: `BOUNDARY_${i}`,
    }));
    expect(() => parseCsvPackage(packageToCsv(main))).not.toThrow();
    main.tables.audit_log.push({ ...original, event_id: "BOUNDARY_1000" });
    expect(() => parseCsvPackage(packageToCsv(main))).toThrow(
      /audit_log.csv: maximum 1000 rows/,
    );
  });

  it.each(["openai", "nvidia", "meterless"])(
    "uses the same stop contract for %s",
    async (name) => {
      const fetch = vi.fn().mockImplementation(
        async () =>
          new Response(
            JSON.stringify({
              choices: [
                {
                  message: {
                    content: JSON.stringify({
                      tool: null,
                      finish: true,
                      reason: "Stop",
                    }),
                  },
                },
              ],
            }),
          ),
      );
      vi.stubGlobal("fetch", fetch);
      const provider = createModelProvider({
        MODEL_PROVIDER: name,
        OPENAI_API_KEY: "mock",
        NVIDIA_API_KEY: "mock",
        METERLESS_RUNTIME_TOKEN: "mock",
        METERLESS_MODEL: "mock",
      });
      const input = {
        paymentId: "test",
        context: {},
        history: [],
        memories: [],
      };
      expect(
        (await provider.next(input, new AbortController().signal)).finish,
      ).toBe(true);
      fetch.mockImplementation(
        async () =>
          new Response(
            JSON.stringify({
              choices: [
                {
                  message: {
                    content: JSON.stringify({
                      tool: "ledger",
                      finish: true,
                      reason: "Contradiction",
                    }),
                  },
                },
              ],
            }),
          ),
      );
      await expect(
        provider.next(input, new AbortController().signal),
      ).rejects.toThrow();
    },
  );

  it("records HTTP attempts, request IDs and usage without request content", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("private", { status: 429 }))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              model: "returned-model",
              choices: [
                {
                  message: {
                    content:
                      '{"tool":"ledger","reason":"Inspect","finish":false}',
                  },
                },
              ],
              usage: {
                prompt_tokens: 12,
                completion_tokens: 4,
                total_tokens: 16,
              },
            }),
            { headers: { "x-request-id": "request-test" } },
          ),
        ),
    );
    const traces: ModelRequestTrace[] = [];
    await createModelProvider({
      MODEL_PROVIDER: "openai",
      OPENAI_API_KEY: "not-to-be-recorded",
    }).next(
      { paymentId: "test", context: {}, history: [], memories: [] },
      new AbortController().signal,
      async (trace) => {
        traces.push(trace);
      },
    );
    expect(traces.map((t) => t.status)).toEqual(["failed", "succeeded"]);
    expect(traces[1]).toMatchObject({
      attempt: 2,
      requestId: "request-test",
      returnedModel: "returned-model",
      inputTokens: 12,
      outputTokens: 4,
      totalTokens: 16,
    });
    expect(JSON.stringify(traces)).not.toMatch(
      /private|not-to-be-recorded|messages/,
    );
  });

  it("recalls approved Chinese memory after restart without an embedding API", async () => {
    await mkdir(".local", { recursive: true });
    const path = await mkdtemp(resolve(".local/bilingual-test-"));
    const memory = new MemoryService(path);
    await memory.approve(
      "workspace",
      "请先检查供应商变更历史，再复核付款分录。",
      "human-run",
    );
    const restored = new MemoryService(path);
    const found = await restored.recall(
      "workspace",
      "payment investigation review ledger settlement vendor history",
    );
    expect(found).toHaveLength(1);
    expect(found[0].content).toContain("供应商变更");
    expect(found[0].source).toBe("human-run");
    expect(await restored.recall("other", "vendor history")).toHaveLength(0);
  });

  it("blocks unmocked external requests", async () => {
    await expect(fetch("https://must-never-connect.invalid")).rejects.toThrow(
      /External network is disabled/,
    );
  });

  it.each(["mock-sensitive-raw-body", "null", "[]"])(
    "sanitizes invalid HTTP response envelopes %#",
    async (body) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
      await expect(
        createModelProvider({
          MODEL_PROVIDER: "openai",
          OPENAI_API_KEY: "mock",
        }).next(
          { paymentId: "test", context: {}, history: [], memories: [] },
          new AbortController().signal,
        ),
      ).rejects.toThrow("Model returned an invalid response envelope");
    },
  );
});
