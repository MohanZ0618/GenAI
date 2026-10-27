import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { createApp } from "../apps/api/src/server.ts";
import { PostgresStore } from "../apps/api/src/store.ts";
import { settings } from "../apps/api/src/config.ts";
import { modelConfiguration } from "../apps/api/src/integrations/model.ts";
import { buildManualPackets } from "./prepare_openai_manual.ts";
import type {
  Investigation,
  Outcome,
  ModelRequestTrace,
} from "../packages/contracts/src/index.ts";

// Explicit opt-in: contacts the real local Runtime, PostgreSQL and Zetaris,
// consumes cloud-model quota, and writes fresh synthetic datasets/reviews/memory.
const args = process.argv.slice(2);
if (
  args.some((arg) => !["--connect", "--workspace"].includes(arg)) ||
  new Set(args).size !== args.length
)
  throw new Error(
    "Usage: node --env-file=.env.nightshift-live.local --import tsx scripts/verify_nightshift.ts --connect [--workspace]",
  );
if (!args.includes("--connect"))
  throw new Error(
    "Nightshift acceptance requires --connect; this makes real model calls and scripted synthetic review/memory writes.",
  );
if (settings.mode !== "live" || process.env.MODEL_PROVIDER !== "meterless")
  throw new Error(
    "Nightshift acceptance requires explicit FINTRACE_MODE=live and MODEL_PROVIDER=meterless; fixture/mock execution is not accepted.",
  );
for (const key of [
  "DATABASE_URL",
  "ZETARIS_BASE_URL",
  "ZETARIS_ORG_ID",
  "ZETARIS_API_KEY",
])
  if (!process.env[key]?.trim()) throw new Error(`Missing ${key}`);
const config = modelConfiguration();
if (
  config.name !== "meterless" ||
  !config.token?.trim() ||
  !config.model?.trim()
)
  throw new Error(
    "Configure a Runtime token and an explicit cloud METERLESS_MODEL; no default model or direct-provider fallback is used.",
  );
const runtimeUrl = new URL(config.base);
if (
  !["http:", "https:"].includes(runtimeUrl.protocol) ||
  !["localhost", "127.0.0.1", "[::1]"].includes(runtimeUrl.hostname) ||
  runtimeUrl.username ||
  runtimeUrl.password ||
  runtimeUrl.search ||
  runtimeUrl.hash ||
  runtimeUrl.pathname.replace(/\/$/, "") !== "/v1"
)
  throw new Error(
    "This acceptance script requires the known local Nightshift Runtime at a loopback /v1 URL.",
  );
const sensitiveValues = [
  config.token,
  process.env.ZETARIS_API_KEY,
  process.env.DATABASE_URL,
].filter((value): value is string => !!value && value.length >= 8);
const metadataId = (value: unknown) =>
  typeof value === "string" &&
  /^[A-Za-z0-9][A-Za-z0-9_./:+-]{0,199}$/.test(value) &&
  !/^(?:sk-|nvapi-|hf_|gh[pousr]_|xox[baprs]-|AIza|ya29\.)/i.test(value) &&
  !sensitiveValues.some((secret) => value.includes(secret))
    ? value
    : undefined;
if (
  !metadataId(config.model) ||
  /^(?:webllm\/|mock|fixture|deterministic)/i.test(config.model)
)
  throw new Error(
    "Select an explicit real cloud model; device, fixture and mock model IDs are refused.",
  );
const workspace = args.includes("--workspace");
type Route = {
  requestedModel: string;
  returnedModel: string;
  routedModel: string;
  winner: string;
  winningProvider: string;
};
let expectedRoute: Route;
let stage = "runtime-probe";
class AcceptanceFailure extends Error {}
function fail(message: string): never {
  throw new AcceptanceFailure(message);
}
const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const requiredLabel = (value: unknown, field: string) =>
  metadataId(value) ??
  fail(`Missing or unsafe ${field}; no raw value was retained.`);
const cloudRoute = (route: Route) =>
  route.winningProvider !== "webllm" &&
  !Object.values(route).some((value) =>
    /^(?:webllm\/|mock|fixture|deterministic)/i.test(value),
  );
const runtimeFetch = (path: string, init: RequestInit = {}) =>
  fetch(config.base.replace(/\/$/, "") + path, {
    ...init,
    headers: { Authorization: "Bearer " + config.token!, ...init.headers },
    signal: AbortSignal.timeout(path === "/chat/completions" ? 180000 : 10000),
  });

await mkdir(".local/nightshift-check", { recursive: true });
const directory = await mkdtemp(
  resolve(".local/nightshift-check/live-nightshift-acceptance-"),
);
const tag = new Date().toISOString().replaceAll(/[^a-zA-Z0-9]/g, "");
const namespace = workspace ? "workspace" : `nightshift-live-${tag}`;
const storageDir = settings.storageDir;
let current: Awaited<ReturnType<typeof createApp>> | undefined;
const report: Record<string, unknown> & {
  runs: unknown[];
  lifecycle: unknown[];
  runtimeCorrelations: Record<string, unknown>[];
} = {
  startedAt: new Date().toISOString(),
  mode: "live",
  provider: config.name,
  model: config.model,
  syntheticDataOnly: true,
  namespace,
  runs: [],
  lifecycle: [],
  runtimeCorrelations: [],
  passed: false,
  signedReceiptVerified: false,
  reviewer:
    "Scripted synthetic reviewer exercising the real review API; not a customer decision or unobserved human approval.",
  notice:
    "Selected synthetic acceptance cases. Scripted reviewer exercises the application's real review API; this is not a customer decision, held-out accuracy evaluation or measured memory-efficiency improvement. Nightshift completion decisions are matched to read-only Runtime explanations. Their metadata is not a cryptographically signed receipt. Query IDs are application trace IDs, not Zetaris server-issued IDs.",
};
const persist = async () =>
  writeFile(
    join(directory, "summary.json"),
    JSON.stringify(report, null, 2) + "\n",
    { mode: 0o600 },
  );

const explainMetadata = (raw: unknown) => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const input = raw as Record<string, unknown>;
  const output: Record<string, unknown> = {};
  for (const key of [
    "decision_id",
    "request_id",
    "selected_strategy",
    "winner",
    "policy_version",
    "app",
    "mode",
  ]) {
    const value = metadataId(input[key]);
    if (value !== undefined) output[key] = value;
    else if (key === "winner" && input[key] === null) output[key] = null;
  }
  for (const key of ["estimated_cost", "estimated_savings", "reflex_ms"])
    if (typeof input[key] === "number" && Number.isFinite(input[key]))
      output[key] = input[key];
  if (
    typeof input.timestamp === "string" &&
    Number.isFinite(Date.parse(input.timestamp))
  )
    output.timestamp = new Date(input.timestamp).toISOString();
  if (Array.isArray(input.candidate_sources))
    output.candidate_sources = input.candidate_sources
      .map(metadataId)
      .filter(Boolean)
      .slice(0, 30);
  return output;
};
const correlateRequests = async (
  requests: ModelRequestTrace[],
  runId: string,
  operation: string,
) => {
  let successful = 0,
    correlated = 0;
  const winners = new Set<string>();
  const providers = new Set<string>();
  for (const trace of requests) {
    const record: Record<string, unknown> = {
      runId: metadataId(runId) ?? null,
      operation,
      traceId: metadataId(trace.id) ?? null,
      applicationStatus: trace.status,
      applicationProvider: metadataId(trace.provider) ?? null,
      requestedModel: metadataId(trace.model) ?? null,
      returnedModel: metadataId(trace.returnedModel) ?? null,
      httpRequestId: metadataId(trace.requestId) ?? null,
      meterlessDecisionId: metadataId(trace.meterlessDecisionId) ?? null,
      meterlessRoutedModel: metadataId(trace.meterlessRoutedModel) ?? null,
      meterlessWinningProvider:
        metadataId(trace.meterlessWinningProvider) ?? null,
      lookupSucceeded: false,
      correlationValid: false,
    };
    if (trace.status === "succeeded") successful++;
    const decisionId = metadataId(trace.meterlessDecisionId);
    if (trace.provider !== "meterless" || !decisionId) {
      record.reason =
        "Missing Nightshift decision metadata; no request-ID substitution was made.";
    } else {
      try {
        let response = await runtimeFetch(
          "/explain/" + encodeURIComponent(decisionId),
        );
        if (response.status === 404) {
          await response.body?.cancel();
          await new Promise((resolve) => setTimeout(resolve, 200));
          response = await runtimeFetch(
            "/explain/" + encodeURIComponent(decisionId),
          );
        }
        record.httpStatus = response.status;
        if (response.ok) {
          const metadata = explainMetadata(await response.json());
          record.explanation = metadata;
          record.lookupSucceeded = !!metadata;
          const valid =
            trace.status === "succeeded" &&
            metadata?.decision_id === decisionId &&
            metadata.winner === expectedRoute.winner &&
            metadata.app === "fintrace" &&
            !!metadataId(metadata.selected_strategy) &&
            metadata.selected_strategy !== "error" &&
            trace.model === expectedRoute.requestedModel &&
            trace.returnedModel === expectedRoute.returnedModel &&
            trace.meterlessRoutedModel === expectedRoute.routedModel &&
            trace.meterlessWinningProvider === expectedRoute.winningProvider;
          record.correlationValid = valid;
          if (valid) {
            correlated++;
            winners.add(metadata!.winner as string);
            if (trace.meterlessWinningProvider)
              providers.add(trace.meterlessWinningProvider);
          }
        } else await response.body?.cancel();
      } catch {
        record.reason =
          "Runtime explanation lookup unavailable; no raw error/prompt/response was retained.";
      }
    }
    report.runtimeCorrelations.push(record);
  }
  await writeFile(
    join(directory, "runtime-correlations.json"),
    JSON.stringify(report.runtimeCorrelations, null, 2) + "\n",
    { mode: 0o600 },
  );
  await persist();
  return {
    passed: successful > 0 && correlated === successful,
    successfulRequests: successful,
    correlatedSuccessfulRequests: correlated,
    winnerModels: [...winners],
    winningProviders: [...providers],
    failedAttempts: requests.filter((trace) => trace.status === "failed")
      .length,
  };
};

const open = async () => {
  const store = new PostgresStore(process.env.DATABASE_URL!);
  await store.init();
  if (
    (await store.runs()).some((run) =>
      ["queued", "running"].includes(run.status),
    )
  ) {
    await store.close();
    fail(
      "Existing active investigation detected; acceptance did not interrupt it.",
    );
  }
  return createApp({ store, mode: "live", storageDir, seed: false });
};
const summarize = (run: Investigation) => {
  const evidence = new Set(run.evidence.map((row) => row.id));
  const requests = run.modelRequests || [];
  return {
    runId: metadataId(run.id) ?? null,
    datasetId: metadataId(run.datasetId) ?? null,
    paymentId: metadataId(run.paymentId) ?? null,
    status: run.status,
    mode: run.mode,
    provider: metadataId(run.provider) ?? null,
    model: metadataId(run.model) ?? null,
    outcome: run.outcome,
    categories: run.findings.map((finding) => finding.category),
    citationsValid: [...run.findings, ...run.checks].every((item) =>
      item.evidenceIds.every((id) => evidence.has(id)),
    ),
    successfulQueries: run.queries.filter(
      (query) => query.status === "succeeded",
    ).length,
    queryCount: run.queries.length,
    queryTables: [
      ...new Set(
        run.queries
          .flatMap((query) => query.tables)
          .map(metadataId)
          .filter(Boolean),
      ),
    ],
    successfulModelRequests: requests.filter(
      (request) => request.status === "succeeded",
    ).length,
    returnedModels: [
      ...new Set(
        requests
          .map((request) => metadataId(request.returnedModel))
          .filter(Boolean),
      ),
    ],
    totalTokens: requests.reduce(
      (sum, request) => sum + (request.totalTokens || 0),
      0,
    ),
    memoryIds: run.memories.flatMap((memory) =>
      memory &&
      typeof memory === "object" &&
      "id" in memory &&
      typeof memory.id === "string"
        ? [memory.id]
        : [],
    ),
    durationMs: Date.parse(run.updatedAt) - Date.parse(run.createdAt),
    review: run.review
      ? {
          decision: run.review.decision,
          memoryId: metadataId(run.review.memoryId) ?? null,
          at: Number.isFinite(Date.parse(run.review.at))
            ? new Date(run.review.at).toISOString()
            : null,
        }
      : null,
  };
};
const execute = async (
  datasetId: string,
  paymentId: string,
  expected: Outcome,
  category: string,
  label: string,
  expectMemoryId?: string,
) => {
  const run = await current!.service.wait(
    (await current!.service.start(datasetId, paymentId, namespace)).id,
  );
  const summary = summarize(run);
  const provenance = await correlateRequests(
    run.modelRequests || [],
    run.id,
    "investigation",
  );
  const passed =
    run.status === "completed" &&
    run.mode === "live" &&
    run.provider === "meterless" &&
    run.model === expectedRoute.requestedModel &&
    run.outcome === expected &&
    summary.categories.includes(category) &&
    provenance.passed &&
    summary.citationsValid &&
    summary.successfulQueries === summary.queryCount &&
    summary.queryCount > 0 &&
    (expected === "insufficient_evidence" ||
      summary.successfulModelRequests > 0) &&
    (!expectMemoryId || summary.memoryIds.includes(expectMemoryId));
  const result = {
    label,
    passed,
    expectedOutcome: expected,
    expectedCategory: category,
    ...summary,
    runtimeProvenance: provenance,
  };
  report.runs.push(result);
  await persist();
  console.log(JSON.stringify(result));
  if (!passed)
    fail(
      `Acceptance case ${label} failed; inspect the sanitized report and the local application before retrying.`,
    );
  return run;
};

try {
  // This path intentionally checks the installed Mac application. It does not
  // accept fixture data or infer success from a provider label alone.
  const healthResponse = await fetch(new URL("/healthz", runtimeUrl), {
    signal: AbortSignal.timeout(10000),
  });
  report.runtimeHealthHttpStatus = healthResponse.status;
  if (!healthResponse.ok) {
    await healthResponse.body?.cancel();
    fail("The local Runtime health check failed.");
  }
  const health = asRecord(await healthResponse.json());
  const cloud = asRecord(asRecord(health.providers).cloud);
  const configuredProviders = Array.isArray(cloud.keys)
    ? cloud.keys.map(metadataId).filter((value): value is string => !!value)
    : [];
  if (
    health.engine !== "meterless" ||
    health.served !== "app" ||
    health.engine_ready !== true ||
    cloud.native !== true ||
    !configuredProviders.length
  )
    fail(
      "The local app Runtime is not ready with a native cloud provider key; no inference or device-model download was attempted.",
    );
  report.runtime = {
    engine: "meterless",
    served: "app",
    build: metadataId(health.build) ?? null,
    configuredProviders,
  };
  const started = Date.now();
  const response = await runtimeFetch("/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "meterless-app": "fintrace",
      "meterless-scope": "user",
    },
    body: JSON.stringify({
      model: config.model,
      messages: [
        {
          role: "user",
          content:
            'Reply with exactly the JSON object {"ok":true}, without markdown.',
        },
      ],
      max_tokens: 32,
      stream: false,
    }),
  });
  const probe: Record<string, unknown> = {
    at: new Date().toISOString(),
    durationMs: Date.now() - started,
    httpStatus: response.status,
    requestedModel: config.model,
    passed: false,
  };
  report.probe = probe;
  if (!response.ok) {
    await response.body?.cancel();
    fail(
      "The explicit cloud-model probe failed; the response body was omitted.",
    );
  }
  const body = asRecord(await response.json());
  const choices = Array.isArray(body.choices) ? body.choices : [];
  const message = asRecord(asRecord(choices[0]).message);
  let parsed: unknown;
  try {
    parsed =
      typeof message.content === "string"
        ? JSON.parse(message.content)
        : undefined;
  } catch {
    fail(
      "The cloud-model probe did not return valid JSON; no answer repair was used.",
    );
  }
  const output = asRecord(parsed);
  probe.jsonContractValid =
    output.ok === true && Object.keys(output).length === 1;
  if (!probe.jsonContractValid)
    fail("The cloud-model probe did not satisfy its exact JSON contract.");
  const meterless = asRecord(body.meterless);
  const decisionId = requiredLabel(
    meterless.decision_id,
    "probe Runtime decision ID",
  );
  probe.decisionId = decisionId;
  probe.httpRequestId =
    metadataId(
      response.headers.get("x-request-id") ||
        response.headers.get("x-meterless-request-id"),
    ) ?? null;
  const explanationResponse = await runtimeFetch(
    "/explain/" + encodeURIComponent(decisionId),
  );
  probe.explanationHttpStatus = explanationResponse.status;
  if (!explanationResponse.ok) {
    await explanationResponse.body?.cancel();
    fail("The probe's Runtime explanation was unavailable.");
  }
  const explanation = explainMetadata(await explanationResponse.json());
  probe.explanation = explanation;
  expectedRoute = {
    requestedModel: requiredLabel(config.model, "requested model"),
    returnedModel: requiredLabel(body.model, "returned model"),
    routedModel: requiredLabel(meterless.routed_model, "routed model"),
    winner: requiredLabel(explanation?.winner, "Runtime winner"),
    winningProvider: requiredLabel(
      asRecord(meterless.winning_route).provider,
      "winning provider",
    ),
  };
  report.expectedRoute = expectedRoute;
  if (
    explanation?.decision_id !== decisionId ||
    explanation.app !== "fintrace" ||
    !metadataId(explanation.selected_strategy) ||
    explanation.selected_strategy === "error" ||
    !cloudRoute(expectedRoute) ||
    !configuredProviders.includes(expectedRoute.winningProvider)
  )
    fail(
      "The cloud probe lacks a matching real FinTrace Runtime decision/provider; no alias equality or device fallback was assumed.",
    );
  probe.passed = true;
  await persist();
  // The probe is deliberately outside the application adapter. Honor its
  // configured request-start spacing before the first business model request.
  const spacingMs = Number(process.env.METERLESS_MIN_REQUEST_INTERVAL_MS || 0);
  if (!Number.isInteger(spacingMs) || spacingMs < 0 || spacingMs > 60000)
    fail(
      "METERLESS_MIN_REQUEST_INTERVAL_MS must be an integer between 0 and 60000.",
    );
  report.minRequestIntervalMs = spacingMs;
  if (spacingMs > 0) {
    stage = "post-probe-pacing";
    await new Promise((resolve) => setTimeout(resolve, spacingMs));
  }
  stage = "application-open";
  current = await open();
  const packets = buildManualPackets();
  packets.main.manifest.name = `FinTrace Nightshift live acceptance ${tag}`;
  packets.partial.manifest.name = `FinTrace Zetaris partial coverage ${tag}`;
  const lesson = JSON.parse(
    JSON.stringify(packets.main).replaceAll("DEMO", "NIGHTSHIFT_LESSON"),
  );
  lesson.manifest.name = `FinTrace Zetaris independent lesson ${tag}`;
  for (const rows of Object.values(lesson.tables) as Record<string, string>[][])
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
  const target = await current.store.saveDataset(packets.main);
  const partial = await current.store.saveDataset(packets.partial);
  const source = await current.store.saveDataset(lesson);
  report.datasets = {
    target: target.info.id,
    partial: partial.info.id,
    independentLesson: source.info.id,
  };
  await persist();
  stage = "normal";
  await execute(
    target.info.id,
    "PAY_DEMO_NORMAL",
    "no_anomaly_supported",
    "NO_FAILURE",
    "normal",
  );
  stage = "partial-coverage";
  await execute(
    partial.info.id,
    "PAY_DEMO_NORMAL",
    "insufficient_evidence",
    "EVIDENCE_GAP",
    "partial-coverage",
  );
  stage = "independent-anomaly-lesson";
  const sourceRun = await execute(
    source.info.id,
    "PAY_NIGHTSHIFT_LESSON_DUP",
    "anomaly_supported",
    "F06",
    "independent-anomaly-lesson",
  );
  stage = "memory-draft";
  const draftResponse = await current.app.inject({
    method: "POST",
    url: `/api/investigations/${sourceRun.id}/memory-draft`,
  });
  const withDraft = draftResponse.json<Investigation>();
  const draftProvenance = await correlateRequests(
    withDraft.memoryDraftRequests || [],
    sourceRun.id,
    "memory-draft",
  );
  if (
    draftResponse.statusCode !== 200 ||
    withDraft.memoryDraft?.status !== "ready" ||
    withDraft.memoryDraft.provider !== "meterless" ||
    !draftProvenance.passed
  )
    fail(
      "Memory draft generation did not produce a ready draft; no automatic fallback or approval was used.",
    );
  const content =
    "When reviewing possible duplicate payment allocations, retrieve allocations first, then reconcile settlements and ledger; establish invoice obligations and temporal coverage before judging a duplicate. Always obtain and verify the current payment evidence.";
  stage = "scripted-review";
  const approvalResponse = await current.app.inject({
    method: "POST",
    url: `/api/investigations/${sourceRun.id}/review`,
    payload: {
      decision: "accepted",
      notes:
        "Scripted synthetic acceptance reviewer: edited to an evidence-only procedure with no target identifiers, amounts, or classification answers.",
      approveMemory: true,
      memoryDraftId: withDraft.memoryDraft.id,
      memoryContent: content,
    },
  });
  const reviewed = approvalResponse.json<Investigation>();
  const memoryId = reviewed.review?.memoryId;
  if (
    approvalResponse.statusCode !== 200 ||
    reviewed.review?.decision !== "accepted" ||
    !memoryId
  )
    fail(
      "The real review API did not persist accepted review and approved memory.",
    );
  report.lifecycle.push({
    stage: "generate-edit-approve",
    sourceRunId: sourceRun.id,
    draftId: metadataId(withDraft.memoryDraft.id) ?? null,
    draftProvider: metadataId(withDraft.memoryDraft.provider) ?? null,
    draftModel: metadataId(withDraft.memoryDraft.model) ?? null,
    draftRequestCount: reviewed.memoryDraftRequests?.length || 0,
    runtimeProvenance: draftProvenance,
    approvedMemoryId: memoryId,
  });
  await persist();
  stage = "reopen-persistence";
  await current.app.close();
  current = undefined;
  current = await open();
  const persistedSource = await current.store.run(sourceRun.id);
  const memoriesResponse = await current.app.inject({
    method: "GET",
    url: `/api/memories?namespace=${encodeURIComponent(namespace)}`,
  });
  const persistedMemories = memoriesResponse.json<{
    memories: { id: string; source: string; status: string }[];
  }>().memories;
  const persisted =
    persistedSource?.review?.memoryId === memoryId &&
    persistedMemories.some(
      (memory) =>
        memory.id === memoryId &&
        memory.source === sourceRun.id &&
        memory.status === "active",
    );
  report.lifecycle.push({
    stage: "reopen-and-check-persistence",
    passed: persisted,
    sourceRunId: sourceRun.id,
    memoryId,
  });
  await persist();
  if (!persisted)
    fail(
      "Approved memory or review did not survive application wrapper recreation.",
    );
  stage = "target-anomaly-with-recall";
  await execute(
    target.info.id,
    "PAY_DEMO_DUP",
    "anomaly_supported",
    "F06",
    "target-anomaly-with-recall",
    memoryId,
  );
  report.runtimeWinnerModels = [
    ...new Set(
      report.runtimeCorrelations
        .map(
          (row) =>
            (row.explanation as Record<string, unknown> | undefined)?.winner,
        )
        .filter(Boolean),
    ),
  ];
  if (
    !(report.runtimeWinnerModels as string[]).every(
      (model) => model === expectedRoute.winner,
    )
  )
    fail(
      "A Runtime winner differs from the successfully smoke-tested cloud winner; no alias normalization was assumed.",
    );
  report.runtimeWinningProviders = [
    ...new Set(
      report.runtimeCorrelations
        .filter((row) => row.correlationValid)
        .map((row) => row.meterlessWinningProvider),
    ),
  ];
  stage = "complete";
  report.passed = true;
  report.completedAt = new Date().toISOString();
  await persist();
  console.log(
    JSON.stringify({
      passed: true,
      report: relative(process.cwd(), join(directory, "summary.json")),
      namespace,
    }),
  );
} catch (error) {
  report.failedAt = new Date().toISOString();
  report.failure =
    error instanceof AcceptanceFailure
      ? error.message
      : "An operation failed; raw errors, prompts and responses were omitted. Check the local application and configuration.";
  report.failedStage = stage;
  await persist();
  console.error(
    JSON.stringify({
      passed: false,
      report: relative(process.cwd(), join(directory, "summary.json")),
      failure: report.failure,
    }),
  );
  process.exitCode = 1;
} finally {
  await current?.app.close();
}
