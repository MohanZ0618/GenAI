import { describe, expect, it, vi } from "vitest";
import { mkdtemp } from "node:fs/promises";
import { resolve, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { FileStore } from "../apps/api/src/store.ts";
import { InvestigationService } from "../apps/api/src/service.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import type { ModelProvider } from "../apps/api/src/integrations/model.ts";
import type {
  BatchStartResponse,
  ToolName,
} from "../packages/contracts/src/index.ts";
import { createApp } from "../apps/api/src/server.ts";
import { buildManualPackets } from "../scripts/prepare_openai_manual.ts";

async function setup() {
  const dir = await mkdtemp(resolve(".local/batch-test-"));
  const store = new FileStore(dir);
  await store.init();
  const dataset = await store.saveDataset(buildManualPackets().main);
  const memory = new MemoryService(join(dir, "memory"));
  return { dir, store, dataset, memory };
}

describe("batch investigations", () => {
  it("runs three independent agent loops in parallel, isolates failures and skips cancelled queued work", async () => {
    const { store, dataset, memory } = await setup();
    let release!: () => void;
    const gate = new Promise<void>((done) => {
      release = done;
    });
    let waiting = 0;
    let peak = 0;
    const entered = new Set<string>();
    let failingPayment = "";
    const paymentIds = dataset.data.manifest.focusPaymentIds!.slice(0, 6);
    const next = vi.fn<ModelProvider["next"]>(async (input) => {
      entered.add(input.paymentId);
      waiting++;
      peak = Math.max(peak, waiting);
      await gate;
      waiting--;
      if (input.paymentId === failingPayment)
        throw new Error("One case failed");
      return {
        tool: (input.context as { availableTools: ToolName[] })
          .availableTools[0],
        reason: "Retrieve evidence",
        finish: false,
      };
    });
    const service = new InvestigationService(store, "local-model", memory, {
      name: "openai",
      model: "mock",
      next,
    });
    try {
      const runs = await Promise.all(
        paymentIds.map((paymentId) =>
          service.start(dataset.info.id, paymentId),
        ),
      );
      await vi.waitFor(() => expect(entered.size).toBe(3));
      const initial = await store.runs();
      expect(initial.filter((run) => run.status === "running")).toHaveLength(3);
      expect(initial.filter((run) => run.status === "queued")).toHaveLength(3);
      failingPayment = initial.find(
        (run) => run.status === "running",
      )!.paymentId;
      const cancelled = initial.find((run) => run.status === "queued")!;
      await service.cancel(cancelled.id);
      release();
      const results = await Promise.all(
        runs.map((run) => service.wait(run.id)),
      );
      expect(peak).toBe(3);
      expect(
        results.find((run) => run.paymentId === failingPayment)?.status,
      ).toBe("failed");
      expect(results.find((run) => run.id === cancelled.id)?.status).toBe(
        "cancelled",
      );
      expect(entered.has(cancelled.paymentId)).toBe(false);
      const completed = results.filter((run) => run.status === "completed");
      expect(completed).toHaveLength(4);
      for (const run of completed) {
        expect(run.queries.length).toBeGreaterThan(0);
        expect(run.modelTurns).toBeGreaterThan(0);
        expect(run.outcome).not.toBeNull();
      }
      const replay = await service.start(
        dataset.info.id,
        completed[0].paymentId,
      );
      expect(replay.id).toBe(completed[0].id);
    } finally {
      release();
      await service.close();
    }
  });

  it("shutdown cancels running and queued investigations", async () => {
    const { store, dataset, memory } = await setup();
    let calls = 0;
    const provider: ModelProvider = {
      name: "openai",
      model: "mock",
      next: async (_input, signal) => {
        calls++;
        await delay(30000, undefined, { signal });
        return { finish: true, reason: "Stop" };
      },
    };
    const service = new InvestigationService(
      store,
      "local-model",
      memory,
      provider,
    );
    try {
      await Promise.all(
        dataset.data.manifest
          .focusPaymentIds!.slice(0, 5)
          .map((paymentId) => service.start(dataset.info.id, paymentId)),
      );
      await vi.waitFor(() => expect(calls).toBe(3));
      await service.close();
      expect((await store.runs()).map((run) => run.status)).toEqual(
        Array(5).fill("cancelled"),
      );
      expect(calls).toBe(3);
    } finally {
      await service.close();
    }
  });

  it("batch API deduplicates cases, returns individual errors and reuses completed results", async () => {
    const { dir, store, dataset } = await setup();
    const { app, service } = await createApp({
      store,
      storageDir: dir,
      mode: "fixture",
      seed: false,
    });
    try {
      const normal = {
        datasetId: dataset.info.id,
        paymentId: "PAY_DEMO_NORMAL",
      };
      const duplicate = {
        datasetId: dataset.info.id,
        paymentId: "PAY_DEMO_DUP",
      };
      const response = await app.inject({
        method: "POST",
        url: "/api/investigations/batch",
        payload: {
          cases: [
            normal,
            normal,
            duplicate,
            { ...normal, paymentId: "missing" },
          ],
        },
      });
      expect(response.statusCode).toBe(202);
      const batch = response.json<BatchStartResponse>();
      expect(batch.concurrency).toBe(3);
      expect(batch.results).toHaveLength(3);
      expect(batch.results[2]).toMatchObject({
        paymentId: "missing",
        error: "Payment not found in this dataset case queue",
      });
      for (const item of batch.results.slice(0, 2))
        await service.wait(item.investigationId!);
      const replay = (
        await app.inject({
          method: "POST",
          url: "/api/investigations/batch",
          payload: { cases: [normal, duplicate] },
        })
      ).json<BatchStartResponse>();
      expect(replay.results.map((item) => item.investigationId)).toEqual(
        batch.results.slice(0, 2).map((item) => item.investigationId),
      );
      expect(await store.runs()).toHaveLength(2);
      expect(
        (
          await app.inject({
            method: "POST",
            url: "/api/investigations/batch",
            payload: { cases: [] },
          })
        ).statusCode,
      ).toBe(400);
    } finally {
      await app.close();
    }
  });
});
