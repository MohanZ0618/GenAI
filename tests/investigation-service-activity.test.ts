import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  loadBuiltinDatasets,
  type DatasetPackage,
} from "../packages/data/src/index.ts";
import type {
  EvidenceReference,
  Investigation,
  InvestigationActivity,
  Mode,
  ToolName,
} from "../packages/contracts/src/index.ts";
import { FileStore } from "../apps/api/src/store.ts";
import { InvestigationService } from "../apps/api/src/service.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import type { ModelProvider } from "../apps/api/src/integrations/model.ts";
import * as evidence from "../apps/api/src/evidence.ts";
import {
  toolResultActivity,
  unfinishedActivities,
} from "../apps/api/src/activity.ts";

let packet: DatasetPackage;
const setups: Array<{ dir: string; service: InvestigationService }> = [];
beforeAll(async () => {
  packet = (await loadBuiltinDatasets()).find(
    (item) => item.manifest.name === "Review packet 001",
  )!;
});
afterEach(async () => {
  await Promise.all(setups.map(({ service }) => service.close()));
  await Promise.all(
    setups
      .splice(0)
      .map(({ dir }) => rm(dir, { recursive: true, force: true })),
  );
  vi.restoreAllMocks();
});

async function setup(mode: Mode = "fixture", provider?: ModelProvider) {
  const dir = await mkdtemp(join(tmpdir(), "fintrace-activity-"));
  const store = new FileStore(dir);
  await store.init();
  const dataset = await store.saveDataset(packet);
  const memory = new MemoryService(join(dir, "memory"));
  const service = new InvestigationService(store, mode, memory, provider);
  setups.push({ dir, service });
  return {
    dir,
    store,
    dataset,
    memory,
    service,
    start: () =>
      service.start(dataset.info.id, packet.manifest.focusPaymentIds![0]),
  };
}
function latestActivities(run: Investigation) {
  const latest = new Map<string, InvestigationActivity>();
  for (const event of run.events)
    if (event.activity) latest.set(event.activity.id, event.activity);
  return [...latest.values()];
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => (resolve = done));
  return { promise, resolve };
}
function model(next?: ModelProvider["next"]): ModelProvider {
  return {
    name: "test-model",
    model: "test-only",
    next:
      next ||
      (async ({ context }) => ({
        tool: (context as { availableTools: ToolName[] }).availableTools[0],
        reason: "STRUCTURED_MODEL_ACTION_REASON",
      })),
  };
}
function sourceRecord(
  table: EvidenceReference["table"],
  recordId: string,
  record: EvidenceReference["record"],
): EvidenceReference {
  return {
    id: `${table}:${recordId}`,
    table,
    recordId,
    record,
    queryId: "helper-test-query",
    datasetVersion: "helper-test-version",
  };
}

describe("investigation activity lifecycle", () => {
  it("does not overwrite a completed run when wait receives an older running snapshot", async () => {
    const { service, store, start } = await setup();
    const completed = await service.wait((await start()).id);
    expect(completed.status).toBe("completed");
    const older = structuredClone(completed);
    older.status = "running";
    older.outcome = null;
    vi.spyOn(store, "run").mockResolvedValueOnce(older);
    const observed = await service.wait(completed.id);
    expect(observed.status).toBe("completed");
    expect(observed.outcome).toBe(completed.outcome);
    expect((await store.run(completed.id))!.status).toBe("completed");
  });

  it("keeps UI-only activity payloads and started events out of model history", async () => {
    const histories: unknown[][] = [];
    const provider = model(async (input) => {
      histories.push(input.history);
      return {
        tool: (input.context as { availableTools: ToolName[] })
          .availableTools[0],
        reason: "Inspect required evidence",
      };
    });
    const { service, start } = await setup("local-model", provider);
    const completed = await service.wait((await start()).id);
    expect(completed.status).toBe("completed");
    expect(histories.length).toBeGreaterThan(0);
    for (const history of histories) {
      expect(history.length).toBeLessThanOrEqual(10);
      expect(
        history.every(
          (item) =>
            !("activity" in (item as Record<string, unknown>)) &&
            !String((item as { type: string }).type).endsWith("_started"),
        ),
      ).toBe(true);
    }
  });

  it("persists matched starts and completions with real query counts and bounded related citations", async () => {
    const { service, store, start, dir } = await setup();
    const run = await service.wait((await start()).id);
    expect(run).toMatchObject({
      status: "completed",
      outcome: "anomaly_supported",
    });
    expect(run.findings.some((finding) => finding.category === "F06")).toBe(
      true,
    );
    expect(unfinishedActivities(run)).toEqual([]);
    const activities = latestActivities(run);
    expect(new Set(activities.map((item) => item.kind))).toEqual(
      new Set(["planning", "tool", "verification", "memory"]),
    );
    for (const activity of activities) {
      const pair = run.events.filter(
        (event) => event.activity?.id === activity.id,
      );
      expect(pair.map((event) => event.activity?.status)).toEqual([
        "running",
        "completed",
      ]);
      expect(activity.source).toBe("rules");
      expect(activity.durationMs).toBeGreaterThanOrEqual(0);
      expect(activity.evidenceIds?.length || 0).toBeLessThanOrEqual(12);
      expect(
        activity.evidenceIds?.every((id) =>
          run.evidence.some((item) => item.id === id),
        ) ?? true,
      ).toBe(true);
      if (activity.kind === "tool") {
        const query = run.queries.find((item) => item.id === activity.queryId)!;
        expect(query).toBeDefined();
        expect(activity.rowCount).toBe(query.rowCount);
        expect(activity.tables).toEqual(query.tables);
        expect(pair[0].activity!.tables).toEqual(query.tables);
        expect(activity.durationMs).toBe(query.durationMs);
        expect(activity.relatedCount).toBeLessThanOrEqual(activity.rowCount!);
      }
    }
    const reopened = new FileStore(dir);
    expect((await reopened.run(run.id))!.events).toEqual(run.events);
    expect((await store.run(run.id))!.outcome).toBe("anomaly_supported");
  });

  it("labels model decisions and separates public tool purposes from diagnostic action reasons", async () => {
    const { service, start } = await setup("local-model", model());
    const run = await service.wait((await start()).id);
    expect(run.status).toBe("completed");
    const selections = latestActivities(run).filter(
      (item) => item.kind === "planning",
    );
    expect(selections[0].source).toBe("rules");
    expect(selections.slice(1).every((item) => item.source === "model")).toBe(
      true,
    );
    expect(JSON.stringify(selections)).not.toContain(
      "STRUCTURED_MODEL_ACTION_REASON",
    );
    expect(
      run.events.some(
        (event) => event.message === "STRUCTURED_MODEL_ACTION_REASON",
      ),
    ).toBe(true);
    expect(run.modelTurns).toBe(selections.length - 1);
  });

  it("makes waiting model planning visible and closes it immediately when cancelled", async () => {
    const entered = deferred();
    const released = deferred();
    const provider = model(async ({ context }) => {
      entered.resolve();
      await released.promise;
      return {
        tool: (context as { availableTools: ToolName[] }).availableTools[0],
        reason: "not public",
      };
    });
    const { service, store, start } = await setup("local-model", provider);
    const started = await start();
    try {
      await entered.promise;
      const pending = unfinishedActivities((await store.run(started.id))!);
      expect(pending).toHaveLength(1);
      expect(pending[0].activity).toMatchObject({
        kind: "planning",
        status: "running",
        source: "model",
      });
      const cancelled = (await service.cancel(started.id))!;
      expect(cancelled.status).toBe("cancelled");
      expect(unfinishedActivities(cancelled)).toEqual([]);
      const final = latestActivities(cancelled).find(
        (item) => item.id === pending[0].activity.id,
      )!;
      expect(final.status).toBe("cancelled");
      expect(final.durationMs).toBeGreaterThanOrEqual(0);
    } finally {
      released.resolve();
      await service.close();
    }
    const final = (await store.run(started.id))!;
    expect(final.outcome).toBeNull();
    expect(unfinishedActivities(final)).toEqual([]);
    expect(
      final.events.filter(
        (event) =>
          event.activity?.source === "model" &&
          event.activity.status === "cancelled",
      ),
    ).toHaveLength(1);
  });

  it("ends planning as failed when the provider rejects without producing a financial result", async () => {
    const { service, start } = await setup(
      "local-model",
      model(async () => {
        throw new Error("Model request failed (401)");
      }),
    );
    const run = await service.wait((await start()).id);
    expect(run).toMatchObject({ status: "failed", outcome: null, actions: [] });
    expect(unfinishedActivities(run)).toEqual([]);
    expect(
      latestActivities(run).find(
        (item) => item.kind === "planning" && item.source === "model",
      )?.status,
    ).toBe("failed");
  });

  it("records query failure as failure rather than a successful empty result", async () => {
    const actualRetrieve = evidence.retrieve;
    vi.spyOn(evidence, "retrieve")
      .mockImplementationOnce(actualRetrieve)
      .mockRejectedValueOnce(new Error("source unavailable"));
    const { service, start } = await setup();
    const run = await service.wait((await start()).id);
    expect(run.status).toBe("failed");
    const failed = latestActivities(run).find(
      (item) => item.kind === "tool" && item.status === "failed",
    )!;
    expect(failed).toBeDefined();
    expect(failed.queryId).toBe(run.queries.at(-1)!.id);
    expect(failed.summary).toContain(
      "does not establish that source records are missing",
    );
    expect(failed.rowCount).toBeUndefined();
    expect(failed.evidenceIds).toBeUndefined();
    expect(unfinishedActivities(run)).toEqual([]);
  });

  it("shows the actual source tables while a query runs and keeps cancellation terminal", async () => {
    const entered = deferred();
    const released = deferred();
    const actualRetrieve = evidence.retrieve;
    vi.spyOn(evidence, "retrieve").mockImplementationOnce(async (...args) => {
      entered.resolve();
      await released.promise;
      args[4].throwIfAborted();
      return actualRetrieve(...args);
    });
    const { service, store, start } = await setup();
    const started = await start();
    let activityId = "";
    try {
      await entered.promise;
      const pending = unfinishedActivities((await store.run(started.id))!);
      expect(pending).toHaveLength(1);
      expect(pending[0]).toMatchObject({
        tool: "overview",
        activity: {
          kind: "tool",
          status: "running",
          tables: ["payments", "invoices", "vendors"],
        },
      });
      activityId = pending[0].activity.id;
      const cancelled = (await service.cancel(started.id))!;
      expect(unfinishedActivities(cancelled)).toEqual([]);
    } finally {
      released.resolve();
      await service.close();
    }
    const final = (await store.run(started.id))!;
    expect(final).toMatchObject({
      status: "cancelled",
      outcome: null,
      actions: [],
    });
    expect(
      final.events
        .filter((event) => event.activity?.id === activityId)
        .map((event) => event.activity!.status),
    ).toEqual(["running", "cancelled"]);
  });

  it("closes an interrupted memory recall without changing the retained evidence", async () => {
    const entered = deferred();
    const released = deferred();
    const { service, memory, store, start } = await setup();
    vi.spyOn(memory, "recall").mockImplementation(async () => {
      entered.resolve();
      await released.promise;
      return [];
    });
    const started = await start();
    try {
      await entered.promise;
      const before = (await store.run(started.id))!;
      expect(unfinishedActivities(before)[0].activity.kind).toBe("memory");
      const cancelled = (await service.cancel(started.id))!;
      expect(cancelled.evidence).toEqual(before.evidence);
      expect(
        latestActivities(cancelled).find((item) => item.kind === "memory")
          ?.status,
      ).toBe("cancelled");
    } finally {
      released.resolve();
      await service.close();
    }
    expect(unfinishedActivities((await store.run(started.id))!)).toEqual([]);
  });

  it("terminates persisted unfinished activities on recovery and accepts legacy events", async () => {
    const { service, store, start } = await setup();
    const original = await service.wait((await start()).id);
    const interrupted = structuredClone(original);
    interrupted.id = "run-activity-recovery";
    interrupted.status = "running";
    interrupted.outcome = null;
    interrupted.events.push(
      {
        id: String(interrupted.events.length + 1),
        at: new Date().toISOString(),
        type: "planning",
        message: "Legacy event without structured activity",
      },
      {
        id: String(interrupted.events.length + 2),
        at: new Date().toISOString(),
        type: "tool_started",
        message: "Read source records",
        tool: "ledger",
        activity: {
          id: "pending-before-restart",
          kind: "tool",
          status: "running",
          source: "rules",
        },
      },
    );
    await store.saveRun(interrupted);
    await service.recover();
    await service.recover();
    const recovered = (await store.run(interrupted.id))!;
    expect(recovered.status).toBe("failed");
    expect(unfinishedActivities(recovered)).toEqual([]);
    expect(
      recovered.events.filter(
        (event) =>
          event.activity?.id === "pending-before-restart" &&
          event.activity.status === "failed",
      ),
    ).toHaveLength(1);
    expect(
      recovered.events.some((event) => event.message.startsWith("Legacy")),
    ).toBe(true);
  });

  it("describes successful empty queries without asserting that a payment is missing", () => {
    const details = toolResultActivity([], [], "payment", "2026-07-01");
    expect(details).toMatchObject({
      rowCount: 0,
      relatedCount: 0,
      evidenceIds: [],
    });
    expect(details.summary).toContain("query succeeded");
    expect(details.summary).toContain(
      "Source coverage still needs to be checked",
    );
  });

  it("summarizes distinct related invoice and payment links without deciding whether they are duplicate payments", () => {
    const payments = ["p1", "p2", "p3"].map((paymentId) =>
      sourceRecord("payments", paymentId, {
        payment_id: paymentId,
        reference_number: `ref-${paymentId}`,
        vendor_id: "vendor",
      }),
    );
    const rows = [
      ["a1", "p1", "i1"],
      ["a2", "p1", "i2"],
      ["a3", "p2", "i1"],
      ["a4", "p3", "i9"],
    ].map(([id, paymentId, invoiceId]) =>
      sourceRecord("payment_allocations", id, {
        payment_id: paymentId,
        invoice_id: invoiceId,
      }),
    );
    const details = toolResultActivity(
      rows,
      [...payments, ...rows],
      "p1",
      "2026-07-01",
      "allocations",
    );
    expect(details).toMatchObject({ rowCount: 4, relatedCount: 3 });
    expect(details.summary).toContain("link 2 invoices and 2 payments");
    expect(details.evidenceIds).not.toContain("payment_allocations:a4");
    expect(details.summary).not.toMatch(/settled|duplicate.*confirmed/i);
  });

  it("reports bank transaction statuses from related returned records while excluding fees, unrelated rows and future records", () => {
    const payment = sourceRecord("payments", "p1", {
      payment_id: "p1",
      reference_number: "ref",
      vendor_id: "vendor",
    });
    const rows = [
      sourceRecord("bank_transactions", "posted", {
        payment_reference: "ref",
        transaction_type: "payment",
        status: "posted",
      }),
      sourceRecord("bank_transactions", "returned", {
        payment_reference: "ref",
        transaction_type: "payment",
        status: "returned",
      }),
      sourceRecord("bank_transactions", "fee", {
        payment_reference: "ref",
        transaction_type: "bank fee",
        status: "posted",
      }),
      sourceRecord("bank_transactions", "unrelated", {
        payment_reference: "another-reference",
        transaction_type: "payment",
        status: "posted",
      }),
      sourceRecord("bank_transactions", "future", {
        payment_reference: "ref",
        transaction_type: "payment",
        status: "posted",
        transaction_date: "2027-01-01",
      }),
    ];
    const details = toolResultActivity(
      rows,
      [payment, ...rows],
      "p1",
      "2026-07-01",
      "settlements",
    );
    expect(details).toMatchObject({ rowCount: 5, relatedCount: 3 });
    expect(details.summary).toContain("Matched 2 non-fee bank transactions");
    expect(details.summary).toContain("1 marked posted and 1 marked returned");
    expect(details.evidenceIds).not.toContain("bank_transactions:future");
  });

  it("limits an unmatched bank summary to the returned records without inferring a missing settlement", () => {
    const payment = sourceRecord("payments", "p1", {
      payment_id: "p1",
      reference_number: "ref",
      vendor_id: "vendor",
    });
    const fee = sourceRecord("bank_transactions", "fee", {
      payment_reference: "ref",
      transaction_type: "bank fee",
      status: "posted",
    });
    const details = toolResultActivity(
      [fee],
      [payment, fee],
      "p1",
      "2026-07-01",
      "settlements",
    );
    expect(details).toMatchObject({ rowCount: 1, relatedCount: 1 });
    expect(details.summary).toContain("was matched in the returned records");
    expect(details.summary).not.toMatch(/anomaly|missing|settlement failed/i);
  });
});
