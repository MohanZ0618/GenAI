import { describe, expect, it } from "vitest";
import {
  runInvestigationQueue,
  hydrateSavedResults,
  type QueueUpdate,
} from "../apps/web/src/investigationQueue";
import type { api, Case, Investigation } from "../apps/web/src/api";

const item = (index: number): Case => ({
  id: `case-${index}`,
  datasetId: "dataset",
  paymentId: `payment-${index}`,
  vendor: "Vendor",
  amount: "100",
  currency: "USD",
  date: "2026-06-01",
  symptom: "Review",
  status: "unreviewed",
});
const run = (
  entry: Case,
  status: Investigation["status"] = "completed",
): Investigation => ({
  id: `run-${entry.id}`,
  datasetId: entry.datasetId,
  paymentId: entry.paymentId,
  status,
  mode: "fixture",
  provider: "fixture",
  model: "none",
  createdAt: "2026-06-01",
  updatedAt: "2026-06-01",
  outcome: status === "completed" ? "no_anomaly_supported" : null,
  findings: [],
  checks: [],
  actions: [],
  evidence: [],
  events: [],
  queries: [],
  memories: [],
  modelTurns: 0,
});

describe("serial investigation queue", () => {
  it("reads three saved results, starts only five new cases, and finishes each before starting the next", async () => {
    const items = Array.from({ length: 8 }, (_, index) =>
      index < 3
        ? {
            ...item(index),
            status: "completed",
            investigationId: `run-case-${index}`,
          }
        : item(index),
    );
    const posts: string[] = [];
    const updates: QueueUpdate[] = [];
    let active = 0;
    let peak = 0;
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      if (options?.method === "POST") {
        expect(path).toBe("/investigations");
        expect(active).toBe(0);
        const entry = items.find(
          (entry) =>
            entry.paymentId === JSON.parse(options.body as string).paymentId,
        )!;
        posts.push(entry.id);
        active++;
        peak = Math.max(peak, active);
        return run(entry, "queued") as T;
      }
      const entry = items.find((entry) => path.endsWith(`run-${entry.id}`))!;
      return run(entry, entry.id === "case-5" ? "failed" : "completed") as T;
    };
    await runInvestigationQueue(
      [...items, items[3]],
      (update) => {
        if (
          update.phase === "finished" &&
          !["case-0", "case-1", "case-2"].includes(update.item.id)
        )
          active--;
        updates.push(update);
      },
      { request, wait: async () => {} },
    );
    expect(posts).toEqual(["case-3", "case-4", "case-5", "case-6", "case-7"]);
    expect(peak).toBe(1);
    expect(
      updates.filter((update) => update.phase === "finished"),
    ).toHaveLength(8);
    expect(
      updates.find(
        (update) => update.item.id === "case-0" && update.phase === "finished",
      )?.item.outcome,
    ).toBe("no_anomaly_supported");
  });

  it("does not rerun a completed case whose saved ID is unavailable, and continues after a start failure", async () => {
    const items = [{ ...item(0), status: "completed" }, item(1), item(2)];
    const posts: string[] = [];
    const updates: QueueUpdate[] = [];
    const request: typeof api = async <T>(
      _path: string,
      options?: RequestInit,
    ) => {
      const entry = items.find(
        (entry) =>
          entry.paymentId === JSON.parse(options!.body as string).paymentId,
      )!;
      posts.push(entry.id);
      if (entry.id === "case-1") throw new Error("Start rejected");
      return run(entry) as T;
    };
    await runInvestigationQueue(items, (update) => updates.push(update), {
      request,
    });
    expect(posts).toEqual(["case-1", "case-2"]);
    expect(updates.filter((update) => update.phase === "error")).toHaveLength(
      2,
    );
    expect(updates.at(-1)?.item.status).toBe("completed");
  });

  it("reconnects to an existing run and pauses later starts if its status cannot be confirmed", async () => {
    const items = [
      { ...item(0), status: "running", investigationId: "existing" },
      item(1),
    ];
    let reads = 0;
    let posts = 0;
    const updates: QueueUpdate[] = [];
    const request: typeof api = async <T>(
      _path: string,
      options?: RequestInit,
    ) => {
      if (options?.method === "POST") posts++;
      reads++;
      if (reads > 1) throw new Error("Connection lost");
      return { ...run(items[0], "running"), id: "existing" } as T;
    };
    await runInvestigationQueue(items, (update) => updates.push(update), {
      request,
      wait: async () => {},
    });
    expect(posts).toBe(0);
    expect(reads).toBe(4);
    expect(updates.at(-1)?.error).toContain("Not started");
  });

  it("hydrates outcomes missing from legacy case lists through read-only requests", async () => {
    const items = [
      { ...item(0), status: "completed", investigationId: "run-case-0" },
      { ...item(1), status: "reviewed", investigationId: "missing" },
      item(2),
    ];
    const paths: string[] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      expect(options?.method).toBeUndefined();
      paths.push(path);
      if (path.endsWith("missing")) throw new Error("Unavailable");
      return run(items[0]) as T;
    };
    const results = await hydrateSavedResults(items, { request });
    expect(results[0].outcome).toBe("no_anomaly_supported");
    expect(results[1]).toEqual(items[1]);
    expect(results[2]).toEqual(items[2]);
    expect(paths).toHaveLength(2);
  });
});
