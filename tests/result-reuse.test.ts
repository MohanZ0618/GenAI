import { describe, expect, it, vi } from "vitest";
import { mkdtemp } from "node:fs/promises";
import { resolve, join } from "node:path";
import { FileStore } from "../apps/api/src/store.ts";
import { InvestigationService } from "../apps/api/src/service.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import type { ModelProvider } from "../apps/api/src/integrations/model.ts";
import type { Case, ToolName } from "../packages/contracts/src/index.ts";
import { createApp } from "../apps/api/src/server.ts";
import { buildManualPackets } from "../scripts/prepare_openai_manual.ts";

async function setup() {
  const dir = await mkdtemp(resolve(".local/reuse-test-"));
  const store = new FileStore(dir);
  await store.init();
  const memory = new MemoryService(join(dir, "memory"));
  const next = vi.fn<ModelProvider["next"]>(async (input) => ({
    tool: (input.context as { availableTools: ToolName[] }).availableTools[0],
    reason: "Retrieve required evidence",
    finish: false,
  }));
  const provider: ModelProvider = { name: "openai", model: "mock", next };
  const service = new InvestigationService(
    store,
    "local-model",
    memory,
    provider,
  );
  const dataset = await store.saveDataset(buildManualPackets().main);
  return { dir, store, memory, provider, service, dataset, next };
}

describe("saved investigation reuse", () => {
  it("lists actual outcomes without treating unfinished or updated cases as clear", async () => {
    const { dir, store, dataset } = await setup();
    const { app, service } = await createApp({
      mode: "fixture",
      storageDir: dir,
      store,
      seed: false,
    });
    try {
      for (const paymentId of [
        "PAY_DEMO_NORMAL",
        "PAY_DEMO_DUP",
        "PAY_DEMO_FUTURE_EVENT",
      ]) {
        const run = await service.start(dataset.info.id, paymentId);
        await service.wait(run.id);
      }
      const list = (
        await app.inject(`/api/cases?datasetId=${dataset.info.id}`)
      ).json().cases as Case[];
      expect(
        list.find((item) => item.paymentId === "PAY_DEMO_NORMAL")?.outcome,
      ).toBe("no_anomaly_supported");
      expect(
        list.find((item) => item.paymentId === "PAY_DEMO_DUP")?.outcome,
      ).toBe("anomaly_supported");
      expect(
        list.find((item) => item.paymentId === "PAY_DEMO_FUTURE_EVENT")
          ?.outcome,
      ).toBe("insufficient_evidence");
      expect(
        list.find((item) => item.paymentId === "PAY_DEMO_MISSING")?.outcome,
      ).toBeNull();
      const normalRun = (await store.runs()).find(
        (run) => run.paymentId === "PAY_DEMO_NORMAL",
      )!;
      await store.saveRun({ ...normalRun, status: "failed" });
      const failed = (
        await app.inject(`/api/cases?datasetId=${dataset.info.id}`)
      ).json().cases as Case[];
      expect(
        failed.find((item) => item.paymentId === "PAY_DEMO_NORMAL"),
      ).toMatchObject({ status: "failed", outcome: null });
      const revised = buildManualPackets().main;
      revised.manifest.clearingDays++;
      const updated = await store.saveDataset(revised);
      const changed = (
        await app.inject(`/api/cases?datasetId=${updated.info.id}`)
      ).json().cases as Case[];
      expect(
        changed.find((item) => item.paymentId === "PAY_DEMO_DUP"),
      ).toMatchObject({ updateAvailable: true, outcome: null });
      expect(await store.runs()).toHaveLength(3);
    } finally {
      await app.close();
    }
  });

  it("coalesces concurrent starts and reopens after memory changes and restart without model calls", async () => {
    const { service, dataset, store, memory, provider, next } = await setup();
    const runs = await Promise.all(
      Array.from({ length: 8 }, () =>
        service.start(dataset.info.id, "PAY_DEMO_NORMAL"),
      ),
    );
    expect(new Set(runs.map((run) => run.id)).size).toBe(1);
    const completed = await service.wait(runs[0].id);
    expect(completed.status).toBe("completed");
    expect(next).toHaveBeenCalled();
    const count = next.mock.calls.length;
    await memory.approve(
      "workspace",
      "请先检查供应商变更历史，再复核付款分录。",
      completed.id,
    );
    expect((await service.start(dataset.info.id, "PAY_DEMO_NORMAL")).id).toBe(
      completed.id,
    );
    await service.close();
    const restarted = new InvestigationService(
      store,
      "local-model",
      memory,
      provider,
    );
    await restarted.recover();
    expect(await restarted.start(dataset.info.id, "PAY_DEMO_NORMAL")).toEqual(
      completed,
    );
    expect(next).toHaveBeenCalledTimes(count);
    expect(await store.runs()).toHaveLength(1);
    await restarted.close();
  });

  it("does not reuse across dataset versions, execution modes or memory namespaces", async () => {
    const { service, dataset, store, memory, next } = await setup();
    const original = await service.start(dataset.info.id, "PAY_DEMO_NORMAL");
    await service.wait(original.id);
    const packet = buildManualPackets().main;
    packet.manifest.clearingDays++;
    const revised = await store.saveDataset(packet);
    const update = await service.start(revised.info.id, "PAY_DEMO_NORMAL");
    await service.wait(update.id);
    expect(update.id).not.toBe(original.id);
    const otherNamespace = await service.start(
      dataset.info.id,
      "PAY_DEMO_NORMAL",
      "other",
    );
    await service.wait(otherNamespace.id);
    expect(otherNamespace.id).not.toBe(original.id);
    const fixture = new InvestigationService(store, "fixture", memory);
    const offline = await fixture.start(dataset.info.id, "PAY_DEMO_NORMAL");
    await fixture.wait(offline.id);
    expect(offline.id).not.toBe(original.id);
    expect(next.mock.calls.length).toBeGreaterThan(4);
    await fixture.close();
    await service.close();
  });

  it("retries failed and cancelled runs and reuses legacy completed runs", async () => {
    const { service, dataset, store } = await setup();
    const original = await service.start(dataset.info.id, "PAY_DEMO_NORMAL");
    const completed = await service.wait(original.id);
    let last = completed;
    for (const status of ["failed", "cancelled"] as const) {
      for (const run of await store.runs())
        await store.saveRun({ ...run, status });
      const retry = await service.start(dataset.info.id, "PAY_DEMO_NORMAL");
      expect(retry.id).not.toBe(original.id);
      last = await service.wait(retry.id);
    }
    delete last.memoryNamespace;
    await store.saveRun(last);
    expect((await service.start(dataset.info.id, "PAY_DEMO_NORMAL")).id).toBe(
      last.id,
    );
    await service.close();
  });

  it("exposes saved IDs, marks changed imports, and reuses an unchanged reimport", async () => {
    const { dir, store, dataset } = await setup();
    const { app, service } = await createApp({
      mode: "fixture",
      storageDir: dir,
      store,
      seed: false,
    });
    try {
      const original = await service.start(dataset.info.id, "PAY_DEMO_NORMAL");
      await service.wait(original.id);
      const reopened = await app.inject({
        method: "POST",
        url: "/api/investigations",
        payload: {
          datasetId: dataset.info.id,
          paymentId: "PAY_DEMO_NORMAL",
        },
      });
      expect(reopened.json().id).toBe(original.id);
      expect(
        (await app.inject(`/api/cases?datasetId=${dataset.info.id}`))
          .json()
          .cases.find(
            (item: { paymentId: string }) =>
              item.paymentId === "PAY_DEMO_NORMAL",
          ),
      ).toMatchObject({
        investigationId: original.id,
        updateAvailable: false,
        status: "completed",
      });
      expect((await store.saveDataset(buildManualPackets().main)).info.id).toBe(
        dataset.info.id,
      );
      const revised = buildManualPackets().main;
      revised.manifest.clearingDays++;
      const updated = await store.saveDataset(revised);
      const list = (
        await app.inject(`/api/cases?datasetId=${updated.info.id}`)
      ).json().cases;
      expect(
        list.find(
          (item: { paymentId: string }) => item.paymentId === "PAY_DEMO_NORMAL",
        ),
      ).toMatchObject({ updateAvailable: true, status: "unreviewed" });
      const update = await service.start(updated.info.id, "PAY_DEMO_NORMAL");
      await service.wait(update.id);
      expect(
        (await app.inject(`/api/cases?datasetId=${updated.info.id}`))
          .json()
          .cases.find(
            (item: { paymentId: string }) =>
              item.paymentId === "PAY_DEMO_NORMAL",
          ),
      ).toMatchObject({
        investigationId: update.id,
        updateAvailable: false,
        status: "completed",
      });
      expect((await store.run(original.id))?.status).toBe("completed");
    } finally {
      await app.close();
    }
  });
});
