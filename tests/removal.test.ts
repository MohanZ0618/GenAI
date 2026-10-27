import { describe, expect, it, vi } from "vitest";
import { mkdir, mkdtemp } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createApp } from "../apps/api/src/server.ts";
import { FileStore } from "../apps/api/src/store.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import { buildManualPackets } from "../scripts/prepare_openai_manual.ts";

async function setup() {
  await mkdir(".local", { recursive: true });
  const dir = await mkdtemp(resolve(".local/removal-test-"));
  const store = new FileStore(dir);
  await store.init();
  const dataset = await store.saveDataset(buildManualPackets().main, true);
  const context = await createApp({
    store,
    storageDir: dir,
    mode: "fixture",
    seed: false,
  });
  return { ...context, dir, dataset };
}

describe("recoverable removal", () => {
  it("serializes removal with investigation starts for the same dataset", async () => {
    const { app, service, store, dataset } = await setup();
    let release!: () => void;
    let entered!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const ready = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const update = store.setDatasetRemoved.bind(store);
    const updateSpy = vi
      .spyOn(store, "setDatasetRemoved")
      .mockImplementation(async (id, removed) => {
        entered();
        await gate;
        await update(id, removed);
      });
    try {
      const removing = app.inject({
        method: "POST",
        url: "/api/datasets/removal",
        payload: { ids: [dataset.info.id], removed: true },
      });
      await ready;
      const readSpy = vi.spyOn(store, "dataset");
      const starting = service.start(dataset.info.id, "PAY_DEMO_DUP");
      const rejected = expect(starting).rejects.toThrow("removed dataset");
      await new Promise<void>((resolve) => setImmediate(resolve));
      expect(readSpy).not.toHaveBeenCalled();
      release();
      expect((await removing).json().results[0].success).toBe(true);
      await rejected;
      readSpy.mockRestore();
    } finally {
      release();
      updateSpy.mockRestore();
      await app.close();
    }
  });
  it("hides datasets and cases, preserves source data and historical exports across restart, and supports undo", async () => {
    const { app, service, store, dir, dataset } = await setup();
    try {
      const run = await service.wait(
        (await service.start(dataset.info.id, "PAY_DEMO_DUP")).id,
      );
      const remove = await app.inject({
        method: "POST",
        url: "/api/datasets/removal",
        payload: { ids: [dataset.info.id, "missing"], removed: true },
      });
      expect(
        remove.json().results.map((item: { success: boolean }) => item.success),
      ).toEqual([true, false]);
      expect((await app.inject("/api/datasets")).json().datasets).toEqual([]);
      expect(
        (await app.inject(`/api/datasets/${dataset.info.id}`)).json().dataset,
      ).toMatchObject({
        name: dataset.info.name,
        removedAt: expect.any(String),
      });
      expect(
        (await app.inject("/api/cases?datasetId=all")).json().cases,
      ).toEqual([]);
      expect(
        (await app.inject(`/api/cases?datasetId=${dataset.info.id}`))
          .statusCode,
      ).toBe(400);
      expect(
        (await app.inject(`/api/investigations/${run.id}`)).json().evidence,
      ).toEqual(run.evidence);
      expect(
        (await app.inject(`/api/investigations/${run.id}/export?format=json`))
          .statusCode,
      ).toBe(200);
      await expect(
        service.start(dataset.info.id, "PAY_DEMO_NORMAL"),
      ).rejects.toThrow("removed dataset");
      const reopened = new FileStore(dir);
      await reopened.init();
      await reopened.saveDataset(buildManualPackets().main, true);
      expect(
        (await reopened.dataset(dataset.info.id))?.info.removedAt,
      ).toBeTruthy();
      expect((await reopened.dataset(dataset.info.id))?.data).toEqual(
        dataset.data,
      );
      const undo = await app.inject({
        method: "POST",
        url: "/api/datasets/removal",
        payload: { ids: [dataset.info.id], removed: false },
      });
      expect(undo.json().results[0].success).toBe(true);
      expect((await app.inject("/api/datasets")).json().datasets).toHaveLength(
        1,
      );
      expect((await store.dataset(dataset.info.id))?.info.removedAt).toBeNull();
    } finally {
      await app.close();
    }
  });

  it("reports active datasets individually without changing them and validates batch input", async () => {
    const { app, service, store, dataset } = await setup();
    try {
      const run = await service.wait(
        (await service.start(dataset.info.id, "PAY_DEMO_DUP")).id,
      );
      run.status = "running";
      await store.saveRun(run);
      const result = await app.inject({
        method: "POST",
        url: "/api/datasets/removal",
        payload: { ids: [dataset.info.id], removed: true },
      });
      expect(result.json().results[0]).toMatchObject({
        success: false,
        error: expect.stringContaining("active investigation"),
      });
      expect(
        (await store.dataset(dataset.info.id))?.info.removedAt,
      ).toBeUndefined();
      expect(
        (
          await app.inject({
            method: "POST",
            url: "/api/datasets/removal",
            payload: { ids: [], removed: true },
          })
        ).statusCode,
      ).toBe(400);
    } finally {
      await app.close();
    }
  });

  it("removes memories from recall while retaining snapshots, provenance and the previous status on undo", async () => {
    const { app, service, store, dir, dataset } = await setup();
    try {
      const memory = service.memory;
      const active = await memory.approve(
        "workspace",
        "Review payment allocations before accepting duplicate payment results.",
        "independent-source",
      );
      const inactive = await memory.approve(
        "workspace",
        "Review payment ledger before accepting duplicate payment results.",
        "inactive-source",
      );
      memory.setStatus("workspace", inactive.id, "inactive");
      const run = await service.wait(
        (await service.start(dataset.info.id, "PAY_DEMO_DUP")).id,
      );
      expect(
        run.memories?.some((item) => (item as { id: string }).id === active.id),
      ).toBe(true);
      const before = structuredClone(run.memories);
      const response = await app.inject({
        method: "POST",
        url: "/api/memories/removal",
        payload: { ids: [active.id, inactive.id, "missing"], removed: true },
      });
      expect(
        response
          .json()
          .results.map((item: { success: boolean }) => item.success),
      ).toEqual([true, true, false]);
      expect((await app.inject("/api/memories")).json().memories).toHaveLength(
        0,
      );
      expect(
        await memory.recall("workspace", "payment allocations duplicate"),
      ).toHaveLength(0);
      expect((await store.run(run.id))?.memories).toEqual(before);
      const reopened = new MemoryService(join(dir, "memory"));
      expect(reopened.list()).toHaveLength(2);
      expect(
        await reopened.recall("workspace", "payment allocations duplicate"),
      ).toHaveLength(0);
      const undo = await app.inject({
        method: "POST",
        url: "/api/memories/removal",
        payload: { ids: [active.id, inactive.id], removed: false },
      });
      expect(
        undo.json().results.every((item: { success: boolean }) => item.success),
      ).toBe(true);
      expect(memory.list().find((item) => item.id === active.id)?.status).toBe(
        "active",
      );
      expect(
        memory.list().find((item) => item.id === inactive.id)?.status,
      ).toBe("inactive");
      expect(
        (await memory.recall("workspace", "payment allocations duplicate")).map(
          (item) => item.id,
        ),
      ).toContain(active.id);
      expect((await store.run(run.id))?.memories).toEqual(before);
    } finally {
      await app.close();
    }
  });
});
