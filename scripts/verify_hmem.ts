import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { join, resolve, relative } from "node:path";
import { settings } from "../apps/api/src/config.ts";
import { FileStore } from "../apps/api/src/store.ts";
import { InvestigationService } from "../apps/api/src/service.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import { createApp } from "../apps/api/src/server.ts";
import { modelConfiguration } from "../apps/api/src/integrations/model.ts";
import { buildManualPackets } from "./prepare_openai_manual.ts";
import type {
  Investigation,
  ModelRequestTrace,
} from "../packages/contracts/src/index.ts";

// Synthetic reviewer actions exercise the same review API as the browser.
// Curated procedure text contains no target-case classifications, amounts or answers.
if (settings.mode === "live")
  throw new Error(
    "Use fixture or local-model; this experiment uses immutable local synthetic evidence.",
  );
if (settings.mode !== "fixture" && !process.argv.includes("--connect"))
  throw new Error("Real model calls require --connect");
await mkdir(".local", { recursive: true });
const directory = await mkdtemp(
  resolve(`.local/hmem-acceptance-${settings.mode}-`),
);
const store = new FileStore(join(directory, "state"));
await store.init();
let memory = new MemoryService(join(directory, "memory"));
let service = new InvestigationService(store, settings.mode, memory);
const { app } = await createApp({
  store,
  mode: settings.mode,
  storageDir: directory,
  seed: false,
});
const config = modelConfiguration();
const report: {
  mode: string;
  provider: string;
  model?: string;
  reviewer: string;
  runs: unknown[];
  lifecycle: unknown[];
  passed?: boolean;
} = {
  mode: settings.mode,
  provider: settings.mode === "fixture" ? "deterministic-fixture" : config.name,
  model: settings.mode === "fixture" ? "none" : config.model,
  reviewer:
    "Scripted synthetic reviewer exercising explicit API approval; not an actual customer or unobserved human approval.",
  runs: [],
  lifecycle: [],
};
const scenarios = [
  {
    code: "DUP",
    category: "F06",
    text: "When reviewing possible duplicate payment allocations, retrieve allocations first, then reconcile settlements and ledger; establish invoice obligations and temporal coverage before judging a duplicate.",
    tools: ["allocations", "settlements", "ledger"],
  },
  {
    code: "STALE",
    category: "F11",
    text: "For vendor bank information changes, inspect vendor history and compare the effective timestamps with payment time, then obtain settlements and ledger. Never use a current vendor snapshot as proof of a historical conflict.",
    tools: ["vendor_history", "settlements", "ledger"],
  },
  {
    code: "FEE",
    category: "F14",
    text: "For a payment and settlement amount difference, retrieve settlements and ledger, then inspect processor events if verification still needs them. Reconcile currency, fee postings and coverage before a conclusion.",
    tools: ["settlements", "ledger", "processor_events"],
  },
];
const summary = (run: Investigation, durationMs: number) => {
  const traces: ModelRequestTrace[] = run.modelRequests || [];
  const known = new Set(run.evidence.map((e) => e.id));
  return {
    id: run.id,
    namespace: run.memoryNamespace,
    status: run.status,
    outcome: run.outcome,
    categories: run.findings.map((f) => f.category),
    citationsValid:
      run.findings.every((f) => f.evidenceIds.every((id) => known.has(id))) &&
      run.checks.every((c) => c.evidenceIds.every((id) => known.has(id))),
    findingCitationCount: run.findings.reduce(
      (n, f) => n + f.evidenceIds.length,
      0,
    ),
    tools: run.queries.map((q) => q.tool),
    memories: run.memories,
    requests: traces.length,
    tokens: {
      input: traces.reduce((n, t) => n + (t.inputTokens || 0), 0),
      output: traces.reduce((n, t) => n + (t.outputTokens || 0), 0),
      total: traces.reduce((n, t) => n + (t.totalTokens || 0), 0),
    },
    usageReported:
      !traces.length || traces.every((t) => t.totalTokens !== undefined),
    durationMs,
    draftRequests: run.memoryDraftRequests || [],
  };
};
const execute = async (
  datasetId: string,
  paymentId: string,
  namespace: string,
) => {
  const started = Date.now();
  const run = await service.wait(
    (await service.start(datasetId, paymentId, namespace)).id,
  );
  return { run, metrics: summary(run, Date.now() - started) };
};
let passed = true;
try {
  const target = await store.saveDataset(buildManualPackets().main);
  const examples = JSON.parse(
    JSON.stringify(buildManualPackets().main).replaceAll("DEMO", "LESSON"),
  );
  examples.manifest.name = "Independent lesson examples";
  // Separate synthetic examples: new identifiers and different financial amounts.
  for (const rows of Object.values(examples.tables) as Record<
    string,
    string
  >[][])
    for (const row of rows)
      for (const key of [
        "payment_amount",
        "invoice_total",
        "allocated_amount",
        "amount",
        "debit",
        "credit",
      ])
        if (row[key] && Number.isFinite(Number(row[key])))
          row[key] = (Number(row[key]) * 1.37).toFixed(2);
  const source = await store.saveDataset(examples);
  const approvedSources: {
    run: Investigation;
    draft: NonNullable<Investigation["memoryDraft"]>;
    text: string;
  }[] = [];
  for (const scenario of scenarios) {
    const namespace = `lesson-${scenario.code}`;
    const { run } = await execute(
      source.info.id,
      `PAY_LESSON_${scenario.code}`,
      namespace,
    );
    if (run.status !== "completed")
      throw new Error(`Independent example failed: ${run.id}`);
    const result = await app.inject({
      method: "POST",
      url: `/api/investigations/${run.id}/memory-draft`,
    });
    const withDraft = result.json<Investigation>();
    if (withDraft.memoryDraft?.status !== "ready")
      throw new Error(`Draft unavailable: ${withDraft.memoryDraft?.status}`);
    const approval = await app.inject({
      method: "POST",
      url: `/api/investigations/${run.id}/review`,
      payload: {
        decision: "accepted",
        notes:
          "Synthetic reviewer: edited to an evidence-only procedure; no target answers included.",
        approveMemory: true,
        memoryDraftId: withDraft.memoryDraft.id,
        memoryContent: scenario.text,
      },
    });
    if (approval.statusCode !== 200)
      throw new Error("Synthetic review approval failed");
    approvedSources.push({
      run,
      draft: withDraft.memoryDraft,
      text: scenario.text,
    });
    report.lifecycle.push({
      stage: "generate-edit-approve",
      ...summary(approval.json<Investigation>(), 0),
      draft: withDraft.memoryDraft,
    });
    await writeFile(
      join(directory, "report.json"),
      JSON.stringify(report, null, 2),
    );
  }
  // Restart application wrappers before recall, preserving source, status and ledger on disk.
  await service.close();
  memory = new MemoryService(join(directory, "memory"));
  service = new InvestigationService(store, settings.mode, memory);
  await service.recover();
  for (let i = 0; i < scenarios.length; i++) {
    const scenario = scenarios[i],
      lesson = approvedSources[i];
    for (let repeat = 1; repeat <= 2; repeat++)
      for (const condition of ["without", "with"] as const) {
        const namespace = `comparison-${scenario.code}-${repeat}-${condition}`;
        if (condition === "with")
          await memory.approve(namespace, lesson.text, lesson.run.id, {
            draftId: lesson.draft.id,
            generationSource: lesson.draft.source,
            conditions: lesson.draft.conditions,
            suggestedTools: lesson.draft.suggestedTools,
            evidenceIds: lesson.draft.evidenceIds,
          });
        const { run, metrics } = await execute(
          target.info.id,
          `PAY_DEMO_${scenario.code}`,
          namespace,
        );
        const valid =
          run.status === "completed" &&
          run.outcome === "anomaly_supported" &&
          run.findings.some((f) => f.category === scenario.category) &&
          metrics.citationsValid &&
          metrics.findingCitationCount > 0 &&
          (condition === "with"
            ? run.memories.length > 0
            : run.memories.length === 0);
        passed &&= valid;
        report.runs.push({
          scenario: scenario.code,
          repeat,
          condition,
          valid,
          ...metrics,
        });
        await writeFile(
          join(directory, "report.json"),
          JSON.stringify(report, null, 2),
        );
        console.log(
          JSON.stringify({
            scenario: scenario.code,
            repeat,
            condition,
            valid,
            requests: metrics.requests,
            tokens: metrics.tokens.total,
            durationMs: metrics.durationMs,
          }),
        );
      }
  }
  const namespace = "lesson-DUP",
    entry = memory.list(namespace)[0];
  const recalled = await execute(target.info.id, "PAY_DEMO_DUP", namespace);
  const snapshot = JSON.stringify(recalled.run.memories);
  passed &&= recalled.run.memories.length > 0;
  memory.setStatus(namespace, entry.id, "inactive");
  const revised = buildManualPackets().main;
  revised.manifest.name += " lifecycle revised version";
  const runCount = (await store.runs()).length;
  const ds2 = await store.saveDataset(revised);
  passed &&= (await store.runs()).length === runCount; // Saving a revision does not start a run.
  await service.close();
  memory = new MemoryService(join(directory, "memory"));
  service = new InvestigationService(store, settings.mode, memory);
  const disabled = await execute(ds2.info.id, "PAY_DEMO_DUP", namespace);
  passed &&=
    disabled.run.memories.length === 0 &&
    memory.list(namespace)[0].status === "inactive" &&
    JSON.stringify((await store.run(recalled.run.id))!.memories) === snapshot;
  report.lifecycle.push(
    { stage: "recall-before-disable", ...recalled.metrics },
    { stage: "after-disable-and-restart", ...disabled.metrics },
  );
  const restartProbe = JSON.parse(
    execFileSync(
      process.execPath,
      ["--import", "tsx", "scripts/hmem_restart_probe.ts", directory],
      { encoding: "utf8" },
    ),
  );
  passed &&=
    restartProbe.drafts.length === 3 &&
    restartProbe.drafts.every(
      (d: { status: string }) => d.status === "ready",
    ) &&
    restartProbe.memoryStates[namespace][0].status === "inactive";
  report.lifecycle.push({
    stage: "independent-process-restart-probe",
    ...restartProbe,
  });
  memory.setStatus(namespace, entry.id, "active");
  passed &&=
    (await memory.recall(namespace, "payment allocations ledger")).length > 0;
  report.passed = passed;
} catch (e) {
  report.passed = false;
  report.lifecycle.push({
    stage: "failure",
    error: e instanceof Error ? e.message : "Acceptance failed",
  });
  process.exitCode = 1;
} finally {
  await writeFile(
    join(directory, "report.json"),
    JSON.stringify(report, null, 2),
  );
  await app.close();
  await service.close();
  console.log(
    JSON.stringify({
      report: relative(process.cwd(), join(directory, "report.json")),
      passed: report.passed,
    }),
  );
}
if (!report.passed) process.exitCode = 1;
