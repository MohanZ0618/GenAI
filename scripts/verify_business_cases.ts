import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { join, resolve, relative } from "node:path";
import { settings } from "../apps/api/src/config.ts";
import { FileStore, PostgresStore, type Store } from "../apps/api/src/store.ts";
import { InvestigationService } from "../apps/api/src/service.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import { parseCsvPackage } from "../packages/data/src/index.ts";
import type { Outcome } from "../packages/contracts/src/index.ts";

// Explicit acceptance run: live/local-model use the configured, billable provider.
const args = process.argv.slice(2);
const repeatArg = args.find((arg) => arg.startsWith("--repeat="));
const repeat = Number(repeatArg?.slice("--repeat=".length) || 1);
if (!Number.isInteger(repeat) || repeat < 1 || repeat > 3)
  throw new Error("--repeat must be 1, 2, or 3");
if (args.some((arg) => arg !== "--connect" && arg !== repeatArg))
  throw new Error("Usage: npm run verify:business -- [--connect] [--repeat=3]");
if (settings.mode !== "fixture" && !args.includes("--connect"))
  throw new Error(
    "Model modes require --connect; this makes billable API calls",
  );
if (settings.mode === "live" && !process.env.DATABASE_URL)
  throw new Error("Live mode requires DATABASE_URL");

const cases: { paymentId: string; outcome: Outcome; category: string }[] = [
  {
    paymentId: "PAY_DEMO_NORMAL",
    outcome: "no_anomaly_supported",
    category: "NO_FAILURE",
  },
  { paymentId: "PAY_DEMO_DUP", outcome: "anomaly_supported", category: "F06" },
  {
    paymentId: "PAY_DEMO_STALE",
    outcome: "anomaly_supported",
    category: "F11",
  },
  {
    paymentId: "PAY_DEMO_MISSING",
    outcome: "anomaly_supported",
    category: "F12",
  },
  { paymentId: "PAY_DEMO_FEE", outcome: "anomaly_supported", category: "F14" },
  {
    paymentId: "PAY_DEMO_FUTURE_EVENT",
    outcome: "insufficient_evidence",
    category: "EVIDENCE_GAP",
  },
  {
    paymentId: "PAY_DEMO_FUTURE_FEE",
    outcome: "anomaly_supported",
    category: "F14",
  },
  {
    paymentId: "PAY_DEMO_CONTEXT_TAIL",
    outcome: "no_anomaly_supported",
    category: "NO_FAILURE",
  },
];
await mkdir(".local", { recursive: true });
const directory = await mkdtemp(
  resolve(`.local/business-cases-${settings.mode}-`),
);
const namespace = `business-acceptance-${Date.now()}`;
const store: Store =
  settings.mode === "live"
    ? new PostgresStore(process.env.DATABASE_URL!)
    : new FileStore(join(directory, "state"));
const memory = new MemoryService(join(directory, "memory"));
const service = new InvestigationService(store, settings.mode, memory);
const results: Record<string, unknown>[] = [];
let passed = true;
try {
  await store.init();
  if (
    (await store.runs()).some((run) =>
      ["queued", "running"].includes(run.status),
    )
  )
    throw new Error(
      "Wait for existing investigations to finish before acceptance testing",
    );
  const importBundle = async (name: string) => {
    const bundle = JSON.parse(
      await readFile(join("data/openai-manual", name), "utf8"),
    );
    return store.saveDataset(parseCsvPackage(bundle));
  };
  const main = await importBundle("01-main-bundle.json");
  const partial = await importBundle("02-partial-coverage.json");
  const execute = async (
    datasetId: string,
    expected: (typeof cases)[number],
    iteration: number,
    label: string,
  ) => {
    const run = await service.wait(
      (
        await service.start(
          datasetId,
          expected.paymentId,
          `${namespace}-${iteration}`,
        )
      ).id,
    );
    await writeFile(
      join(directory, `${label}-${iteration}.json`),
      JSON.stringify(run, null, 2) + "\n",
    );
    const known = new Set(run.evidence.map((item) => item.id));
    const citationIntegrity = run.findings.every((finding) =>
      finding.evidenceIds.every((id) => known.has(id)),
    );
    const requests = run.modelRequests || [];
    const ok =
      run.status === "completed" &&
      run.outcome === expected.outcome &&
      run.findings.some((finding) => finding.category === expected.category) &&
      citationIntegrity &&
      run.queries.every((query) => query.status === "succeeded") &&
      (settings.mode === "fixture" ||
        expected.outcome === "insufficient_evidence" ||
        requests.some((request) => request.status === "succeeded"));
    passed &&= ok;
    const result = {
      label,
      iteration,
      passed: ok,
      runId: run.id,
      datasetId,
      paymentId: run.paymentId,
      mode: run.mode,
      provider: run.provider,
      model: run.model,
      status: run.status,
      outcome: run.outcome,
      expectedOutcome: expected.outcome,
      expectedCategory: expected.category,
      categories: run.findings.map((finding) => finding.category),
      citationIntegrity,
      queryCount: run.queries.length,
      queryTables: [...new Set(run.queries.flatMap((query) => query.tables))],
      modelRequests: requests.length,
      successfulModelRequests: requests.filter(
        (request) => request.status === "succeeded",
      ).length,
      totalTokens: requests.reduce(
        (sum, request) => sum + (request.totalTokens || 0),
        0,
      ),
      returnedModels: [
        ...new Set(
          requests.map((request) => request.returnedModel).filter(Boolean),
        ),
      ],
      durationMs: Date.parse(run.updatedAt) - Date.parse(run.createdAt),
      failedChecks: run.checks
        .filter((check) => check.status === "failed")
        .map((check) => check.id),
    };
    results.push(result);
    await writeFile(
      join(directory, "summary.json"),
      JSON.stringify(
        {
          verifiedAt: new Date().toISOString(),
          syntheticDataOnly: true,
          mode: settings.mode,
          repeat,
          passed,
          completedRuns: results.length,
          results,
          notice:
            "Selected acceptance cases, not a held-out evaluation or proof of real business accuracy. Query IDs are application trace IDs, not Zetaris server-issued query IDs.",
        },
        null,
        2,
      ) + "\n",
    );
    console.log(JSON.stringify(result));
    if (run.status === "failed")
      throw new Error(
        "Technical failure; inspect the local run artifact before retrying",
      );
  };
  const partialCase = {
    paymentId: "PAY_DEMO_NORMAL",
    outcome: "insufficient_evidence" as const,
    category: "EVIDENCE_GAP",
  };
  for (const item of cases)
    await execute(main.info.id, item, 1, item.paymentId);
  await execute(partial.info.id, partialCase, 1, "PARTIAL_COVERAGE");
  for (let iteration = 2; iteration <= repeat; iteration++) {
    for (const item of cases.slice(0, 2))
      await execute(main.info.id, item, iteration, item.paymentId);
    await execute(partial.info.id, partialCase, iteration, "PARTIAL_COVERAGE");
  }
  console.log(
    JSON.stringify({
      passed,
      report: relative(process.cwd(), join(directory, "summary.json")),
    }),
  );
  if (!passed) process.exitCode = 1;
} finally {
  await service.close();
  await store.close();
}
