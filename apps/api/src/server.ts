import Fastify from "fastify";
import staticFiles from "@fastify/static";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";
import { ZodError } from "zod";
import { settings } from "./config.ts";
import { FileStore, PostgresStore, type Store } from "./store.ts";
import { MemoryService } from "./integrations/memory.ts";
import { InvestigationService, casesFor } from "./service.ts";
import {
  startSchema,
  batchStartSchema,
  reviewSchema,
} from "../../../packages/contracts/src/index.ts";
import {
  loadBuiltinDatasets,
  parseCsvPackage,
  getTemplates,
  ImportError,
} from "../../../packages/data/src/index.ts";
import { exportRun } from "./export.ts";
import { modelConfiguration } from "./integrations/model.ts";
import type {
  Mode,
  BatchStartResponse,
  BatchStartResult,
} from "../../../packages/contracts/src/index.ts";

export async function createApp(
  options: {
    store?: Store;
    mode?: Mode;
    storageDir?: string;
    seed?: boolean;
  } = {},
) {
  const mode = options.mode || settings.mode;
  const storageDir = options.storageDir || settings.storageDir;
  if (mode === "live" && !options.store && !process.env.DATABASE_URL)
    throw new Error("Live mode requires DATABASE_URL");
  const store =
    options.store ||
    (mode === "live"
      ? new PostgresStore(process.env.DATABASE_URL!)
      : new FileStore(storageDir));
  await store.init();
  if (options.seed !== false)
    for (const data of await loadBuiltinDatasets())
      await store.saveDataset(data, true);
  const memory = new MemoryService(join(storageDir, "memory"));
  const service = new InvestigationService(store, mode, memory);
  await service.recover();
  const app = Fastify({ logger: false, bodyLimit: 20 * 1024 * 1024 });
  app.setErrorHandler((error, request, reply) => {
    if (error instanceof ZodError)
      return reply
        .code(400)
        .send({ error: "Validation failed", issues: error.issues });
    if (error instanceof ImportError)
      return reply
        .code(400)
        .send({ error: error.message, issues: error.issues });
    const status =
      error.statusCode && error.statusCode < 500
        ? error.statusCode
        : /not found/i.test(error.message)
          ? 404
          : /missing|must|invalid|requires|only|cannot|review|configuration/i.test(
                error.message,
              )
            ? 400
            : 500;
    return reply.code(status).send({
      error:
        status === 500
          ? "The request failed. Check local configuration and retry."
          : error.message,
    });
  });
  app.get("/api/health", async () => {
    const config = modelConfiguration({ ...process.env, FINTRACE_MODE: mode });
    const modelConfigured = !!(config.token?.trim() && config.model?.trim());
    return {
      mode,
      provider: mode === "fixture" ? "deterministic-fixture" : config.name,
      model: mode === "fixture" ? "none" : config.model,
      integrations: {
        zetaris: {
          status: mode !== "live" ? "not used" : "not verified",
          configured: !!(
            process.env.ZETARIS_BASE_URL &&
            process.env.ZETARIS_API_KEY &&
            process.env.ZETARIS_ORG_ID
          ),
          verified: false,
        },
        model: {
          configured: modelConfigured,
          status:
            mode === "fixture"
              ? "not used"
              : modelConfigured
                ? "configured; not verified"
                : "not configured",
          verified: false,
        },
        memory: {
          configured: true,
          implementation:
            "Meterless H-MEM reference; deterministic mock embeddings",
        },
        storage: {
          backend: mode === "live" ? "PostgreSQL" : "local immutable files",
          status: mode === "live" ? "PostgreSQL" : "local immutable files",
        },
      },
    };
  });
  app.get("/api/datasets", async () => ({
    datasets: (await store.datasets())
      .map((d) => ({ ...d.info, caseCount: casesFor(d).length }))
      .sort((a, b) => a.name.localeCompare(b.name)),
  }));
  app.post("/api/datasets", async (request, reply) => {
    const raw = request.body as {
      manifest: unknown;
      files: Record<string, string>;
    };
    if (!raw || typeof raw.files !== "object" || !raw.files)
      throw new Error("Import requires manifest and CSV files");
    const data = parseCsvPackage(raw);
    const saved = await store.saveDataset(data);
    return reply
      .code(201)
      .send({ dataset: { ...saved.info, caseCount: casesFor(saved).length } });
  });
  app.get("/api/templates", async () => getTemplates());
  app.get("/api/cases", async (request) => {
    const datasetId = (request.query as { datasetId?: string }).datasetId;
    if (!datasetId) throw new Error("datasetId is required");
    const datasets =
      datasetId === "all"
        ? await store.datasets()
        : [await store.dataset(datasetId)];
    if (datasets.some((d) => !d)) throw new Error("Dataset not found");
    const runs = (await store.runs())
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .filter(
        (run) =>
          run.mode === mode &&
          (run.memoryNamespace || "workspace") === "workspace",
      );
    const allDatasets = await store.datasets();
    return {
      cases: datasets
        .flatMap((ds) =>
          casesFor(ds!).map((c) => {
            const matching = runs.filter(
              (r) => r.datasetId === c.datasetId && r.paymentId === c.paymentId,
            );
            const run =
              matching.find((r) =>
                ["queued", "running", "completed"].includes(r.status),
              ) || matching[0];
            const previous =
              !run &&
              runs.find(
                (r) =>
                  r.paymentId === c.paymentId &&
                  r.status === "completed" &&
                  allDatasets.some(
                    (other) =>
                      other.info.id === r.datasetId &&
                      other.info.name === ds!.info.name &&
                      other.info.createdAt < ds!.info.createdAt,
                  ),
              );
            return {
              ...c,
              status: run?.review ? "reviewed" : run?.status || "unreviewed",
              investigationId: run?.id,
              outcome: run?.status === "completed" ? run.outcome : null,
              updateAvailable: !!previous,
            };
          }),
        )
        .sort((a, b) => a.vendor.localeCompare(b.vendor)),
    };
  });
  app.post("/api/investigations", async (request, reply) => {
    const input = startSchema.parse(request.body);
    return reply
      .code(202)
      .send(await service.start(input.datasetId, input.paymentId));
  });
  app.post("/api/investigations/batch", async (request, reply) => {
    const input = batchStartSchema.parse(request.body);
    const unique = [
      ...new Map(
        input.cases.map((item) => [
          JSON.stringify([item.datasetId, item.paymentId]),
          item,
        ]),
      ).values(),
    ];
    const results: BatchStartResult[] = new Array(unique.length);
    let cursor = 0;
    await Promise.all(
      Array.from({ length: Math.min(3, unique.length) }, async () => {
        while (cursor < unique.length) {
          const index = cursor++;
          const item = unique[index];
          try {
            const run = await service.start(item.datasetId, item.paymentId);
            results[index] = {
              ...item,
              investigationId: run.id,
              status: run.status,
            };
          } catch (error) {
            const message =
              error instanceof Error &&
              /not found|configuration|requires|cannot/i.test(error.message)
                ? error.message
                : "Could not start investigation. Check configuration and retry.";
            results[index] = { ...item, error: message };
          }
        }
      }),
    );
    return reply.code(202).send({
      results,
      concurrency: service.concurrency,
    } satisfies BatchStartResponse);
  });
  app.get("/api/investigations/:id", async (request, reply) => {
    const run = await store.run((request.params as { id: string }).id);
    return run || reply.code(404).send({ error: "Investigation not found" });
  });
  app.post("/api/investigations/:id/cancel", async (request, reply) => {
    const run = await service.cancel((request.params as { id: string }).id);
    return run || reply.code(404).send({ error: "Investigation not found" });
  });
  app.post("/api/investigations/:id/review", async (request, reply) => {
    const id = (request.params as { id: string }).id;
    const input = reviewSchema.parse(request.body);
    const run = await store.run(id);
    if (!run) return reply.code(404).send({ error: "Investigation not found" });
    if (run.status !== "completed")
      throw new Error("Only a completed investigation can be reviewed");
    const now = new Date().toISOString();
    let memoryId: string | undefined;
    if (input.approveMemory) {
      const record = await memory.approve(
        "workspace",
        input.memoryContent!,
        run.id,
      );
      memoryId = record.id;
    }
    run.review = {
      decision: input.decision,
      notes: input.notes,
      at: now,
      ...(memoryId ? { memoryId } : {}),
    };
    await service.event(
      run,
      "review",
      `Human review recorded: ${input.decision}${memoryId ? "; reusable memory explicitly approved." : "."}`,
    );
    return run;
  });
  app.get("/api/investigations/:id/export", async (request, reply) => {
    const run = await store.run((request.params as { id: string }).id);
    if (!run) return reply.code(404).send({ error: "Investigation not found" });
    const format = (request.query as { format?: string }).format || "json";
    const exported = exportRun(run, format);
    return reply
      .header(
        "Content-Disposition",
        `attachment; filename="fintrace-${run.id}.${exported.extension}"`,
      )
      .type(exported.type)
      .send(exported.body);
  });
  app.get("/api/investigations/:id/events", async (request, reply) => {
    const id = (request.params as { id: string }).id;
    if (!(await store.run(id)))
      return reply.code(404).send({ error: "Investigation not found" });
    reply.hijack();
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    let last = Number(request.headers["last-event-id"] || 0);
    let busy = false;
    const tick = async () => {
      if (busy || reply.raw.destroyed) return;
      busy = true;
      try {
        const run = await store.run(id);
        if (!run) {
          reply.raw.end();
          return;
        }
        for (const event of run.events)
          if (Number(event.id) > last) {
            reply.raw.write(
              `id: ${event.id}\ndata: ${JSON.stringify(event)}\n\n`,
            );
            last = Number(event.id);
          }
        if (!["queued", "running"].includes(run.status)) {
          clearInterval(timer);
          reply.raw.end();
        }
      } finally {
        busy = false;
      }
    };
    const timer = setInterval(
      () => void tick().catch(() => reply.raw.end()),
      250,
    );
    request.raw.on("close", () => clearInterval(timer));
    await tick();
  });
  if (existsSync(resolve("apps/web/dist/index.html"))) {
    await app.register(staticFiles, { root: resolve("apps/web/dist") });
    app.setNotFoundHandler((request, reply) =>
      request.url.startsWith("/api/")
        ? reply.code(404).send({ error: "Route not found" })
        : reply.sendFile("index.html"),
    );
  }
  app.addHook("onClose", async () => {
    await service.close();
    await store.close();
  });
  return { app, store, service };
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  const { app } = await createApp();
  await app.listen({ host: settings.host, port: settings.port });
  console.log(
    `FinTrace: http://${settings.host}:${settings.port} (${settings.mode} mode)`,
  );
  for (const event of ["SIGINT", "SIGTERM"] as const)
    process.once(event, () => {
      void app.close();
    });
}
