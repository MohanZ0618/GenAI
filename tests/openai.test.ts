import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdir, mkdtemp, readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  createModelProvider,
  modelConfiguration,
  onePassBaseline,
} from "../apps/api/src/integrations/model.ts";
import { createApp } from "../apps/api/src/server.ts";
import { FileStore } from "../apps/api/src/store.ts";
import {
  loadBuiltinDatasets,
  parseCsvPackage,
} from "../packages/data/src/index.ts";
import { exportRun } from "../apps/api/src/export.ts";
import { runPreflight } from "../scripts/preflight.ts";

const env = {
  MODEL_PROVIDER: "openai",
  OPENAI_API_KEY: "test-only-openai-token",
};
const input = { paymentId: "test", context: {}, history: [], memories: [] };
const signal = () => new AbortController().signal;
const reply = (output: unknown) =>
  new Response(
    JSON.stringify({
      choices: [
        { message: { content: JSON.stringify(output) }, finish_reason: "stop" },
      ],
    }),
    { status: 200 },
  );
const toolReply = () =>
  reply({
    tool: "ledger",
    reason: "Inspect accounting evidence",
    finish: false,
  });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("OpenAI provider", () => {
  it("uses the selected provider only and requires its credentials", () => {
    expect(() =>
      createModelProvider({
        MODEL_PROVIDER: "openai",
        NVIDIA_API_KEY: "unrelated-token",
      }),
    ).toThrow(/credentials/);
    expect(modelConfiguration({ FINTRACE_MODE: "local-model" }).name).toBe(
      "openai",
    );
    expect(() => createModelProvider({ MODEL_PROVIDER: "unknown" })).toThrow(
      /MODEL_PROVIDER/,
    );
  });
  it("sends OpenAI structured output and the configured model to the correct endpoint", async () => {
    const fetch = vi.fn().mockResolvedValue(toolReply());
    vi.stubGlobal("fetch", fetch);
    const provider = createModelProvider({
      ...env,
      OPENAI_BASE_URL: "https://example.test/v1/",
      OPENAI_MODEL: "gpt-4.1-mini",
    });
    expect((await provider.next(input, signal())).tool).toBe("ledger");
    const [url, request] = fetch.mock.calls[0];
    const body = JSON.parse(request.body);
    expect(url).toBe("https://example.test/v1/chat/completions");
    expect(request.headers.Authorization).toBe(`Bearer ${env.OPENAI_API_KEY}`);
    expect(body).toMatchObject({
      model: "gpt-4.1-mini",
      max_completion_tokens: 1000,
      store: false,
      response_format: { type: "json_schema", json_schema: { strict: true } },
    });
    expect(body).not.toHaveProperty("max_tokens");
    expect(request.body).not.toContain(env.OPENAI_API_KEY);
  });
  it("accepts explicit finish without a tool, and rejects missing decisions", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        reply({ tool: null, finish: true, reason: "Stop" }),
      )
      .mockResolvedValueOnce(
        reply({ tool: null, finish: false, reason: "Invalid" }),
      );
    vi.stubGlobal("fetch", fetch);
    const provider = createModelProvider(env);
    expect(await provider.next(input, signal())).toEqual({
      finish: true,
      reason: "Stop",
    });
    await expect(provider.next(input, signal())).rejects.toThrow();
  });
  it.each([401, 403, 404])(
    "does not retry permanent HTTP %s errors or reveal their body",
    async (status) => {
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(env.OPENAI_API_KEY, { status }));
      vi.stubGlobal("fetch", fetch);
      await expect(
        createModelProvider(env).next(input, signal()),
      ).rejects.toThrow(`(${status})`);
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );
  it.each([429, 503])(
    "retries transient HTTP %s exactly once",
    async (status) => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(new Response("", { status }))
        .mockResolvedValueOnce(toolReply());
      vi.stubGlobal("fetch", fetch);
      expect((await createModelProvider(env).next(input, signal())).tool).toBe(
        "ledger",
      );
      expect(fetch).toHaveBeenCalledTimes(2);
    },
  );
  it("limits retry exhaustion and sanitizes network errors", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error(env.OPENAI_API_KEY));
    vi.stubGlobal("fetch", fetch);
    await expect(
      createModelProvider(env).next(input, signal()),
    ).rejects.toThrow("Model connection failed");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each([
    { message: { content: "invalid JSON" } },
    {
      message: {
        content: '{"tool":"execute_sql","reason":"invalid","finish":false}',
      },
    },
    { message: { refusal: "refused" } },
    { message: { content: "{}" }, finish_reason: "length" },
    { message: {} },
  ])(
    "rejects malformed, forbidden, refused or truncated output %#",
    async (choice) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(JSON.stringify({ choices: [choice] })),
          ),
      );
      await expect(
        createModelProvider(env).next(input, signal()),
      ).rejects.toThrow();
    },
  );
  it("uses OpenAI for one-pass evaluation and validates evidence IDs", async () => {
    const answer = {
      outcome: "no_anomaly_supported",
      category: "NO_FAILURE",
      evidenceIds: ["e1"],
      explanation: "Reviewed evidence",
    };
    const fetch = vi
      .fn()
      .mockImplementation(async (_url: string, _request: RequestInit) =>
        reply(answer),
      );
    vi.stubGlobal("fetch", fetch);
    expect(
      await onePassBaseline(
        { paymentId: "p", evidence: [{ id: "e1" }], manifest: {} },
        signal(),
        env,
      ),
    ).toEqual(answer);
    expect(
      JSON.parse(fetch.mock.calls[0][1].body).response_format.json_schema.name,
    ).toBe("fintrace_baseline");
    await expect(
      onePassBaseline(
        { paymentId: "p", evidence: [], manifest: {} },
        signal(),
        env,
      ),
    ).rejects.toThrow(/unknown evidence/);
  });
});

describe("mode-aware preflight", () => {
  it("requires no connections in fixture mode", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(await runPreflight("fixture", true, env)).toMatchObject({
      ok: true,
      required: [],
      checks: {},
    });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("requires the selected OpenAI key, even if another provider has a key", async () => {
    expect(
      await runPreflight("local-model", false, {
        MODEL_PROVIDER: "openai",
        NVIDIA_API_KEY: "unrelated",
      }),
    ).toMatchObject({
      ok: false,
      required: ["model"],
      configured: { model: false },
    });
  });
  it("checks only OpenAI in local-model mode and reports failed connections", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(toolReply())
      .mockResolvedValueOnce(
        new Response("private-provider-response", { status: 401 }),
      );
    vi.stubGlobal("fetch", fetch);
    const config = {
      ...env,
      DATABASE_URL: "postgresql://invalid",
      ZETARIS_BASE_URL: "https://invalid",
      ZETARIS_ORG_ID: "1",
      ZETARIS_API_KEY: "unrelated",
    };
    expect(await runPreflight("local-model", true, config)).toMatchObject({
      ok: true,
      checks: { model: { status: "responded", provider: "openai" } },
    });
    const failed = await runPreflight("local-model", true, config);
    expect(failed.ok).toBe(false);
    expect(Object.keys(failed.checks)).toEqual(["model"]);
    expect(JSON.stringify(failed)).not.toContain(env.OPENAI_API_KEY);
    expect(JSON.stringify(failed)).not.toContain("private-provider-response");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

describe("local-model investigation", () => {
  it("runs all six representative cases using local evidence and mocked OpenAI, persists and exports provenance", async () => {
    vi.stubEnv("MODEL_PROVIDER", "openai");
    vi.stubEnv("OPENAI_API_KEY", env.OPENAI_API_KEY);
    const fetch = vi
      .fn()
      .mockImplementation(async (_url: string, request: RequestInit) => {
        const messages = JSON.parse(request.body as string).messages;
        const context = JSON.parse(messages[1].content).context;
        return reply({
          tool: context.availableTools[0],
          reason: "Retrieve verifier-required evidence",
          finish: false,
        });
      });
    vi.stubGlobal("fetch", fetch);
    await mkdir(".local", { recursive: true });
    const dir = await mkdtemp(join(process.cwd(), ".local", "openai-test-"));
    const { app, store, service } = await createApp({
      mode: "local-model",
      storageDir: dir,
      seed: false,
    });
    let lastId = "";
    try {
      const packets = await loadBuiltinDatasets();
      const cases = [
        ["Review packet 001", "anomaly_supported", "F06"],
        ["Review packet 013", "anomaly_supported", "F11"],
        ["Review packet 025", "anomaly_supported", "F12"],
        ["Review packet 037", "anomaly_supported", "F14"],
        ["Review packet 049", "no_anomaly_supported", "NO_FAILURE"],
        ["Coverage packet 001", "insufficient_evidence", "EVIDENCE_GAP"],
      ];
      for (const [name, outcome, category] of cases) {
        const packet = packets.find((p) => p.manifest.name === name)!;
        const ds = await store.saveDataset(packet);
        const started = await service.start(
          ds.info.id,
          packet.manifest.focusPaymentIds![0],
        );
        const run = await service.wait(started.id);
        lastId = run.id;
        expect(run, name).toMatchObject({
          status: "completed",
          mode: "local-model",
          provider: "openai",
          model: "gpt-4.1-mini",
          outcome,
        });
        expect(
          run.findings.some((f) => f.category === category),
          name,
        ).toBe(true);
        expect(run.modelTurns).toBeGreaterThan(0);
        expect(
          run.findings.every((f) =>
            f.evidenceIds.every((id) => run.evidence.some((e) => e.id === id)),
          ),
        ).toBe(true);
        expect(run.events[0].message).toContain("local snapshots; no Zetaris");
        expect(exportRun(run, "html").body).toContain(
          "REAL MODEL + LOCAL DATA",
        );
        expect(exportRun(run, "csv").body).toContain(
          '"local-model","openai","gpt-4.1-mini"',
        );
        expect(exportRun(run, "json").body).not.toContain(env.OPENAI_API_KEY);
      }
      const interrupted = structuredClone((await store.run(lastId))!);
      interrupted.id = "run-interrupted-test";
      interrupted.status = "running";
      interrupted.outcome = null;
      interrupted.findings = [];
      interrupted.actions = [];
      await store.saveRun(interrupted);
      const health = (await app.inject("/api/health")).json();
      expect(health).toMatchObject({
        mode: "local-model",
        provider: "openai",
        model: "gpt-4.1-mini",
        integrations: {
          zetaris: { status: "not used" },
          storage: { backend: "local immutable files" },
        },
      });
      expect(JSON.stringify(health)).not.toContain(env.OPENAI_API_KEY);
      expect(
        fetch.mock.calls.every(
          ([url]) => url === "https://api.openai.com/v1/chat/completions",
        ),
      ).toBe(true);
    } finally {
      await app.close();
    }
    const modelCallsBeforeRestart = fetch.mock.calls.length;
    const restarted = await createApp({
      mode: "local-model",
      storageDir: dir,
      seed: false,
    });
    try {
      expect(
        (await restarted.app.inject(`/api/investigations/${lastId}`)).json()
          .status,
      ).toBe("completed");
      const recovered = (
        await restarted.app.inject("/api/investigations/run-interrupted-test")
      ).json();
      expect(recovered).toMatchObject({
        status: "failed",
        outcome: null,
        provider: "openai",
        mode: "local-model",
      });
      expect(recovered.evidence.length).toBeGreaterThan(0);
      expect(recovered.error).toContain("process stopped");
      expect(fetch).toHaveBeenCalledTimes(modelCallsBeforeRestart);
    } finally {
      await restarted.app.close();
    }
  });
  it("does not fall back to fixture on OpenAI failure", async () => {
    vi.stubEnv("MODEL_PROVIDER", "openai");
    vi.stubEnv("OPENAI_API_KEY", env.OPENAI_API_KEY);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("private-details", { status: 401 })),
    );
    await mkdir(".local", { recursive: true });
    const dir = await mkdtemp(join(process.cwd(), ".local", "openai-fail-"));
    const { app, store, service } = await createApp({
      mode: "local-model",
      storageDir: dir,
      seed: false,
    });
    try {
      const packet = (await loadBuiltinDatasets())[0];
      const ds = await store.saveDataset(packet);
      const started = await service.start(
        ds.info.id,
        packet.manifest.focusPaymentIds![0],
      );
      const run = await service.wait(started.id);
      expect(run).toMatchObject({
        status: "failed",
        outcome: null,
        actions: [],
        provider: "openai",
      });
      expect(run.error).toContain("401");
      expect(JSON.stringify(run)).not.toContain("private-details");
    } finally {
      await app.close();
    }
  });
  it("ships valid populated import samples, a new version, and an invalid sample", async () => {
    const read = async (name: string) =>
      JSON.parse(await readFile(`data/manual-test/${name}`, "utf8"));
    const valid = await read("valid-bundle.json");
    const revised = await read("revised-bundle.json");
    expect(parseCsvPackage(valid).tables.payments.length).toBeGreaterThan(0);
    expect(parseCsvPackage(revised).manifest.clearingDays).not.toBe(
      valid.manifest.clearingDays,
    );
    const invalid = await read("invalid-missing-payments.json");
    expect(() => parseCsvPackage(invalid)).toThrow(/payments.csv/);
  });
});
