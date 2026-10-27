import { useEffect, useRef, useSyncExternalStore } from "react";
import { api } from "./api";
import type { Case, Investigation } from "./api";

export type InvestigationSession = {
  key: string;
  payment?: Case;
  run?: Investigation;
  pending: boolean;
  error: string;
  stale: string;
  fresh: boolean;
  cancelling: boolean;
};

type Options = { onRun?: (run: Investigation) => void };
type ControllerOptions = Options & {
  request?: typeof api;
  pollInterval?: number;
};
type Action =
  | { method: "GET"; runId: string }
  | { method: "POST"; datasetId: string; paymentId: string };

const active = (run: Investigation | undefined) =>
  run?.status === "queued" || run?.status === "running";
const caseKey = (payment: Pick<Case, "datasetId" | "paymentId">) =>
  JSON.stringify([payment.datasetId, payment.paymentId]);
const time = (value: string | undefined) => {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? parsed : 0;
};

/** Reject older snapshots even when the server timestamps share a millisecond. */
function follows(previous: Investigation | undefined, next: Investigation) {
  if (!previous || previous.id !== next.id) return true;
  if (!active(previous) && previous.status !== next.status) return false;
  if (time(next.updatedAt) < time(previous.updatedAt)) return false;
  if (next.events.length < previous.events.length) return false;
  if (
    previous.review &&
    (!next.review || time(next.review.at) < time(previous.review.at))
  )
    return false;
  return true;
}

/** Independent sessions, with no dependency on the currently visible window. */
export function createInvestigationSessions(options: ControllerOptions = {}) {
  const request = options.request ?? api;
  let sessions: Record<string, InvestigationSession> = {};
  const listeners = new Set<() => void>();
  const cases = new Map<string, string>();
  const runs = new Map<string, string>();
  const revisions = new Map<string, number>();
  const actions = new Map<string, Action>();
  const polling = new Set<string>();
  const cancellations = new Map<string, Promise<void>>();
  let enabled = false;
  let timer: ReturnType<typeof setInterval> | undefined;

  function revision(key: string) {
    const next = (revisions.get(key) ?? 0) + 1;
    revisions.set(key, next);
    return next;
  }

  function syncTimer() {
    const needsPolling =
      enabled && Object.values(sessions).some((s) => active(s.run));
    if (needsPolling && timer === undefined)
      timer = setInterval(() => {
        for (const session of Object.values(sessions)) void poll(session.key);
      }, options.pollInterval ?? 1500);
    else if (!needsPolling && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  }

  function set(key: string, patch: Partial<InvestigationSession>) {
    sessions = { ...sessions, [key]: { ...sessions[key], ...patch } };
    syncTimer();
    for (const listener of listeners) listener();
  }

  function create(key: string, payment?: Case) {
    if (sessions[key]) return;
    set(key, {
      key,
      payment,
      pending: false,
      error: "",
      stale: "",
      fresh: false,
      cancelling: false,
    });
  }

  function receive(
    key: string,
    run: Investigation,
    token: number,
    replace = false,
    fresh?: boolean,
  ) {
    const session = sessions[key];
    if (!session || revisions.get(key) !== token) return false;
    if (session.run && session.run.id !== run.id && !replace) return false;
    if (
      session.payment &&
      (session.payment.datasetId !== run.datasetId ||
        session.payment.paymentId !== run.paymentId)
    )
      throw new Error("The investigation does not match the selected payment.");
    if (!follows(session.run, run)) return false;
    if (
      session.run &&
      session.run.id !== run.id &&
      runs.get(session.run.id) === key
    )
      runs.delete(session.run.id);
    runs.set(run.id, key);
    const indexed = cases.get(caseKey(run));
    const indexedSession = indexed ? sessions[indexed] : undefined;
    if (
      !indexedSession ||
      indexed === key ||
      (!indexedSession.pending &&
        indexedSession.run &&
        time(run.createdAt) > time(indexedSession.run.createdAt))
    )
      cases.set(caseKey(run), key);
    set(key, {
      run,
      pending: false,
      error: "",
      stale: "",
      ...(fresh === undefined ? {} : { fresh }),
    });
    options.onRun?.(run);
    return true;
  }

  async function launch(key: string, action: Action) {
    actions.set(key, action);
    const token = revision(key);
    set(key, {
      pending: true,
      error: "",
      stale: "",
      fresh: action.method === "POST",
    });
    try {
      const run =
        action.method === "GET"
          ? await request<Investigation>(
              `/investigations/${encodeURIComponent(action.runId)}`,
            )
          : await request<Investigation>("/investigations", {
              method: "POST",
              body: JSON.stringify({
                datasetId: action.datasetId,
                paymentId: action.paymentId,
              }),
            });
      if (action.method === "GET" && run.id !== action.runId)
        throw new Error(
          "The investigation response did not match the requested run.",
        );
      receive(
        key,
        run,
        token,
        action.method === "POST",
        action.method === "POST" || active(run),
      );
    } catch (error) {
      if (revisions.get(key) === token)
        set(key, {
          pending: false,
          error:
            error instanceof Error
              ? error.message
              : "Could not open investigation.",
        });
    } finally {
      if (revisions.get(key) === token && sessions[key]?.pending)
        set(key, { pending: false });
    }
  }

  async function poll(key: string) {
    const session = sessions[key];
    const run = session?.run;
    if (
      !active(run) ||
      !run ||
      session.pending ||
      session.cancelling ||
      polling.has(run.id)
    )
      return;
    const token = revisions.get(key) ?? 0;
    polling.add(run.id);
    try {
      const next = await request<Investigation>(
        `/investigations/${encodeURIComponent(run.id)}`,
      );
      if (next.id !== run.id)
        throw new Error(
          "The investigation response did not match the requested run.",
        );
      receive(key, next, token);
    } catch (error) {
      if (revisions.get(key) === token)
        set(key, {
          stale: `Updates paused: ${error instanceof Error ? error.message : "Could not refresh investigation."} The last received result remains visible.`,
        });
    } finally {
      polling.delete(run.id);
    }
  }

  function open(payment: Case) {
    const index = caseKey(payment);
    const key = cases.get(index) ?? index;
    cases.set(index, key);
    const previous = sessions[key];
    create(key, payment);
    if (previous) {
      set(key, { payment });
      if (
        previous.pending ||
        previous.cancelling ||
        previous.run ||
        previous.error
      )
        return key;
    }
    const reusable =
      !payment.updateAvailable &&
      payment.investigationId &&
      ["queued", "running", "completed", "reviewed"].includes(
        payment.status ?? "",
      );
    void launch(
      key,
      reusable
        ? { method: "GET", runId: payment.investigationId! }
        : {
            method: "POST",
            datasetId: payment.datasetId,
            paymentId: payment.paymentId,
          },
    );
    return key;
  }

  function resume(runId: string, payment?: Case) {
    const known = runs.get(runId);
    if (known) {
      if (payment) set(known, { payment });
      return known;
    }
    const indexed = payment ? cases.get(caseKey(payment)) : undefined;
    const existing = indexed ? sessions[indexed] : undefined;
    const key =
      payment && !existing?.run && !existing?.pending
        ? (indexed ?? caseKey(payment))
        : `run:${runId}`;
    if (sessions[key]) return key;
    create(key, payment);
    runs.set(runId, key);
    if (payment && !indexed) cases.set(caseKey(payment), key);
    void launch(key, { method: "GET", runId });
    return key;
  }

  function cancel(key: string): Promise<void> {
    const underway = cancellations.get(key);
    if (underway) return underway;
    const run = sessions[key]?.run;
    if (!active(run) || !run) return Promise.resolve();
    const token = revision(key);
    set(key, { cancelling: true, error: "" });
    const result = (async () => {
      try {
        const next = await request<Investigation>(
          `/investigations/${encodeURIComponent(run.id)}/cancel`,
          { method: "POST" },
        );
        if (next.id !== run.id)
          throw new Error(
            "The cancellation response did not match the requested run.",
          );
        receive(key, next, token);
      } catch (error) {
        if (revisions.get(key) === token)
          set(key, {
            error:
              error instanceof Error
                ? error.message
                : "Could not cancel investigation.",
          });
      } finally {
        set(key, { cancelling: false });
        cancellations.delete(key);
      }
    })();
    cancellations.set(key, result);
    return result;
  }

  function retry(key: string) {
    const session = sessions[key];
    if (!session || session.pending || session.cancelling) return;
    if (active(session.run)) {
      void poll(key);
      return;
    }
    if (session.run?.status === "failed" || session.run?.status === "cancelled")
      void launch(key, {
        method: "POST",
        datasetId: session.run.datasetId,
        paymentId: session.run.paymentId,
      });
    else if (session.error && actions.has(key))
      void launch(key, actions.get(key)!);
  }

  function updateRun(run: Investigation) {
    const indexed = cases.get(caseKey(run));
    // A late review of an old run gets its own session rather than replacing a retry.
    const key =
      runs.get(run.id) ??
      (indexed &&
      (!sessions[indexed].run || sessions[indexed].run?.id === run.id)
        ? indexed
        : indexed
          ? `run:${run.id}`
          : caseKey(run));
    create(key);
    if (!follows(sessions[key].run, run)) return;
    const token = revision(key);
    receive(key, run, token);
  }

  return {
    open,
    resume,
    cancel,
    retry,
    updateRun,
    getSnapshot: () => sessions,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start() {
      enabled = true;
      syncTimer();
    },
    stop() {
      enabled = false;
      syncTimer();
    },
  };
}

export function useInvestigationSessions(options: Options = {}) {
  const onRun = useRef(options.onRun);
  onRun.current = options.onRun;
  const controllerRef = useRef<ReturnType<
    typeof createInvestigationSessions
  > | null>(null);
  if (!controllerRef.current)
    controllerRef.current = createInvestigationSessions({
      onRun: (run) => onRun.current?.(run),
    });
  const controller = controllerRef.current;
  const sessions = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    controller.start();
    return controller.stop;
  }, [controller]);
  return {
    sessions,
    open: controller.open,
    resume: controller.resume,
    cancel: controller.cancel,
    retry: controller.retry,
    updateRun: controller.updateRun,
  };
}
