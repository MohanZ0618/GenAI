import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, join } from "node:path";
import { createApp } from "./server.ts";
import { settings } from "./config.ts";
import { PostgresStore, recordId } from "./store.ts";
import { TABLES } from "../../../packages/contracts/src/index.ts";
import { assess, TOOL_ORDER } from "./verifier.ts";
import { onePassBaseline, modelConfiguration } from "./integrations/model.ts";

const [command, ...args] = process.argv.slice(2);
if (command === "db-init") {
  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is required");
  const store = new PostgresStore(process.env.DATABASE_URL);
  await store.init();
  await store.close();
  console.log(
    "Created FinTrace application tables, financial tables, and source views.",
  );
} else if (command === "investigate") {
  const { app, store, service } = await createApp();
  try {
    const datasets = await store.datasets();
    const ds = args[0]
      ? await store.dataset(args[0])
      : datasets.sort((a, b) => a.info.name.localeCompare(b.info.name))[0];
    if (!ds) throw new Error("Dataset not found");
    const pid =
      args[1] ||
      ds.data.manifest.focusPaymentIds?.[0] ||
      ds.data.tables.payments[0]?.payment_id;
    const run = await service.start(ds.info.id, pid);
    console.log(JSON.stringify(await service.wait(run.id), null, 2));
  } finally {
    await app.close();
  }
} else if (command === "evaluate") {
  const { app, store, service } = await createApp({
    storageDir: resolve(`.local/evaluation-${settings.mode}`),
  });
  try {
    const labels = JSON.parse(
      await readFile(resolve("evaluation/labels/cases.json"), "utf8"),
    ) as {
      packet: string;
      split: string;
      paymentId: string;
      expectedOutcome: string;
      category: string;
      evidenceIds: string[];
    }[];
    const datasets = await store.datasets();
    const results: Record<string, unknown>[] = [];
    for (const label of labels) {
      if (args[0] && label.split !== args[0]) continue;
      const ds = datasets.find((d) => d.info.name === label.packet);
      if (!ds) throw new Error(`Missing dataset ${label.packet}`);
      const run = await service.start(
        ds.info.id,
        label.paymentId,
        `evaluation-${ds.info.id}`,
      );
      const result = await service.wait(run.id);
      const cited = new Set(result.findings.flatMap((f) => f.evidenceIds));
      const citationRecords = result.evidence.filter((e) => cited.has(e.id));
      const aliases = new Set(
        citationRecords.flatMap((e) =>
          [e.recordId, e.record.journal_id].filter(Boolean),
        ),
      );
      const hits = label.evidenceIds.filter((id) => aliases.has(id)).length;
      const baselineEvidence = TABLES.flatMap((table) =>
        ds.data.tables[table].map((record, i) => ({
          id: `${table}:${recordId(table, record, i)}`,
          table,
          recordId: recordId(table, record, i),
          queryId: "independent-rule-baseline",
          datasetVersion: ds.info.version,
          record,
        })),
      );
      const baseline = assess(
        ds.info,
        label.paymentId,
        baselineEvidence,
        new Set(TOOL_ORDER),
      );
      let onePass: unknown = null;
      if (settings.mode !== "fixture") {
        try {
          onePass = await onePassBaseline(
            {
              paymentId: label.paymentId,
              evidence: baselineEvidence,
              manifest: ds.data.manifest,
            },
            AbortSignal.timeout(120000),
          );
        } catch {
          onePass = {
            status: "failed",
            reason: "One-pass request or citation validation failed",
          };
        }
      }
      results.push({
        packet: label.packet,
        split: label.split,
        expectedOutcome: label.expectedOutcome,
        expectedCategory: label.category,
        outcome: result.outcome,
        status: result.status,
        correct: result.outcome === label.expectedOutcome,
        rootCauseCorrect:
          result.outcome === label.expectedOutcome &&
          (label.expectedOutcome !== "anomaly_supported" ||
            result.findings.some((f) => label.category.startsWith(f.category))),
        ruleBaseline: baseline.outcome,
        onePassBaseline: onePass,
        category: result.findings.map((f) => f.category),
        citationIntegrity: result.findings.every((f) =>
          f.evidenceIds.every((id) => result.evidence.some((e) => e.id === id)),
        ),
        requiredEvidenceRecall: label.evidenceIds.length
          ? hits / label.evidenceIds.length
          : null,
        citationPrecision:
          label.evidenceIds.length && citationRecords.length
            ? citationRecords.filter(
                (e) =>
                  label.evidenceIds.includes(e.recordId) ||
                  label.evidenceIds.includes(e.record.journal_id),
              ).length / citationRecords.length
            : null,
        queries: result.queries.length,
        modelTurns: result.modelTurns,
        latencyMs: Date.parse(result.updatedAt) - Date.parse(result.createdAt),
        failedChecks: result.checks.filter((c) => c.status === "failed").length,
        unverifiedActions: result.actions.filter((a) => !a.verified).length,
        runId: result.id,
      });
    }
    const group = (split: string) => {
      const r = results.filter((r) => r.split === split);
      const normal = r.filter(
        (r) => r.expectedOutcome === "no_anomaly_supported",
      );
      return {
        cases: r.length,
        outcomeAccuracy: r.length
          ? r.filter((r) => r.correct).length / r.length
          : null,
        rootCauseAccuracy: r.length
          ? r.filter((r) => r.rootCauseCorrect).length / r.length
          : null,
        normalFalsePositives: normal.filter(
          (r) => r.outcome === "anomaly_supported",
        ).length,
        normalCases: normal.length,
        citationIntegrity: r.every((r) => r.citationIntegrity),
        technicalFailures: r.filter((r) => r.status === "failed").length,
      };
    };
    const report = {
      generatedAt: new Date().toISOString(),
      mode: settings.mode,
      provider:
        settings.mode === "fixture"
          ? "deterministic-fixture"
          : modelConfiguration().name,
      model: settings.mode === "fixture" ? "none" : modelConfiguration().model,
      notice:
        settings.mode === "fixture"
          ? "Offline deterministic verification. These results are not live-model or Zetaris results. Rules and fixture orchestration share the verifier; matching results do not demonstrate an AI advantage."
          : settings.mode === "local-model"
            ? "Live model with local synthetic snapshots; no Zetaris or PostgreSQL connectivity is established."
            : "Live model-and-Zetaris run. Compare with rules under the reported conditions.",
      onePassModelBaseline: {
        status:
          settings.mode === "fixture" ? "not_run" : "see_per_case_results",
        reason:
          settings.mode === "fixture"
            ? "No model is called in fixture mode."
            : "Same configured model, full visible packet, one response; no case memory.",
      },
      summary: {
        development: group("development"),
        heldout: group("heldout"),
        stress: group("stress"),
      },
      results,
    };
    await mkdir("evaluation/results", { recursive: true });
    const file = `evaluation/results/${settings.mode}-latest.json`;
    await writeFile(file, JSON.stringify(report, null, 2) + "\n");
    console.log(
      JSON.stringify({ report: file, summary: report.summary }, null, 2),
    );
  } finally {
    await app.close();
  }
} else {
  console.error(
    "Usage: npm run investigate -- [datasetId] [paymentId] | npm run evaluate -- [development|heldout|stress] | npm run db:init",
  );
  process.exitCode = 1;
}
