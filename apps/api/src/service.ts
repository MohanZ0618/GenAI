import { randomUUID } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";
import type {
  Investigation,
  Mode,
  ToolName,
  Case,
  InvestigationActivity,
} from "../../../packages/contracts/src/index.ts";
import type { Store, StoredDataset } from "./store.ts";
import { assess, TOOL_ORDER } from "./verifier.ts";
import { retrieve } from "./evidence.ts";
import {
  createModelProvider,
  generateMemorySuggestion,
  modelConfiguration,
  type ModelProvider,
} from "./integrations/model.ts";
import { MemoryService } from "./integrations/memory.ts";
import { planningEvidence } from "./context.ts";
import {
  toolPurpose,
  toolTables,
  toolResultActivity,
  unfinishedActivities,
  verificationActivity,
} from "./activity.ts";

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
  private draftJobs = new Map<string, Promise<Investigation>>();
  private mutations = new Map<string, Promise<unknown>>();
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
    for (const run of await this.store.runs()) {
      if (run.memoryDraft?.status === "generating") {
        run.memoryDraft.status = "failed";
        run.memoryDraft.error =
          "Generation interrupted by restart; explicitly retry or enter a memory manually.";
        await this.store.saveRun(run);
      }
      if (run.status === "queued" || run.status === "running") {
        run.status = "failed";
        run.error =
          "The process stopped before completion. Retained evidence is available; start a new investigation to retry.";
        await this.finishOpenActivities(
          run,
          "failed",
          "A process restart interrupted this step. Retained evidence is available for review.",
        );
        await this.event(run, "recovery", run.error);
      }
    }
  }
  async event(
    run: Investigation,
    type: string,
    message: string,
    tool?: ToolName,
    activity?: InvestigationActivity,
  ) {
    run.updatedAt = new Date().toISOString();
    run.events.push({
      id: String(run.events.length + 1),
      at: run.updatedAt,
      type,
      message,
      ...(tool ? { tool } : {}),
      ...(activity ? { activity } : {}),
    });
    await this.store.saveRun(run);
  }
  private async beginActivity(
    run: Investigation,
    kind: InvestigationActivity["kind"],
    reason: string,
    source: InvestigationActivity["source"],
    tool?: ToolName,
  ) {
    const activity: InvestigationActivity = {
      id: randomUUID(),
      kind,
      status: "running",
      source,
      reason,
      ...(kind === "tool" && tool ? { tables: toolTables[tool] } : {}),
    };
    await this.event(run, `${kind}_started`, reason, tool, activity);
    return activity;
  }
  private async finishActivity(
    run: Investigation,
    activity: InvestigationActivity,
    status: Exclude<InvestigationActivity["status"], "running">,
    summary: string,
    tool?: ToolName,
    details: Partial<InvestigationActivity> = {},
    message: string = summary,
  ) {
    const pending = unfinishedActivities(run).find(
      (item) => item.activity.id === activity.id,
    );
    // Cancellation may already have closed this activity while its call awaited.
    if (!pending) return;
    const type =
      status !== "completed"
        ? `${activity.kind}_${status}`
        : activity.kind === "tool"
          ? "evidence"
          : activity.kind;
    await this.event(run, type, message, tool || pending.tool, {
      ...activity,
      ...details,
      id: activity.id,
      kind: activity.kind,
      status,
      summary,
      durationMs:
        details.durationMs ??
        Math.max(0, Date.now() - Date.parse(pending.startedAt)),
    });
  }
  private async finishOpenActivities(
    run: Investigation,
    status: "failed" | "cancelled",
    summary: string,
  ) {
    for (const { activity, tool } of unfinishedActivities(run))
      await this.finishActivity(run, activity, status, summary, tool);
  }
  private async verifyActivity(
    run: Investigation,
    ds: StoredDataset,
    completed: Set<ToolName>,
    signal: AbortSignal,
  ) {
    signal.throwIfAborted();
    const activity = await this.beginActivity(
      run,
      "verification",
      "Check evidence completeness, timing, and financial relationships using independent rules.",
      "rules",
    );
    signal.throwIfAborted();
    const result = assess(ds.info, run.paymentId, run.evidence, completed);
    const details = verificationActivity(result);
    await this.finishActivity(
      run,
      activity,
      "completed",
      details.summary,
      undefined,
      details,
    );
    return result;
  }
  async start(datasetId: string, paymentId: string, namespace = "workspace") {
    if (this.closing)
      throw new Error(
        "Cannot start investigations while the service is closing",
      );
    const key = JSON.stringify([datasetId, paymentId, this.mode, namespace]);
    const pending = this.starts.get(key);
    if (pending) return pending;
    const starting = this.mutate(`dataset:${datasetId}`, () =>
      this.startOrReuse(datasetId, paymentId, namespace),
    );
    this.starts.set(key, starting);
    try {
      return await starting;
    } finally {
      this.starts.delete(key);
    }
  }
  async setDatasetRemoved(datasetId: string, removed: boolean) {
    return this.mutate(`dataset:${datasetId}`, async () => {
      if (
        removed &&
        (await this.store.runs()).some(
          (run) =>
            run.datasetId === datasetId &&
            (run.status === "queued" || run.status === "running"),
        )
      ) {
        throw new Error(
          "This dataset has an active investigation. Wait for it to finish or cancel it first.",
        );
      }
      await this.store.setDatasetRemoved(datasetId, removed);
    });
  }
  private async startOrReuse(
    datasetId: string,
    paymentId: string,
    namespace: string,
  ) {
    const ds = await this.store.dataset(datasetId);
    if (!ds) throw new Error("Dataset not found");
    if (ds.info.removedAt)
      throw new Error(
        "Cannot investigate a removed dataset. Restore it first.",
      );
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
      let previous = await this.verifyActivity(run, ds, completed, signal);
      for (let turn = 0; turn < 6; turn++) {
        signal.throwIfAborted();
        if (!previous.neededTools.length) break;
        let tool: ToolName;
        let reason: string;
        let diagnosticReason: string | undefined;
        const selectionSource = turn > 0 && provider ? "model" : "rules";
        const planning = await this.beginActivity(
          run,
          "planning",
          selectionSource === "model"
            ? "Ask the model to choose the next tool from the independent verifier's outstanding evidence requests."
            : "Plan the next evidence request from the independent verifier's evidence gaps.",
          selectionSource,
        );
        signal.throwIfAborted();
        if (turn === 0) {
          tool = "overview";
          reason = toolPurpose.overview;
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
              history: run.events
                .filter((event) => !event.type.endsWith("_started"))
                .slice(-10)
                .map(({ activity: _activity, ...event }) => event),
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
          signal.throwIfAborted();
          if (next.finish) {
            await this.finishActivity(
              run,
              planning,
              "completed",
              "The model requested an end to evidence retrieval. Unmet evidence requirements remain reported as gaps.",
            );
            await this.event(
              run,
              "budget",
              "The model stopped before all required evidence was retrieved; the result will remain unresolved.",
            );
            break;
          }
          tool = next.tool!;
          reason = toolPurpose[tool];
          diagnosticReason = next.reason;
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
            preferred.find(
              (t) => previous.neededTools.includes(t) && !completed.has(t),
            ) || previous.neededTools[0];
          reason = preferred.includes(tool)
            ? `${toolPurpose[tool]} Prioritize evidence retrieval using approved investigation experience.`
            : toolPurpose[tool];
        }
        await this.finishActivity(
          run,
          planning,
          "completed",
          `Selected tool ${tool}. ${reason}`,
          tool,
          { reason },
          diagnosticReason,
        );
        signal.throwIfAborted();
        if (!previous.neededTools.includes(tool) || completed.has(tool)) {
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
        const toolActivity = await this.beginActivity(
          run,
          "tool",
          reason,
          selectionSource,
          tool,
        );
        signal.throwIfAborted();
        let result: Awaited<ReturnType<typeof retrieve>>;
        const queryStarted = Date.now();
        try {
          result = await retrieve(tool, ds, run.paymentId, this.mode, signal);
        } catch (e) {
          const queryId = randomUUID();
          run.queries.push({
            id: queryId,
            tool,
            tables: [],
            at: new Date().toISOString(),
            durationMs: Math.max(0, Date.now() - queryStarted),
            rowCount: 0,
            status: "failed",
            error:
              "Evidence source request failed; no absence inference was made.",
            coverage: {},
          });
          await this.finishActivity(
            run,
            toolActivity,
            controller.signal.aborted ? "cancelled" : "failed",
            controller.signal.aborted
              ? "The query was cancelled. No inference was made about whether source records exist."
              : "The evidence query did not complete. A failed request does not establish that source records are missing.",
            tool,
            { queryId, durationMs: Math.max(0, Date.now() - queryStarted) },
          );
          throw e;
        }
        signal.throwIfAborted();
        run.queries.push(result.query);
        run.evidence.push(...result.evidence);
        completed.add(tool);
        const toolDetails = toolResultActivity(
          result.evidence,
          run.evidence,
          run.paymentId,
          ds.info.asOf,
          tool,
        );
        await this.finishActivity(
          run,
          toolActivity,
          "completed",
          toolDetails.summary,
          tool,
          {
            ...toolDetails,
            queryId: result.query.id,
            tables: result.query.tables,
            durationMs: result.query.durationMs,
          },
        );
        const feedback = await this.verifyActivity(run, ds, completed, signal);
        previous = feedback;
        run.checks = feedback.checks;
        if (tool === "overview") {
          const context = planningEvidence(
            run.evidence,
            run.paymentId,
            ds.info.asOf,
          );
          const payment = context.evidence.find(
            (e) =>
              e.table === "payments" && e.record.payment_id === run.paymentId,
          )?.record;
          const query = [
            "payment investigation",
            payment?.vendor_id,
            payment?.payment_currency,
            ...feedback.neededTools.map((t) => t.replaceAll("_", " ")),
            ...feedback.checks
              .filter((c) => c.status !== "passed")
              .map((c) => c.label),
          ]
            .filter(Boolean)
            .join(" ");
          signal.throwIfAborted();
          const memoryActivity = await this.beginActivity(
            run,
            "memory",
            "Retrieve relevant approved investigation experience to help prioritize subsequent evidence tools.",
            "rules",
          );
          signal.throwIfAborted();
          run.memories = await this.memory.recall(
            namespace,
            query,
            payment?.vendor_id,
          );
          signal.throwIfAborted();
          await this.finishActivity(
            run,
            memoryActivity,
            "completed",
            run.memories.length
              ? `Found ${run.memories.length} approved memories for reference. Continue checking the current evidence.`
              : "No reusable approved experience was found. Continue investigating the current evidence.",
          );
        }
        if (this.mode === "fixture") await delay(20, undefined, { signal });
      }
      signal.throwIfAborted();
      const result = await this.verifyActivity(run, ds, completed, signal);
      signal.throwIfAborted();
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
      await this.finishOpenActivities(
        run,
        run.status === "cancelled" ? "cancelled" : "failed",
        run.status === "cancelled"
          ? "This step was cancelled. No financial conclusion was produced."
          : "This step did not complete. No financial conclusion was produced; retained evidence is available for review.",
      );
      await this.event(run, run.status, run.error);
    } finally {
      this.active.delete(run.id);
      this.liveRuns.delete(run.id);
    }
  }
  async mutate<T>(id: string, action: () => Promise<T>): Promise<T> {
    const previous = this.mutations.get(id) || Promise.resolve();
    const task = previous.catch(() => {}).then(action);
    this.mutations.set(id, task);
    try {
      return await task;
    } finally {
      if (this.mutations.get(id) === task) this.mutations.delete(id);
    }
  }
  async memoryDraft(id: string, retry = false) {
    const pending = this.draftJobs.get(id);
    if (pending) return pending;
    const task = this.mutate(id, async () => {
      const run = await this.store.run(id);
      if (!run) throw new Error("Investigation not found");
      if (run.status !== "completed")
        throw new Error("Only completed investigations can suggest memory");
      if (run.memoryDraft && !(retry && run.memoryDraft.status === "failed"))
        return run;
      const ds = await this.store.dataset(run.datasetId);
      if (!ds) throw new Error("Dataset not found");
      const config = modelConfiguration({
        ...process.env,
        FINTRACE_MODE: run.mode,
      });
      const draft: NonNullable<Investigation["memoryDraft"]> = {
        id: `draft-${randomUUID()}`,
        status: "generating",
        source: run.mode === "fixture" ? "fixture" : "model",
        provider: run.mode === "fixture" ? run.provider : config.name,
        model: run.mode === "fixture" ? run.model : config.model || "",
        createdAt: new Date().toISOString(),
      };
      run.memoryDraft = draft;
      run.memoryDraftRequests ||= [];
      await this.store.saveRun(run);
      try {
        const context = planningEvidence(
          run.evidence,
          run.paymentId,
          ds.info.asOf,
        );
        const allowed = new Set(context.evidence.map((e) => e.id));
        const verification = run.checks.map((c) => ({
          ...c,
          evidenceIds: c.evidenceIds.filter((id) => allowed.has(id)),
        }));
        const suggestion =
          run.mode === "fixture"
            ? {
                hasSuggestion: context.evidence.length > 0,
                content:
                  "Inspect allocations and vendor history, then reconcile settlements and ledger before accepting a payment assessment.",
                conditions:
                  "Payment reconciliation with unresolved evidence checks; retrieve current evidence every time.",
                suggestedTools: [
                  "allocations",
                  "vendor_history",
                  "settlements",
                  "ledger",
                ] as ToolName[],
                evidenceIds: context.evidence.slice(0, 2).map((e) => e.id),
                reason: "Deterministic fixture example; no model was called.",
              }
            : await generateMemorySuggestion(
                {
                  evidence: context.evidence,
                  verification,
                  gaps: run.findings.flatMap((f) => f.uncertainty),
                },
                new AbortController().signal,
                async (trace) => {
                  run.memoryDraftRequests!.push(trace);
                  await this.store.saveRun(run);
                },
              );
        Object.assign(draft, suggestion, {
          status: suggestion.hasSuggestion ? "ready" : "none",
        });
      } catch (error) {
        Object.assign(draft, {
          status: "failed",
          error:
            error instanceof Error &&
            /^Memory draft|^Model |^openai |^nvidia |^meterless /.test(
              error.message,
            )
              ? error.message
              : "Memory generation failed; manual entry remains available.",
        });
      }
      await this.event(
        run,
        "memory_draft",
        `Memory draft ${draft.status}; source: ${draft.source}. No memory approved.`,
      );
      return run;
    });
    this.draftJobs.set(id, task);
    try {
      return await task;
    } finally {
      this.draftJobs.delete(id);
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
      await this.finishOpenActivities(
        run,
        "cancelled",
        "This step was cancelled. No financial conclusion was produced.",
      );
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
        // A read may begin before the final save and finish after its controller
        // is removed. Re-read so an older snapshot cannot overwrite completion.
        const latest = await this.store.run(id);
        if (!latest) throw new Error("Investigation not found");
        if (!["queued", "running"].includes(latest.status)) return latest;
        latest.status = "failed";
        latest.outcome = null;
        latest.actions = [];
        latest.error =
          "Execution ended before the final state could be persisted. Retry the investigation.";
        await this.finishOpenActivities(
          latest,
          "failed",
          "This step was unexpectedly interrupted. No financial conclusion was produced.",
        );
        await this.store.saveRun(latest);
        return latest;
      }
      await delay(50);
    }
    throw new Error("Timed out waiting for investigation completion");
  }
  async close() {
    this.closing = true;
    await Promise.allSettled(this.starts.values());
    await Promise.allSettled(this.draftJobs.values());
    for (const controller of this.active.values()) controller.abort();
    while (this.executing.size) await Promise.allSettled(this.executing);
  }
}
