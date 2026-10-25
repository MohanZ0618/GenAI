import { randomUUID } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";
import type {
  Investigation,
  Mode,
  ToolName,
  Case,
} from "../../../packages/contracts/src/index.ts";
import type { Store, StoredDataset } from "./store.ts";
import { assess, TOOL_ORDER } from "./verifier.ts";
import { retrieve } from "./evidence.ts";
import {
  createModelProvider,
  type ModelProvider,
} from "./integrations/model.ts";
import { MemoryService } from "./integrations/memory.ts";
import { planningEvidence } from "./context.ts";

export function casesFor(dataset: StoredDataset): Case[] {
  const focus = dataset.data.manifest.focusPaymentIds;
  return dataset.data.tables.payments
    .filter((p) => !focus || focus.includes(p.payment_id))
    .map((p) => {
      const bank = dataset.data.tables.bank_transactions.filter(
        (b) =>
          b.payment_reference === p.reference_number &&
          b.transaction_type !== "bank fee",
      );
      const symptom = !bank.length
        ? "Bank settlement not matched"
        : bank.some((b) => b.status === "returned")
          ? "Settlement returned"
          : bank.some((b) => b.amount !== p.payment_amount)
            ? "Settlement amount differs"
            : "Reconciliation review requested";
      return {
        id: `${dataset.info.id}:${p.payment_id}`,
        paymentId: p.payment_id,
        datasetId: dataset.info.id,
        vendor:
          dataset.data.tables.vendors.find((v) => v.vendor_id === p.vendor_id)
            ?.vendor_name || p.vendor_id,
        amount: p.payment_amount,
        currency: p.payment_currency,
        date: p.payment_date,
        symptom,
        status: "unreviewed",
      };
    });
}
export class InvestigationService {
  private active = new Map<string, AbortController>();
  private liveRuns = new Map<string, Investigation>();
  readonly concurrency = 3;
  private pending: Array<() => Promise<void>> = [];
  private executing = new Set<Promise<void>>();
  private closing = false;
  private starts = new Map<string, Promise<Investigation>>();
  constructor(
    readonly store: Store,
    readonly mode: Mode,
    readonly memory: MemoryService,
    readonly provider?: ModelProvider,
  ) {}
  async recover() {
    for (const run of await this.store.runs())
      if (run.status === "queued" || run.status === "running") {
        run.status = "failed";
        run.error =
          "The process stopped before completion. Retained evidence is available; start a new investigation to retry.";
        await this.event(run, "recovery", run.error);
      }
  }
  async event(
    run: Investigation,
    type: string,
    message: string,
    tool?: ToolName,
  ) {
    run.updatedAt = new Date().toISOString();
    run.events.push({
      id: String(run.events.length + 1),
      at: run.updatedAt,
      type,
      message,
      ...(tool ? { tool } : {}),
    });
    await this.store.saveRun(run);
  }
  async start(datasetId: string, paymentId: string, namespace = "workspace") {
    if (this.closing)
      throw new Error(
        "Cannot start investigations while the service is closing",
      );
    const key = JSON.stringify([datasetId, paymentId, this.mode, namespace]);
    const pending = this.starts.get(key);
    if (pending) return pending;
    const starting = this.startOrReuse(datasetId, paymentId, namespace);
    this.starts.set(key, starting);
    try {
      return await starting;
    } finally {
      this.starts.delete(key);
    }
  }
  private async startOrReuse(
    datasetId: string,
    paymentId: string,
    namespace: string,
  ) {
    const ds = await this.store.dataset(datasetId);
    if (!ds) throw new Error("Dataset not found");
    if (!casesFor(ds).some((c) => c.paymentId === paymentId))
      throw new Error("Payment not found in this dataset case queue");
    const existing = (await this.store.runs())
      .filter(
        (run) =>
          run.datasetId === datasetId &&
          run.paymentId === paymentId &&
          run.mode === this.mode &&
          (run.memoryNamespace || "workspace") === namespace &&
          ["queued", "running", "completed"].includes(run.status),
      )
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];
    if (existing) return existing;
    const provider =
      this.mode !== "fixture"
        ? this.provider ||
          createModelProvider({ ...process.env, FINTRACE_MODE: this.mode })
        : undefined;
    const now = new Date().toISOString();
    const run: Investigation = {
      id: `run-${randomUUID()}`,
      memoryNamespace: namespace,
      datasetId,
      paymentId,
      status: "queued",
      mode: this.mode,
      provider: provider?.name || "deterministic-fixture",
      model: provider?.model || "none",
      createdAt: now,
      updatedAt: now,
      outcome: null,
      findings: [],
      checks: [],
      actions: [],
      evidence: [],
      events: [],
      queries: [],
      memories: [],
      modelTurns: 0,
      modelRequests: [],
    };
    await this.store.saveRun(run);
    const controller = new AbortController();
    this.active.set(run.id, controller);
    this.liveRuns.set(run.id, run);
    this.pending.push(() =>
      this.execute(run, ds, controller, namespace, provider),
    );
    this.drain();
    return structuredClone(run);
  }
  private drain() {
    while (this.executing.size < this.concurrency && this.pending.length) {
      const job = this.pending.shift()!;
      const task = job()
        .catch(() => {})
        .finally(() => {
          this.executing.delete(task);
          this.drain();
        });
      this.executing.add(task);
    }
  }
  private async execute(
    run: Investigation,
    ds: StoredDataset,
    controller: AbortController,
    namespace: string,
    provider?: ModelProvider,
  ) {
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(300000),
    ]);
    const completed = new Set<ToolName>();
    try {
      signal.throwIfAborted();
      run.status = "running";
      await this.event(
        run,
        "started",
        this.mode === "fixture"
          ? "Offline fixture run: deterministic tool selection and rules; no live model or Zetaris."
          : this.mode === "local-model"
            ? `Local-data model investigation: ${run.provider} / ${run.model}; evidence read from local snapshots; no Zetaris.`
            : "Live investigation: evidence queried through Zetaris with model-selected tools.",
      );
      run.memories = await this.memory.recall(
        namespace,
        "payment investigation review ledger settlement vendor",
      );
      await this.event(
        run,
        "memory",
        `Retrieved ${run.memories.length} explicitly approved playbook memories. Current financial evidence will be queried again.`,
      );
      for (let turn = 0; turn < 6; turn++) {
        signal.throwIfAborted();
        const previous = assess(
          ds.info,
          run.paymentId,
          run.evidence,
          completed,
        );
        if (!previous.neededTools.length) break;
        let tool: ToolName;
        let reason: string;
        if (turn === 0) {
          tool = "overview";
          reason =
            "Establish the payment, vendor, and invoice context before forming a conclusion.";
        } else if (provider) {
          run.modelTurns++;
          const context = planningEvidence(
            run.evidence,
            run.paymentId,
            ds.info.asOf,
          );
          await this.event(
            run,
            "context",
            `Model context: sent ${context.sent} related records (${context.bytes} bytes); ${context.omitted} omitted by the 24 KiB budget; ${context.excludedFuture} future records excluded; unrelated records not sent.`,
          );
          const next = await provider.next(
            {
              paymentId: run.paymentId,
              context: {
                verification: previous,
                availableTools: previous.neededTools,
                evidence: context.evidence,
                observationCutoff: ds.info.asOf,
                contextCoverage: {
                  omitted: context.omitted,
                  excludedFuture: context.excludedFuture,
                },
              },
              history: run.events.slice(-10),
              memories: run.memories,
            },
            signal,
            async (trace) => {
              run.modelRequests!.push(trace);
              await this.event(
                run,
                "model_request",
                `Model request ${trace.status}: ${trace.provider} / ${trace.model}; attempt ${trace.attempt}; ${trace.durationMs} ms${trace.httpStatus ? `; HTTP ${trace.httpStatus}` : ""}${trace.errorCode ? `; ${trace.errorCode}` : ""}.`,
              );
            },
          );
          if (next.finish) {
            await this.event(
              run,
              "budget",
              "The model stopped before all required evidence was retrieved; the result will remain unresolved.",
            );
            break;
          }
          tool = next.tool!;
          reason = next.reason;
        } else {
          const memoryText = JSON.stringify(run.memories).toLowerCase();
          const preferred = TOOL_ORDER.map((tool) => ({
            tool,
            rank: memoryText.indexOf(tool.replaceAll("_", " ")),
          }))
            .filter((t) => t.rank >= 0)
            .sort((a, b) => a.rank - b.rank)
            .map((t) => t.tool);
          tool =
            preferred.find((t) => !completed.has(t)) || previous.neededTools[0];
          reason = preferred.includes(tool)
            ? "Apply a reviewer-approved investigation playbook to prioritize this evidence tool."
            : "Retrieve the next source required by the independent verifier.";
        }
        if (completed.has(tool)) {
          await this.event(
            run,
            "stopped",
            "Repeated evidence query rejected. Remaining gaps will be reported.",
            tool,
          );
          break;
        }
        if (run.queries.reduce((n, q) => n + q.tables.length, 0) >= 12) {
          await this.event(run, "budget", "Evidence query budget exhausted.");
          break;
        }
        await this.event(run, "planning", reason, tool);
        let result: Awaited<ReturnType<typeof retrieve>>;
        try {
          result = await retrieve(tool, ds, run.paymentId, this.mode, signal);
        } catch (e) {
          run.queries.push({
            id: randomUUID(),
            tool,
            tables: [],
            at: new Date().toISOString(),
            durationMs: 0,
            rowCount: 0,
            status: "failed",
            error:
              "Evidence source request failed; no absence inference was made.",
            coverage: {},
          });
          throw e;
        }
        signal.throwIfAborted();
        run.queries.push(result.query);
        run.evidence.push(...result.evidence);
        completed.add(tool);
        await this.event(
          run,
          "evidence",
          `Retrieved ${result.evidence.length} source records. Query ${result.query.id}.`,
          tool,
        );
        const feedback = assess(
          ds.info,
          run.paymentId,
          run.evidence,
          completed,
        );
        run.checks = feedback.checks;
        if (feedback.neededTools.length)
          await this.event(
            run,
            "verification",
            "Conclusion withheld: the evidence is incomplete. Follow-up required: " +
              feedback.neededTools.join(", "),
          );
        if (this.mode === "fixture") await delay(20, undefined, { signal });
      }
      signal.throwIfAborted();
      const result = assess(ds.info, run.paymentId, run.evidence, completed);
      run.outcome = result.outcome;
      run.findings = result.findings;
      run.actions = result.actions;
      run.checks = result.checks;
      if (!run.findings.length)
        run.findings = [
          {
            id: "finding-incomplete",
            title: "Required evidence was not retrieved",
            category: "EVIDENCE_GAP",
            summary:
              "The investigation ended before all verification inputs were available.",
            evidenceIds: [],
            contradictions: [],
            uncertainty: result.neededTools.map((t) => `Retrieve ${t}`),
          },
        ];
      const known = new Set(run.evidence.map((e) => e.id));
      if (run.findings.some((f) => f.evidenceIds.some((id) => !known.has(id))))
        throw new Error("An evidence citation could not be resolved");
      run.status = "completed";
      await this.event(
        run,
        "completed",
        `Investigation completed: ${run.outcome.replaceAll("_", " ")}. Proposed actions require human review.`,
      );
    } catch (e) {
      run.status = controller.signal.aborted ? "cancelled" : "failed";
      run.outcome = null;
      run.actions = [];
      run.error = controller.signal.aborted
        ? "Cancelled by the user."
        : signal.aborted
          ? "Investigation exceeded its five-minute time budget."
          : e instanceof Error
            ? e.message
            : "Investigation failed";
      await this.event(run, run.status, run.error);
    } finally {
      this.active.delete(run.id);
      this.liveRuns.delete(run.id);
    }
  }
  async cancel(id: string) {
    const run = this.liveRuns.get(id) || (await this.store.run(id));
    if (!run) return undefined;
    if (["queued", "running"].includes(run.status)) {
      this.active.get(id)?.abort();
      run.status = "cancelled";
      run.outcome = null;
      run.actions = [];
      run.error = "Cancelled by the user.";
      await this.event(run, "cancelled", run.error);
    }
    return this.store.run(id);
  }
  async wait(id: string) {
    const until = Date.now() + 360000;
    while (Date.now() < until) {
      const run = await this.store.run(id);
      if (!run) throw new Error("Investigation not found");
      if (!["queued", "running"].includes(run.status)) return run;
      if (!this.active.has(id)) {
        run.status = "failed";
        run.outcome = null;
        run.error =
          "Execution ended before the final state could be persisted. Retry the investigation.";
        await this.store.saveRun(run);
        return run;
      }
      await delay(50);
    }
    throw new Error("Timed out waiting for investigation completion");
  }
  async close() {
    this.closing = true;
    await Promise.allSettled(this.starts.values());
    for (const controller of this.active.values()) controller.abort();
    while (this.executing.size) await Promise.allSettled(this.executing);
  }
}
