import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { resolve, relative } from "node:path";
import { settings } from "../apps/api/src/config.ts";
import { modelConfiguration } from "../apps/api/src/integrations/model.ts";
import { createApp } from "../apps/api/src/server.ts";

// Explicit, billable smoke check; never imported by the ordinary test suite.
if (settings.mode !== "local-model" || modelConfiguration().name !== "openai")
  throw new Error(
    "This smoke check requires local-model mode and MODEL_PROVIDER=openai",
  );
await mkdir(".local", { recursive: true });
const storageDir = await mkdtemp(resolve(".local/openai-live-smoke-"));
const { app, service } = await createApp({
  mode: "local-model",
  storageDir,
  seed: false,
});
try {
  const bundle = JSON.parse(
    await readFile("data/openai-manual/01-main-bundle.json", "utf8"),
  );
  const imported = await app.inject({
    method: "POST",
    url: "/api/datasets",
    payload: bundle,
  });
  if (imported.statusCode !== 201)
    throw new Error("Smoke-check dataset import failed");
  const run = await service.wait(
    (await service.start(imported.json().dataset.id, "PAY_DEMO_NORMAL")).id,
  );
  const passed =
    run.status === "completed" &&
    run.outcome === "no_anomaly_supported" &&
    (run.modelRequests || []).some((r) => r.status === "succeeded");
  const report = {
    verifiedAt: new Date().toISOString(),
    scope:
      "One real OpenAI normal-case investigation; not an eight-case live evaluation",
    mode: run.mode,
    provider: run.provider,
    model: run.model,
    runId: run.id,
    datasetId: run.datasetId,
    storageDir: relative(process.cwd(), storageDir),
    paymentId: run.paymentId,
    status: run.status,
    outcome: run.outcome,
    passed,
    error: run.error,
    findings: run.findings,
    checks: run.checks,
    modelRequests: run.modelRequests,
    queryCount: run.queries.length,
    modelTurns: run.modelTurns,
  };
  const file = "data/openai-manual/live-smoke.json";
  await writeFile(file, JSON.stringify(report, null, 2) + "\n");
  console.log(
    JSON.stringify({
      report: file,
      passed,
      provider: run.provider,
      model: run.model,
      status: run.status,
      outcome: run.outcome,
      httpAttempts: run.modelRequests?.length || 0,
      runId: run.id,
    }),
  );
  if (!passed) process.exitCode = 1;
} finally {
  await app.close();
}
