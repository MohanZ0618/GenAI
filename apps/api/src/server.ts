import Fastify from "fastify";
import staticFiles from "@fastify/static";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";
import { z, ZodError } from "zod";
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
      .filter((d) => !d.info.removedAt)
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
  app.get("/api/datasets/:id", async (request, reply) => {
    const dataset = await store.dataset((request.params as { id: string }).id);
    if (!dataset) return reply.code(404).send({ error: "Dataset not found" });
    return {
      dataset: { ...dataset.info, caseCount: casesFor(dataset).length },
    };
  });
  const removalSchema = z
    .object({
      ids: z.array(z.string().min(1).max(100)).min(1).max(1000),
      removed: z.boolean(),
    })
    .strict();
  app.post("/api/datasets/removal", async (request) => {
    const { ids, removed } = removalSchema.parse(request.body);
    const results = [];
    for (const id of new Set(ids)) {
      try {
        await service.setDatasetRemoved(id, removed);
        results.push({ id, success: true });
      } catch (error) {
        results.push({
          id,
          success: false,
          error:
            error instanceof Error
              ? error.message
              : "Unable to update dataset.",
        });
      }
    }
    return { results };
  });
  app.get("/api/cases", async (request) => {
    const datasetId = (request.query as { datasetId?: string }).datasetId;
    if (!datasetId) throw new Error("datasetId is required");
    const datasets =
      datasetId === "all"
        ? (await store.datasets()).filter((d) => !d.info.removedAt)
        : [await store.dataset(datasetId)];
    if (datasets.some((d) => !d)) throw new Error("Dataset not found");
    if (datasets.some((d) => d?.info.removedAt))
      throw new Error(
        "Cannot list cases for a removed dataset. Restore it first.",
      );
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
  const namespaceSchema = z
    .object({ namespace: z.string().min(1).max(200).default("workspace") })
    .strict();
  app.get("/api/memories", async (request) => {
    const { namespace } = namespaceSchema.parse(request.query);
    return {
      memories: memory.list(namespace).filter((item) => !item.removedAt),
    };
  });
  app.post("/api/memories/removal", async (request) => {
    const { namespace } = namespaceSchema.parse(request.query);
    const { ids, removed } = removalSchema.parse(request.body);
    const results = [];
    for (const id of new Set(ids)) {
      try {
        memory.setRemoved(namespace, id, removed);
        results.push({ id, success: true });
      } catch (error) {
        results.push({
          id,
          success: false,
          error:
            error instanceof Error ? error.message : "Unable to update memory.",
        });
      }
    }
    return { results };
  });
  app.patch("/api/memories/:id", async (request) => {
    const { namespace } = namespaceSchema.parse(request.query);
    const { status } = z
      .object({ status: z.enum(["active", "inactive"]) })
      .strict()
      .parse(request.body);
    return memory.setStatus(
      namespace,
      (request.params as { id: string }).id,
      status,
    );
  });
  app.post("/api/investigations/:id/memory-draft", async (request) => {
    const { retry } = z
      .object({ retry: z.boolean().default(false) })
      .strict()
      .parse(request.body || {});
    return service.memoryDraft((request.params as { id: string }).id, retry);
  });
  app.post("/api/investigations/:id/review", async (request) => {
    const id = (request.params as { id: string }).id;
    const input = reviewSchema.parse(request.body);
    return service.mutate(id, async () => {
      const run = await store.run(id);
      if (!run) throw new Error("Investigation not found");
      if (run.status !== "completed")
        throw new Error("Only a completed investigation can be reviewed");
      let memoryId: string | undefined;
      if (input.approveMemory) {
        const draft = run.memoryDraft;
        if (
          input.memoryDraftId &&
          (draft?.id !== input.memoryDraftId || draft.status !== "ready")
        )
          throw new Error("Invalid memory draft identifier or state");
        const vendorId = run.evidence.find(
          (e) =>
            e.table === "payments" && e.record.payment_id === run.paymentId,
        )?.record.vendor_id;
        if (input.memoryScope === "vendor" && !vendorId)
          throw new Error("Vendor scope requires a known vendor");
        const namespace = run.memoryNamespace || "workspace";
        const prior = memory
          .list(namespace)
          .filter(
            (m) => m.source === id && m.status === "active" && !m.removedAt,
          );
        const same = prior.find(
          (m) =>
            m.content === input.memoryContent!.trim() &&
            m.scope === input.memoryScope,
        );
        if (prior.length && !same)
          throw Object.assign(
            new Error(
              "This investigation already has an active memory. Deactivate the existing memory before approving different content, or uncheck memory approval to save only the review.",
            ),
            { statusCode: 409 },
          );
        const record = await memory.approve(
          namespace,
          input.memoryContent!.trim(),
          run.id,
          {
            scope: input.memoryScope,
            vendorId: input.memoryScope === "vendor" ? vendorId : undefined,
            draftId: input.memoryDraftId,
            generationSource: input.memoryDraftId ? draft!.source : "manual",
            conditions: input.memoryDraftId
              ? draft!.conditions
              : "Human supplied investigation procedure",
            suggestedTools: input.memoryDraftId ? draft!.suggestedTools : [],
            evidenceIds: input.memoryDraftId ? draft!.evidenceIds : [],
          },
        );
        memoryId = record.id;
      }
      run.review = {
        decision: input.decision,
        notes: input.notes,
        at: new Date().toISOString(),
        ...(memoryId ? { memoryId } : {}),
      };
      await service.event(
        run,
        "review",
        `Human review recorded: ${input.decision}${memoryId ? "; reusable memory explicitly approved." : "."}`,
      );
      return run;
    });
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
