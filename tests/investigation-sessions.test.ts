import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createInvestigationSessions } from "../apps/web/src/useInvestigationSessions";
import type { api, Case, Investigation } from "../apps/web/src/api";

const payment = (name: string): Case => ({
  id: `case-${name}`,
  datasetId: "dataset",
  paymentId: `PAY_${name}`,
  vendor: `Vendor ${name}`,
  amount: "100.00",
  currency: "USD",
  date: "2026-06-01",
  symptom: "Review requested",
  status: "unreviewed",
});

const run = (
  item: Case,
  status: Investigation["status"] = "running",
  overrides: Partial<Investigation> = {},
): Investigation => ({
  id: `run-${item.id}`,
  datasetId: item.datasetId,
  paymentId: item.paymentId,
  status,
  mode: "fixture",
  provider: "deterministic-fixture",
  model: "none",
  createdAt: "2026-06-01T10:00:00Z",
  updatedAt: "2026-06-01T10:00:00Z",
  outcome: status === "completed" ? "no_anomaly_supported" : null,
  findings: [],
  checks: [],
  actions: [],
  evidence: [],
  events: [],
  queries: [],
  memories: [],
  modelTurns: 0,
  ...overrides,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

const controllers: ReturnType<typeof createInvestigationSessions>[] = [];
function controller(request: typeof api, onRun = vi.fn()) {
  const sessions = createInvestigationSessions({ request, onRun });
  sessions.start();
  controllers.push(sessions);
  return sessions;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  for (const sessions of controllers.splice(0)) sessions.stop();
  vi.useRealTimers();
});

describe("independent investigation sessions", () => {
  it("opens pending windows synchronously and keeps a slow A response independent of a fast B", async () => {
    const a = payment("A");
    const b = payment("B");
    const slow = deferred<Investigation>();
    const seen = vi.fn();
    const calls: string[] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      expect(path).toBe("/investigations");
      expect(options?.method).toBe("POST");
      const id = JSON.parse(options!.body as string).paymentId;
      calls.push(id);
      return (id === a.paymentId ? await slow.promise : run(b)) as T;
    };
    const sessions = controller(request, seen);
    const keyA = sessions.open(a);
    expect(keyA).toBe(JSON.stringify([a.datasetId, a.paymentId]));
    expect(sessions.getSnapshot()[keyA]).toMatchObject({
      pending: true,
      fresh: true,
      payment: a,
    });
    expect(sessions.open(a)).toBe(keyA);
    const keyB = sessions.open(b);
    await flush();
    expect(sessions.getSnapshot()[keyB].run?.paymentId).toBe(b.paymentId);
    expect(sessions.getSnapshot()[keyA].run).toBeUndefined();
    slow.resolve(run(a));
    await flush();
    expect(sessions.getSnapshot()[keyA].run?.paymentId).toBe(a.paymentId);
    expect(sessions.getSnapshot()[keyB].run?.paymentId).toBe(b.paymentId);
    expect(calls).toEqual([a.paymentId, b.paymentId]);
    expect(seen.mock.calls.map(([value]) => value.paymentId)).toEqual([
      b.paymentId,
      a.paymentId,
    ]);
  });

  it("continues polling cached runs when their window unsubscribes and reuses completed results on reopen", async () => {
    const a = payment("A");
    const b = payment("B");
    const posts: string[] = [];
    const reads: string[] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      if (options?.method === "POST") {
        const id = JSON.parse(options.body as string).paymentId;
        posts.push(id);
        return run(id === a.paymentId ? a : b) as T;
      }
      reads.push(path);
      return run(path.endsWith(`run-${a.id}`) ? a : b, "completed") as T;
    };
    const sessions = controller(request);
    const render = vi.fn();
    const closeWindow = sessions.subscribe(render);
    const keyA = sessions.open(a);
    const keyB = sessions.open(b);
    await flush();
    closeWindow();
    const beforeClosing = render.mock.calls.length;
    await vi.advanceTimersByTimeAsync(1500);
    expect(sessions.getSnapshot()[keyA].run?.status).toBe("completed");
    expect(sessions.getSnapshot()[keyB].run?.status).toBe("completed");
    expect(render).toHaveBeenCalledTimes(beforeClosing);
    expect(sessions.open(a)).toBe(keyA);
    expect(sessions.getSnapshot()[keyA].fresh).toBe(true);
    await vi.advanceTimersByTimeAsync(4500);
    expect(posts).toEqual([a.paymentId, b.paymentId]);
    expect(reads).toHaveLength(2);
  });

  it("gets saved or resumed runs without POST and associates a metadata-free resume with its payment", async () => {
    const a = payment("A");
    const b = payment("B");
    const savedA = run(a, "completed");
    const savedB = run(b, "completed");
    const calls: [string, string][] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      calls.push([options?.method ?? "GET", path]);
      return (path.endsWith(savedA.id) ? savedA : savedB) as T;
    };
    const sessions = controller(request);
    const keyA = sessions.open({
      ...a,
      investigationId: savedA.id,
      status: "reviewed",
    });
    const keyB = sessions.resume(savedB.id);
    expect(keyB).toBe(`run:${savedB.id}`);
    await flush();
    expect(sessions.getSnapshot()[keyA]).toMatchObject({
      fresh: false,
      pending: false,
      run: savedA,
    });
    expect(sessions.open(b)).toBe(keyB);
    expect(sessions.getSnapshot()[keyB].payment).toEqual(b);
    expect(sessions.getSnapshot()[keyB].fresh).toBe(false);
    expect(sessions.resume(savedB.id, b)).toBe(keyB);
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls).toEqual([
      ["GET", `/investigations/${savedA.id}`],
      ["GET", `/investigations/${savedB.id}`],
    ]);
  });

  it("does not overlap polls for one run or stall another run behind a slow request", async () => {
    const a = payment("A");
    const b = payment("B");
    const slow = deferred<Investigation>();
    const reads: string[] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      if (options?.method === "POST")
        return run(
          JSON.parse(options.body as string).paymentId === a.paymentId ? a : b,
        ) as T;
      reads.push(path);
      return (
        path.endsWith(`run-${a.id}`) ? await slow.promise : run(b, "completed")
      ) as T;
    };
    const sessions = controller(request);
    const keyA = sessions.open(a);
    const keyB = sessions.open(b);
    await flush();
    await vi.advanceTimersByTimeAsync(4500);
    expect(reads).toEqual([
      `/investigations/run-${a.id}`,
      `/investigations/run-${b.id}`,
    ]);
    expect(sessions.getSnapshot()[keyB].run?.status).toBe("completed");
    slow.resolve(run(a, "completed"));
    await flush();
    expect(sessions.getSnapshot()[keyA].run?.status).toBe("completed");
  });

  it("animates a newly resumed active GET session while completed GET sessions stay direct", async () => {
    const a = payment("A");
    const b = payment("B");
    let completed = false;
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      expect(options?.method).not.toBe("POST");
      return run(
        path.endsWith(`run-${a.id}`) ? a : b,
        path.endsWith(`run-${a.id}`) && !completed ? "running" : "completed",
      ) as T;
    };
    const sessions = controller(request);
    const keyA = sessions.resume(`run-${a.id}`, a);
    const keyB = sessions.resume(`run-${b.id}`, b);
    await flush();
    expect(sessions.getSnapshot()[keyA].fresh).toBe(true);
    expect(sessions.getSnapshot()[keyB].fresh).toBe(false);
    completed = true;
    await vi.advanceTimersByTimeAsync(1500);
    expect(sessions.getSnapshot()[keyA].run?.status).toBe("completed");
    expect(sessions.getSnapshot()[keyA].fresh).toBe(true);
    expect(sessions.open(a)).toBe(keyA);
    expect(sessions.getSnapshot()[keyA].fresh).toBe(true);
  });

  it("takes the cancellation POST response and ignores an older in-flight poll", async () => {
    const a = payment("A");
    const olderPoll = deferred<Investigation>();
    const cancelled = run(a, "cancelled", {
      updatedAt: "2026-06-01T10:00:02Z",
    });
    const calls: [string, string][] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      calls.push([options?.method ?? "GET", path]);
      if (path.endsWith("/cancel")) return cancelled as T;
      if (options?.method === "POST") return run(a) as T;
      return (await olderPoll.promise) as T;
    };
    const sessions = controller(request);
    const key = sessions.open(a);
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    await sessions.cancel(key);
    expect(sessions.getSnapshot()[key]).toMatchObject({
      run: cancelled,
      cancelling: false,
    });
    olderPoll.resolve(run(a, "running", { updatedAt: "2026-06-01T10:00:03Z" }));
    await flush();
    await vi.advanceTimersByTimeAsync(3000);
    expect(sessions.getSnapshot()[key].run).toEqual(cancelled);
    expect(calls).toEqual([
      ["POST", "/investigations"],
      ["GET", `/investigations/run-${a.id}`],
      ["POST", `/investigations/run-${a.id}/cancel`],
    ]);
  });

  it("keeps a reviewed snapshot when an older poll finishes or updateRun receives an older record", async () => {
    const a = payment("A");
    const olderPoll = deferred<Investigation>();
    const request: typeof api = async <T>(
      _path: string,
      options?: RequestInit,
    ) => (options?.method === "POST" ? run(a) : await olderPoll.promise) as T;
    const sessions = controller(request);
    const key = sessions.open(a);
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    const reviewed = run(a, "completed", {
      updatedAt: "2026-06-01T10:00:02Z",
      review: {
        decision: "accepted",
        notes: "Confirmed source records",
        at: "2026-06-01T10:00:02Z",
      },
    });
    sessions.updateRun(reviewed);
    olderPoll.resolve(
      run(a, "completed", { updatedAt: "2026-06-01T10:00:03Z" }),
    );
    await flush();
    sessions.updateRun(
      run(a, "completed", { updatedAt: "2026-06-01T10:00:04Z" }),
    );
    expect(sessions.getSnapshot()[key].run).toEqual(reviewed);
  });

  it("preserves API errors and retries a saved result with GET rather than starting a paid run", async () => {
    const a = payment("A");
    const calls: [string, string][] = [];
    const request: typeof api = async <T>(
      path: string,
      options?: RequestInit,
    ) => {
      calls.push([options?.method ?? "GET", path]);
      if (calls.length === 1)
        throw new Error("Saved result is temporarily unavailable");
      return run(a, "completed") as T;
    };
    const sessions = controller(request);
    const key = sessions.open({
      ...a,
      status: "completed",
      investigationId: `run-${a.id}`,
    });
    await flush();
    expect(sessions.getSnapshot()[key]).toMatchObject({
      fresh: false,
      pending: false,
      error: "Saved result is temporarily unavailable",
    });
    sessions.retry(key);
    await flush();
    expect(sessions.getSnapshot()[key]).toMatchObject({
      fresh: false,
      error: "",
      run: { status: "completed" },
    });
    expect(calls).toEqual([
      ["GET", `/investigations/run-${a.id}`],
      ["GET", `/investigations/run-${a.id}`],
    ]);
  });

  it("keeps retries, dataset versions and late updates of an older run independent", async () => {
    const a = payment("A");
    let postCount = 0;
    const request: typeof api = async <T>(
      _path: string,
      options?: RequestInit,
    ) => {
      const body = JSON.parse(options!.body as string);
      postCount++;
      return run(
        { ...a, datasetId: body.datasetId },
        postCount === 1 ? "cancelled" : "running",
        { id: `attempt-${postCount}` },
      ) as T;
    };
    const sessions = controller(request);
    const key = sessions.open(a);
    await flush();
    expect(sessions.getSnapshot()[key].run?.status).toBe("cancelled");
    expect(sessions.open(a)).toBe(key);
    await flush();
    expect(postCount).toBe(1);
    expect(sessions.getSnapshot()[key].run?.status).toBe("cancelled");
    sessions.retry(key);
    await flush();
    expect(sessions.getSnapshot()[key].run?.id).toBe("attempt-2");
    sessions.updateRun(run(a, "cancelled", { id: "attempt-1" }));
    expect(sessions.getSnapshot()[key].run?.id).toBe("attempt-2");
    const newerVersion = sessions.open({
      ...a,
      datasetId: "dataset-v2",
      updateAvailable: true,
    });
    expect(newerVersion).not.toBe(key);
    await flush();
    expect(sessions.getSnapshot()[newerVersion].run?.datasetId).toBe(
      "dataset-v2",
    );
    expect(sessions.getSnapshot()[key].fresh).toBe(true);
    expect(postCount).toBe(3);
  });

  it("retains a cached snapshot through polling errors and rejects a shorter event history", async () => {
    const a = payment("A");
    const initial = run(a, "running", {
      events: [
        {
          id: "event-1",
          at: "2026-06-01T10:00:00Z",
          type: "planning",
          message: "Started",
        },
      ],
    });
    let reads = 0;
    const request: typeof api = async <T>(
      _path: string,
      options?: RequestInit,
    ) => {
      if (options?.method === "POST") return initial as T;
      reads++;
      if (reads === 1) throw new Error("Connection interrupted");
      return { ...initial, updatedAt: "2026-06-01T10:00:03Z" } as T;
    };
    const sessions = controller(request);
    const key = sessions.open(a);
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(sessions.getSnapshot()[key].run).toEqual(initial);
    expect(sessions.getSnapshot()[key].stale).toContain(
      "Connection interrupted",
    );
    await vi.advanceTimersByTimeAsync(1500);
    expect(sessions.getSnapshot()[key].stale).toBe("");
    sessions.updateRun(
      run(a, "running", { updatedAt: "2026-06-01T10:00:04Z", events: [] }),
    );
    expect(sessions.getSnapshot()[key].run?.events).toHaveLength(1);
  });

  it("indexes a newer externally updated run while keeping its older cached run intact", async () => {
    const a = payment("A");
    const request: typeof api = async <T>() => run(a, "completed") as T;
    const sessions = controller(request);
    const previousKey = sessions.open(a);
    await flush();
    const newer = run(a, "completed", {
      id: "newer-run",
      createdAt: "2026-06-02T10:00:00Z",
      updatedAt: "2026-06-02T10:00:01Z",
    });
    sessions.updateRun(newer);
    const nextKey = sessions.open(a);
    expect(nextKey).not.toBe(previousKey);
    expect(sessions.getSnapshot()[nextKey].run).toEqual(newer);
    expect(sessions.getSnapshot()[previousKey].run?.id).toBe(`run-${a.id}`);
  });
});
