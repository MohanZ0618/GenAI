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
const reply = (value: unknown, meterless?: unknown) =>
  new Response(
    JSON.stringify({
      model: "test-underlying-model",
      meterless,
      choices: [{ message: { content: JSON.stringify(value) } }],
    }),
    { headers: { "x-meterless-request-id": "req_nightshift_test" } },
  );
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Nightshift provider contract (mocked, not live proof)", () => {
  it("keeps the Runtime decision separate from its HTTP request and records only route labels", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        reply(
          { tool: "overview", reason: "Read evidence", finish: false },
          {
            decision_id: "req_runtime_decision",
            routed_model: "webllm/Qwen2.5-1.5B-Instruct-q4f16_1-MLC",
            winning_route: {
              provider: "webllm",
              routed_model: "wrong-location",
            },
            receipt: { secret: "private-receipt" },
            phases: ["private-phase"],
            reason: "private-reasoning",
          },
        ),
      ),
    );
    const traces: ModelRequestTrace[] = [];
    await createModelProvider(env).next(
      input,
      new AbortController().signal,
      async (trace) => {
        traces.push(trace);
      },
    );
    expect(traces[0]).toMatchObject({
      requestId: "req_nightshift_test",
      meterlessDecisionId: "req_runtime_decision",
      meterlessWinningProvider: "webllm",
      meterlessRoutedModel: "webllm/Qwen2.5-1.5B-Instruct-q4f16_1-MLC",
      status: "succeeded",
    });
    expect(traces[0].requestId).not.toBe(traces[0].meterlessDecisionId);
    expect(JSON.stringify(traces)).not.toMatch(/private-|wrong-location/);
  });

  it.each([
    {
      decision_id: { value: "unsafe" },
      routed_model: ["unsafe"],
      winning_route: "unsafe",
    },
    {
      decision_id: "x".repeat(161),
      routed_model: "x".repeat(201),
      winning_route: { provider: "x".repeat(49) },
    },
    {
      decision_id: "decision\nunsafe",
      routed_model: "model\u0000unsafe",
      winning_route: { provider: "webllm\tunsafe" },
    },
    {
      decision_id: "sk-private-key",
      routed_model: env.METERLESS_RUNTIME_TOKEN,
      winning_route: { provider: "nvapi-private-key" },
    },
    {
      decision_id: "AIza-test-private-key",
      routed_model: "ya29.private-google-token",
      winning_route: { provider: "AIza-test-private-key" },
    },
  ])(
    "ignores unsafe optional Runtime metadata while validating the actual decision",
    async (metadata) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            reply(
              { tool: "overview", reason: "Read evidence", finish: false },
              metadata,
            ),
          ),
      );
      const traces: ModelRequestTrace[] = [];
      const result = await createModelProvider(env).next(
        input,
        new AbortController().signal,
        async (trace) => {
          traces.push(trace);
        },
      );
      expect(result.tool).toBe("overview");
      expect(traces[0]).toMatchObject({
        status: "succeeded",
        requestId: "req_nightshift_test",
      });
      expect(traces[0]).not.toHaveProperty("meterlessDecisionId");
      expect(traces[0]).not.toHaveProperty("meterlessWinningProvider");
      expect(traces[0]).not.toHaveProperty("meterlessRoutedModel");
    },
  );

  it("spaces consecutive Nightshift request starts when explicitly configured", async () => {
    vi.useFakeTimers();
    const starts: number[] = [];
    const fetch = vi.fn(async () => {
      starts.push(Date.now());
      return reply({
        tool: "overview",
        reason: "Read evidence",
        finish: false,
      });
    });
    vi.stubGlobal("fetch", fetch);
    const provider = createModelProvider({
      ...env,
      METERLESS_BASE_URL: "http://127.0.0.1:8088/pacing-consecutive",
      METERLESS_MIN_REQUEST_INTERVAL_MS: "1000",
    });
    await provider.next(input, new AbortController().signal);
    const second = provider.next(input, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await second;
    expect(starts[1] - starts[0]).toBe(1000);
  });

  it("shares pacing across concurrent provider instances without waiting for inference completion", async () => {
    vi.useFakeTimers();
    let finishFirst!: () => void;
    const firstResponse = new Promise<void>((resolve) => {
      finishFirst = resolve;
    });
    const starts: number[] = [];
    const fetch = vi.fn(async () => {
      starts.push(Date.now());
      if (starts.length === 1) await firstResponse;
      return reply({
        tool: "overview",
        reason: "Read evidence",
        finish: false,
      });
    });
    vi.stubGlobal("fetch", fetch);
    const paced = {
      ...env,
      METERLESS_BASE_URL: "http://127.0.0.1:8088/pacing-concurrent/",
      METERLESS_MIN_REQUEST_INTERVAL_MS: "1000",
    };
    const calls = [
      createModelProvider(paced).next(input, new AbortController().signal),
      createModelProvider({
        ...paced,
        METERLESS_BASE_URL: paced.METERLESS_BASE_URL.slice(0, -1),
      }).next(input, new AbortController().signal),
      createModelProvider(paced).next(input, new AbortController().signal),
    ];
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetch).toHaveBeenCalledTimes(3);
    finishFirst();
    await Promise.all(calls);
    expect(starts.map((at) => at - starts[0])).toEqual([0, 1000, 2000]);
  });

  it("paces retries through the same Runtime without increasing their budget", async () => {
    vi.useFakeTimers();
    const starts: number[] = [];
    const fetch = vi.fn(async () => {
      starts.push(Date.now());
      return starts.length === 1
        ? new Response("upstream unavailable", { status: 502 })
        : reply({ tool: "overview", reason: "Read evidence", finish: false });
    });
    vi.stubGlobal("fetch", fetch);
    const call = createModelProvider({
      ...env,
      METERLESS_BASE_URL: "http://127.0.0.1:8088/pacing-retry",
      METERLESS_MIN_REQUEST_INTERVAL_MS: "1000",
    }).next(input, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await call;
    expect(starts[1] - starts[0]).toBe(1000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("cancels a queued request promptly and never sends it or blocks later starts", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () =>
      reply({ tool: "overview", reason: "Read evidence", finish: false }),
    );
    vi.stubGlobal("fetch", fetch);
    const provider = createModelProvider({
      ...env,
      METERLESS_BASE_URL: "http://127.0.0.1:8088/pacing-cancel",
      METERLESS_MIN_REQUEST_INTERVAL_MS: "1000",
    });
    await provider.next(input, new AbortController().signal);
    const second = provider.next(input, new AbortController().signal);
    const controller = new AbortController();
    const traces: ModelRequestTrace[] = [];
    const cancelled = provider.next(input, controller.signal, async (trace) => {
      traces.push(trace);
    });
    const rejection = expect(cancelled).rejects.toThrow("connection failed");
    controller.abort();
    await rejection;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(traces).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      status: "cancelled",
      errorCode: "cancelled",
    });
    await vi.advanceTimersByTimeAsync(1000);
    await second;
    expect(fetch).toHaveBeenCalledTimes(2);
    const fourth = provider.next(input, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(1000);
    await fourth;
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each(["-1", "60001", "1.5", "NaN", "Infinity"])(
    "rejects invalid Nightshift pacing value %s before contacting the Runtime",
    (interval) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      expect(() =>
        createModelProvider({
          ...env,
          METERLESS_MIN_REQUEST_INTERVAL_MS: interval,
        }),
      ).toThrow("METERLESS_MIN_REQUEST_INTERVAL_MS");
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("routes planning and memory drafting to the runtime with explicit output contracts", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
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
      expect(request.headers["meterless-app"]).toBe("fintrace");
      expect(request.headers["meterless-scope"]).toBe("user");
      const body = JSON.parse(request.body);
      expect(body.model).toBe("test-cloud-lane");
      expect(body.messages[0].content).toContain("JSON Schema:");
      expect(body).not.toHaveProperty("response_format");
      expect(request.body).not.toContain(env.OPENAI_API_KEY);
    }
    expect(
      timeout.mock.calls.filter(([milliseconds]) => milliseconds === 180000),
    ).toHaveLength(2);
    expect(timeout).not.toHaveBeenCalledWith(90000);
    expect(traces[0]).toMatchObject({
      provider: "meterless",
      model: "test-cloud-lane",
      returnedModel: "test-underlying-model",
      requestId: "req_nightshift_test",
      status: "succeeded",
    });
    expect(JSON.stringify(traces)).not.toContain(env.METERLESS_RUNTIME_TOKEN);
  });

  it.each(["openai", "deepseek"] as const)(
    "keeps %s requests separate from the Nightshift protocol and load timeout",
    async (provider) => {
      const timeout = vi.spyOn(AbortSignal, "timeout");
      const fetch = vi.fn().mockResolvedValue(
        reply(
          { tool: "overview", reason: "Read evidence", finish: false },
          {
            decision_id: "foreign-decision",
            routed_model: "foreign-model",
            winning_route: { provider: "foreign-provider" },
          },
        ),
      );
      vi.stubGlobal("fetch", fetch);
      const traces: ModelRequestTrace[] = [];
      await createModelProvider({
        MODEL_PROVIDER: provider,
        OPENAI_API_KEY: "test-openai-token",
        DEEPSEEK_API_KEY: "test-deepseek-token",
        METERLESS_MIN_REQUEST_INTERVAL_MS: "invalid-for-Nightshift-only",
      }).next(input, new AbortController().signal, async (trace) => {
        traces.push(trace);
      });
      expect(fetch).toHaveBeenCalledTimes(1);
      const request = fetch.mock.calls[0][1];
      expect(request.headers).not.toHaveProperty("meterless-app");
      expect(request.headers).not.toHaveProperty("meterless-scope");
      expect(timeout).toHaveBeenCalledWith(90000);
      expect(timeout).not.toHaveBeenCalledWith(180000);
      expect(traces[0]).not.toHaveProperty("meterlessDecisionId");
      expect(traces[0]).not.toHaveProperty("meterlessWinningProvider");
      expect(traces[0]).not.toHaveProperty("meterlessRoutedModel");
    },
  );

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
