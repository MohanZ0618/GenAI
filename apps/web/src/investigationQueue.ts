import { api } from "./api";
import type { Case, Investigation } from "./api";

export type QueueUpdate = {
  item: Case;
  phase: "waiting" | "running" | "finished" | "error";
  error?: string;
};
type Request = typeof api;
const completed = (item: Case) =>
  ["completed", "reviewed"].includes(item.status ?? "") &&
  !item.updateAvailable;
const active = (run: Investigation) =>
  ["queued", "running"].includes(run.status);

export function caseFromRun(item: Case, run: Investigation): Case {
  if (item.datasetId !== run.datasetId || item.paymentId !== run.paymentId)
    throw new Error("The investigation does not belong to this case.");
  return {
    ...item,
    investigationId: run.id,
    status: run.review ? "reviewed" : run.status,
    outcome: run.status === "completed" ? run.outcome : null,
    updateAvailable: false,
  };
}

export async function hydrateSavedResults(
  items: Case[],
  options: { request?: Request; signal?: AbortSignal } = {},
): Promise<Case[]> {
  const request = options.request ?? api;
  const result = [...items];
  let cursor = 0;
  await Promise.all(
    Array.from({ length: Math.min(4, items.length) }, async () => {
      while (cursor < items.length && !options.signal?.aborted) {
        const index = cursor++;
        const item = items[index];
        if (!completed(item) || item.outcome || !item.investigationId) continue;
        try {
          const run = await request<Investigation>(
            `/investigations/${encodeURIComponent(item.investigationId)}`,
            { signal: options.signal },
          );
          result[index] = caseFromRun(item, run);
        } catch {
          // A missing saved result must never trigger a new investigation.
        }
      }
    }),
  );
  return result;
}

export async function runInvestigationQueue(
  items: Case[],
  onUpdate: (update: QueueUpdate) => void,
  options: { request?: Request; wait?: () => Promise<void> } = {},
) {
  const request = options.request ?? api;
  const wait =
    options.wait ?? (() => new Promise<void>((done) => setTimeout(done, 1000)));
  const unique = [
    ...new Map(
      items.map((item) => [
        JSON.stringify([item.datasetId, item.paymentId]),
        item,
      ]),
    ).values(),
  ];
  const ordered = [
    ...unique.filter(completed),
    ...unique.filter((item) => !completed(item)),
  ];
  for (const item of unique) onUpdate({ item, phase: "waiting" });
  let paused = false;
  for (const item of ordered) {
    if (paused) {
      onUpdate({
        item,
        phase: "error",
        error:
          "Not started: the previous investigation's progress could not be confirmed. Retry when the connection is available.",
      });
      continue;
    }
    let current = item;
    try {
      const reusable =
        !item.updateAvailable &&
        item.investigationId &&
        ["completed", "reviewed", "running", "queued"].includes(
          item.status ?? "",
        );
      if (completed(item) && !item.investigationId)
        throw new Error(
          "The saved investigation ID is missing. This completed case was not rerun.",
        );
      let run = reusable
        ? await request<Investigation>(
            `/investigations/${encodeURIComponent(item.investigationId!)}`,
          )
        : await request<Investigation>("/investigations", {
            method: "POST",
            body: JSON.stringify({
              datasetId: item.datasetId,
              paymentId: item.paymentId,
            }),
          });
      current = caseFromRun(item, run);
      onUpdate({ item: current, phase: active(run) ? "running" : "finished" });
      while (active(run)) {
        await wait();
        let next: Investigation | undefined;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            next = await request<Investigation>(
              `/investigations/${encodeURIComponent(run.id)}`,
            );
            break;
          } catch (error) {
            if (attempt === 2) {
              paused = true;
              throw error;
            }
            await wait();
          }
        }
        run = next!;
        current = caseFromRun(item, run);
        onUpdate({
          item: current,
          phase: active(run) ? "running" : "finished",
        });
      }
    } catch (error) {
      if (
        current.investigationId &&
        ["queued", "running"].includes(current.status ?? "")
      )
        paused = true;
      onUpdate({
        item: current,
        phase: "error",
        error:
          error instanceof Error
            ? error.message
            : "Could not investigate this case.",
      });
    }
  }
}
