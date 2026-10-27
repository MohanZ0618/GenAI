import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createModelProvider,
  generateMemorySuggestion,
} from "../apps/api/src/integrations/model.ts";
import { runPreflight, runSubmissionPreflight } from "../scripts/preflight.ts";
import type { ModelRequestTrace } from "../packages/contracts/src/index.ts";

const env = {
  MODEL_PROVIDER: "meterless",
  METERLESS_BASE_URL: "http://127.0.0.1:8088/v1",
  METERLESS_RUNTIME_TOKEN: "test-runtime-token",
  METERLESS_MODEL: "test-cloud-lane",
  OPENAI_API_KEY: "unused-direct-key",
};
const input = {
  paymentId: "synthetic",
  context: {},
  history: [],
  memories: [],
};
const reply = (value: unknown) =>
  new Response(
    JSON.stringify({
      model: "test-underlying-model",
      choices: [{ message: { content: JSON.stringify(value) } }],
    }),
  );
afterEach(() => vi.unstubAllGlobals());

describe("Nightshift provider contract (mocked, not live proof)", () => {
  it("routes planning and memory drafting to the runtime with explicit output contracts", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        reply({ tool: "overview", reason: "Read evidence", finish: false }),
      )
      .mockResolvedValueOnce(
        reply({
          hasSuggestion: false,
          content: "",
          conditions: "",
          suggestedTools: [],
          evidenceIds: [],
          reason: "No reusable procedure",
        }),
      );
    vi.stubGlobal("fetch", fetch);
    const traces: ModelRequestTrace[] = [];
    await createModelProvider(env).next(
      input,
      AbortSignal.timeout(5000),
      async (trace) => {
        traces.push(trace);
      },
    );
    await generateMemorySuggestion(
      { evidence: [], verification: {}, gaps: [] },
      AbortSignal.timeout(5000),
      undefined,
      env,
    );
    expect(fetch).toHaveBeenCalledTimes(2);
    for (const [url, request] of fetch.mock.calls) {
      expect(url).toBe("http://127.0.0.1:8088/v1/chat/completions");
      expect(request.headers.Authorization).toBe("Bearer test-runtime-token");
      const body = JSON.parse(request.body);
      expect(body.model).toBe("test-cloud-lane");
      expect(body.messages[0].content).toContain("JSON Schema:");
      expect(body).not.toHaveProperty("response_format");
      expect(request.body).not.toContain(env.OPENAI_API_KEY);
    }
    expect(traces[0]).toMatchObject({
      provider: "meterless",
      model: "test-cloud-lane",
      returnedModel: "test-underlying-model",
      status: "succeeded",
    });
    expect(JSON.stringify(traces)).not.toContain(env.METERLESS_RUNTIME_TOKEN);
  });

  it("fails authentication without trying the direct OpenAI key", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response("private upstream error", { status: 401 }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(
      createModelProvider(env).next(input, AbortSignal.timeout(5000)),
    ).rejects.toThrow("401");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain("127.0.0.1:8088");
  });

  it("keeps retries on Nightshift and rejects invalid tool decisions", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetch);
    await expect(
      createModelProvider(env).next(input, AbortSignal.timeout(5000)),
    ).rejects.toThrow("connection failed");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(
      fetch.mock.calls.every(
        ([url]) => url === "http://127.0.0.1:8088/v1/chat/completions",
      ),
    ).toBe(true);
    fetch
      .mockReset()
      .mockResolvedValue(
        reply({ tool: "execute_payment", reason: "Unsafe", finish: false }),
      );
    await expect(
      createModelProvider(env).next(input, AbortSignal.timeout(5000)),
    ).rejects.toThrow();
  });

  it("reports the returned model in a connected model preflight", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          reply({ tool: "overview", reason: "Inspect", finish: false }),
        ),
    );
    expect(await runPreflight("local-model", true, env)).toMatchObject({
      ok: true,
      checks: {
        model: {
          provider: "meterless",
          returnedModel: "test-underlying-model",
          requests: 1,
        },
      },
    });
  });
});

describe("submission preflight", () => {
  it.each(["fixture", "local-model"] as const)(
    "blocks %s without contacting services",
    async (mode) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      const result = await runSubmissionPreflight(mode, true, env);
      expect(result).toMatchObject({
        ok: false,
        stage: "blocked",
        submissionReady: false,
      });
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("blocks direct OpenAI even when all credential fields exist", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const result = await runSubmissionPreflight("live", true, {
      ...env,
      MODEL_PROVIDER: "openai",
      DATABASE_URL: "test-db",
      ZETARIS_BASE_URL: "test-origin",
      ZETARIS_ORG_ID: "1",
      ZETARIS_API_KEY: "test-key",
    });
    expect(result.ok).toBe(false);
    expect(result.blockers.join(" ")).toContain("MODEL_PROVIDER=meterless");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not equate complete configuration with submission readiness", async () => {
    const result = await runSubmissionPreflight("live", false, {
      ...env,
      DATABASE_URL: "test-db",
      ZETARIS_BASE_URL: "test-origin",
      ZETARIS_ORG_ID: "1",
      ZETARIS_API_KEY: "test-key",
    });
    expect(result).toMatchObject({
      ok: true,
      stage: "configuration-only",
      submissionReady: false,
    });
    expect(result.remainingEvidence.length).toBeGreaterThan(0);
  });
});
