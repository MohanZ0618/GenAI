import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createApp } from "../apps/api/src/server.ts";
import { FileStore } from "../apps/api/src/store.ts";
import { buildManualPackets } from "../scripts/prepare_openai_manual.ts";
import type {
  Investigation,
  InvestigationSummary,
} from "../packages/contracts/src/index.ts";

const contexts: Array<{
  dir: string;
  app: Awaited<ReturnType<typeof createApp>>["app"];
}> = [];

afterEach(async () => {
  for (const { app, dir } of contexts.splice(0)) {
    await app.close();
    await rm(dir, { recursive: true, force: true });
  }
  vi.restoreAllMocks();
});

async function setup() {
  const dir = await mkdtemp(join(tmpdir(), "fintrace-history-"));
  const store = new FileStore(dir);
  const { app } = await createApp({
    store,
    storageDir: dir,
    mode: "fixture",
    seed: false,
  });
  contexts.push({ app, dir });
  const dataset = await store.saveDataset(buildManualPackets().main);
  return { app, dir, store, dataset };
}

function run(
  datasetId: string,
  overrides: Partial<Investigation> = {},
): Investigation {
  return {
    id: "history-run",
    datasetId,
    paymentId: "PAY_DEMO_NORMAL",
    status: "completed",
    mode: "fixture",
    provider: "deterministic-fixture",
    model: "none",
    createdAt: "2026-10-27T12:00:00Z",
    updatedAt: "2026-10-27T12:05:00Z",
    outcome: "no_anomaly_supported",
    findings: [],
    checks: [],
    actions: [],
    evidence: [],
    events: [],
    queries: [],
    memories: [],
    modelTurns: 0,
    ...overrides,
  };
}

async function list(app: Awaited<ReturnType<typeof createApp>>["app"]) {
  const response = await app.inject("/api/investigations");
  expect(response.statusCode).toBe(200);
  return response.json<{ investigations: InvestigationSummary[] }>()
    .investigations;
}

describe("saved investigation history", () => {
  it("keeps each saved run and status, newest first, without mutating history or exposing full payloads", async () => {
    const { app, store, dataset } = await setup();
    const statuses: Investigation["status"][] = [
      "completed",
      "failed",
      "cancelled",
      "running",
      "queued",
    ];
    for (const [index, status] of statuses.entries())
      await store.saveRun(
        run(dataset.info.id, {
          id: `history-${index}`,
          status,
          createdAt: `2026-10-27T12:0${index}:00Z`,
          review:
            index === 0
              ? {
                  decision: "accepted",
                  notes: "Checked source records.",
                  at: "2026-10-27T13:00:00Z",
                  memoryId: "not-part-of-list",
                }
              : undefined,
        }),
      );
    const before = await store.runs();
    const save = vi.spyOn(store, "saveRun");
    const datasetRead = vi.spyOn(store, "dataset");
    const datasetList = vi.spyOn(store, "datasets");
    const history = await list(app);
    expect(history.map((item) => item.id)).toEqual([
      "history-4",
      "history-3",
      "history-2",
      "history-1",
      "history-0",
    ]);
    expect(history.map((item) => item.status)).toEqual([...statuses].reverse());
    expect(new Set(history.map((item) => item.paymentId)).size).toBe(1);
    expect(history[4]).toMatchObject({
      vendor: "Synthetic NORMAL Supplier",
      question: "Reconciliation review requested",
      datasetName: dataset.info.name,
      datasetVersion: dataset.info.version,
      datasetRemoved: false,
      outcome: "no_anomaly_supported",
      review: {
        decision: "accepted",
        notes: "Checked source records.",
        at: "2026-10-27T13:00:00Z",
      },
    });
    expect(history.slice(0, 4).every((item) => item.outcome === null)).toBe(
      true,
    );
    for (const field of ["evidence", "events", "queries", "modelRequests"])
      expect(history[4]).not.toHaveProperty(field);
    expect(history[4].review).not.toHaveProperty("memoryId");
    expect(save).not.toHaveBeenCalled();
    expect(datasetRead).not.toHaveBeenCalled();
    expect(datasetList).toHaveBeenCalledTimes(1);
    expect(await store.runs()).toEqual(before);
    expect(await list(app)).toEqual(history);
  });

  it("matches current mode and workspace scope, with deterministic ordering for equal timestamps", async () => {
    const { app, store, dataset } = await setup();
    for (const overrides of [
      { id: "tie-z", memoryNamespace: "workspace" },
      { id: "tie-a" },
      { id: "other-namespace", memoryNamespace: "hmem-demo" },
      { id: "other-mode", mode: "local-model" as const },
    ])
      await store.saveRun(run(dataset.info.id, overrides));
    expect((await list(app)).map((item) => item.id)).toEqual([
      "tie-a",
      "tie-z",
    ]);
  });

  it("keeps removed snapshots and falls back to saved evidence when source metadata is unavailable", async () => {
    const { app, store, dataset } = await setup();
    await store.setDatasetRemoved(dataset.info.id, true);
    await store.saveRun(run(dataset.info.id, { id: "removed-source" }));
    await store.saveRun(
      run("missing-snapshot", {
        id: "missing-source",
        evidence: [
          {
            id: "saved-payment",
            table: "payments",
            recordId: "PAY_DEMO_NORMAL",
            queryId: "original-query",
            datasetVersion: "saved-snapshot-version",
            record: {
              payment_id: "PAY_DEMO_NORMAL",
              vendor_id: "SAVED_VENDOR",
            },
          },
          {
            id: "saved-vendor",
            table: "vendors",
            recordId: "SAVED_VENDOR",
            queryId: "original-query",
            datasetVersion: "saved-snapshot-version",
            record: {
              vendor_id: "SAVED_VENDOR",
              vendor_name: "Original saved supplier",
            },
          },
        ],
      }),
    );
    await store.saveRun(run("also-missing", { id: "no-source-or-evidence" }));
    const history = await list(app);
    expect(history.find((item) => item.id === "removed-source")).toMatchObject({
      datasetRemoved: true,
      datasetName: dataset.info.name,
      datasetVersion: dataset.info.version,
      vendor: "Synthetic NORMAL Supplier",
    });
    expect(history.find((item) => item.id === "missing-source")).toMatchObject({
      datasetName: "missing-snapshot",
      datasetVersion: "saved-snapshot-version",
      vendor: "Original saved supplier",
      question: "Payment reconciliation review",
      datasetRemoved: false,
    });
    expect(
      history.find((item) => item.id === "no-source-or-evidence"),
    ).toMatchObject({
      datasetName: "also-missing",
      datasetVersion: "",
      vendor: "Vendor unavailable",
    });
  });

  it("reflects saved and edited human reviews after reopening the persistent store", async () => {
    const { app, store, dataset, dir } = await setup();
    await store.saveRun(run(dataset.info.id));
    for (const [decision, notes] of [
      ["accepted", "Matched the bank evidence."],
      ["needs_changes", "Please explain the settlement difference."],
    ] as const) {
      const response = await app.inject({
        method: "POST",
        url: "/api/investigations/history-run/review",
        payload: { decision, notes, approveMemory: false },
      });
      expect(response.statusCode).toBe(200);
      expect((await list(app))[0].review).toMatchObject({ decision, notes });
    }
    await app.close();
    const reopened = await createApp({
      store: new FileStore(dir),
      storageDir: dir,
      mode: "fixture",
      seed: false,
    });
    contexts[contexts.length - 1].app = reopened.app;
    expect((await list(reopened.app))[0]).toMatchObject({
      id: "history-run",
      review: {
        decision: "needs_changes",
        notes: "Please explain the settlement difference.",
      },
    });
    expect(await reopened.store.runs()).toHaveLength(1);
  });
});
