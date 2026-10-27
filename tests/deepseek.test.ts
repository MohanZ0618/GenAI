import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createModelProvider,
  generateMemorySuggestion,
  modelConfiguration,
  onePassBaseline,
} from "../apps/api/src/integrations/model.ts";
import type {
  EvidenceReference,
  ModelRequestTrace,
} from "../packages/contracts/src/index.ts";

const nativeFetch = globalThis.fetch;
const token = "test-only-deepseek-token";
const input = {
  paymentId: "PAY_DEEPSEEK",
  context: { gaps: ["ledger"] },
  history: [],
  memories: [],
};
const signal = () => new AbortController().signal;
const servers: Server[] = [];
type CapturedRequest = {
  path: string;
  authorization: string | undefined;
  body: Record<string, any>;
};
type MockReply = { status?: number; body: unknown };

function envelope(output: unknown, extraMessage: Record<string, unknown> = {}) {
  return {
    model: "deepseek-flash-local-fixture",
    usage: { prompt_tokens: 30, completion_tokens: 12, total_tokens: 42 },
    choices: [
      {
        finish_reason: "stop",
        message: { ...extraMessage, content: JSON.stringify(output) },
      },
    ],
  };
}

function rawEnvelope(content: string) {
  const body = envelope({});
  body.choices[0].message.content = content;
  return body;
}

async function mockDeepSeek(
  handler: (request: CapturedRequest) => MockReply | undefined,
) {
  const requests: CapturedRequest[] = [];
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    const captured = {
      path: request.url!,
      authorization: request.headers.authorization,
      body: JSON.parse(raw),
    };
    requests.push(captured);
    const body = captured.body;
    // This local server accepts the DeepSeek JSON-mode contract, and rejects
    // OpenAI-only structured-output parameters rather than silently ignoring them.
    const compatible =
      request.method === "POST" &&
      request.url === "/v1/chat/completions" &&
      captured.authorization === `Bearer ${token}` &&
      body.response_format?.type === "json_object" &&
      body.thinking?.type === "disabled" &&
      typeof body.max_tokens === "number" &&
      body.max_tokens > 0 &&
      !Object.hasOwn(body, "max_completion_tokens") &&
      !Object.hasOwn(body, "store") &&
      !Object.hasOwn(body.response_format, "json_schema") &&
      body.messages?.some((message: { content: string }) =>
        /json/i.test(message.content),
      );
    if (!compatible) {
      response.writeHead(400, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ error: "Unsupported provider request" }));
      return;
    }
    const result = handler(captured);
    if (!result) return; // An intentionally pending response for cancellation.
    response.writeHead(result.status ?? 200, {
      "Content-Type": "application/json",
      "x-request-id": "deepseek-local-request",
    });
    response.end(JSON.stringify(result.body));
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1/`;
  return {
    requests,
    env: {
      MODEL_PROVIDER: "deepseek",
      DEEPSEEK_API_KEY: token,
      DEEPSEEK_BASE_URL: base,
    },
  };
}

beforeEach(() => vi.stubGlobal("fetch", nativeFetch));
afterEach(async () => {
  for (const server of servers.splice(0)) {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
  vi.unstubAllGlobals();
});

describe("DeepSeek provider", () => {
  it("uses explicit DeepSeek settings without borrowing another provider's key", () => {
    expect(modelConfiguration({ MODEL_PROVIDER: "deepseek" })).toMatchObject({
      name: "deepseek",
      base: "https://api.deepseek.com",
      model: "deepseek-flash",
    });
    expect(() =>
      createModelProvider({
        MODEL_PROVIDER: "deepseek",
        OPENAI_API_KEY: "unrelated-openai-token",
        NVIDIA_API_KEY: "unrelated-nvidia-token",
      }),
    ).toThrow(/deepseek.*credentials/i);
  });

  it("selects evidence tools over compatible HTTP and records the actual provider without exposing reasoning", async () => {
    const privateReasoning = "PRIVATE_REASONING_MUST_NOT_ENTER_THE_TRACE";
    const mock = await mockDeepSeek(() => ({
      body: envelope(
        {
          tool: "ledger",
          reason: "Inspect accounting evidence",
          finish: false,
        },
        { reasoning_content: privateReasoning },
      ),
    }));
    const traces: ModelRequestTrace[] = [];
    const provider = createModelProvider(mock.env);
    const result = await provider.next(input, signal(), async (trace) => {
      traces.push(trace);
    });
    expect(provider).toMatchObject({
      name: "deepseek",
      model: "deepseek-flash",
    });
    expect(result).toEqual({
      tool: "ledger",
      reason: "Inspect accounting evidence",
      finish: false,
    });
    expect(mock.requests).toHaveLength(1);
    expect(mock.requests[0].body.model).toBe("deepseek-flash");
    expect(mock.requests[0].body.max_tokens).toBe(1000);
    expect(mock.requests[0].body.messages[0].content).toContain(
      "Write the user-facing reason in English",
    );
    expect(mock.requests[0].body.messages[0].content).toContain(
      "Preserve exact record IDs and quoted source values",
    );
    expect(JSON.stringify(mock.requests[0].body)).not.toContain(token);
    expect(traces).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      provider: "deepseek",
      model: "deepseek-flash",
      returnedModel: "deepseek-flash-local-fixture",
      status: "succeeded",
      httpStatus: 200,
      requestId: "deepseek-local-request",
      inputTokens: 30,
      outputTokens: 12,
      totalTokens: 42,
    });
    expect(JSON.stringify({ result, traces })).not.toContain(privateReasoning);
    expect(JSON.stringify(traces)).not.toContain(token);
  });

  it("honors an explicitly selected model and accepts a final decision without a tool", async () => {
    const mock = await mockDeepSeek(() => ({
      body: envelope({
        tool: null,
        reason: "No missing evidence",
        finish: true,
      }),
    }));
    const provider = createModelProvider({
      ...mock.env,
      DEEPSEEK_MODEL: "deepseek-v4-pro",
    });
    expect(await provider.next(input, signal())).toEqual({
      reason: "No missing evidence",
      finish: true,
    });
    expect(mock.requests[0].body.model).toBe("deepseek-v4-pro");
  });

  it("accepts a complete uppercase JSON fence with surrounding whitespace without another request", async () => {
    const answer = {
      tool: "ledger",
      reason: "Inspect accounting evidence",
      finish: false,
    };
    const mock = await mockDeepSeek(() => ({
      body: rawEnvelope(
        `\uFEFF \n\t\`\`\`JSON\n${JSON.stringify(answer)}\n\`\`\` \n`,
      ),
    }));
    expect(await createModelProvider(mock.env).next(input, signal())).toEqual(
      answer,
    );
    expect(mock.requests).toHaveLength(1);
  });

  it("retries malformed final JSON once and records both failed and successful requests", async () => {
    const privateOutput = "PRIVATE_MALFORMED_RESPONSE_MUST_NOT_BE_REPLAYED";
    const answer = {
      tool: "ledger",
      reason: "Inspect accounting evidence",
      finish: false,
    };
    let attempts = 0;
    const mock = await mockDeepSeek(() => ({
      body: ++attempts === 1 ? rawEnvelope(privateOutput) : envelope(answer),
    }));
    const traces: ModelRequestTrace[] = [];
    expect(
      await createModelProvider(mock.env).next(
        input,
        signal(),
        async (trace) => {
          traces.push(trace);
        },
      ),
    ).toEqual(answer);
    expect(mock.requests).toHaveLength(2);
    expect(traces).toMatchObject([
      {
        attempt: 1,
        status: "failed",
        errorCode: "invalid_json",
        httpStatus: 200,
      },
      { attempt: 2, status: "succeeded", httpStatus: 200 },
    ]);
    expect(JSON.stringify(traces)).not.toContain(privateOutput);
    expect(JSON.stringify(mock.requests[1].body)).not.toContain(privateOutput);
    expect(mock.requests[1].body.messages[0].content).not.toBe(
      mock.requests[0].body.messages[0].content,
    );
    expect(mock.requests[1].body.messages[0].content).toContain("JSON Schema");
    expect(mock.requests[1].body.messages[0].content).toContain(
      '"required":["tool","reason","finish"]',
    );
  });

  it("stops after two malformed responses without leaking provider output in errors, traces, or the correction prompt", async () => {
    const privateOutput = `PRIVATE_MALFORMED_RESPONSE ${token}`;
    const mock = await mockDeepSeek(() => ({
      body: rawEnvelope(privateOutput),
    }));
    const traces: ModelRequestTrace[] = [];
    const result = createModelProvider(mock.env).next(
      input,
      signal(),
      async (trace) => {
        traces.push(trace);
      },
    );
    await expect(result).rejects.toThrow("Model returned invalid JSON");
    await expect(result).rejects.not.toThrow(privateOutput);
    await expect(result).rejects.not.toThrow(token);
    expect(mock.requests).toHaveLength(2);
    expect(traces).toMatchObject([
      { attempt: 1, status: "failed", errorCode: "invalid_json" },
      { attempt: 2, status: "failed", errorCode: "invalid_json" },
    ]);
    expect(JSON.stringify(traces)).not.toContain(privateOutput);
    expect(JSON.stringify(traces)).not.toContain(token);
    expect(
      JSON.stringify(mock.requests.map((request) => request.body)),
    ).not.toContain(privateOutput);
  });

  it.each(["network", "503"])(
    "shares the two-request retry budget between a %s failure and malformed JSON",
    async (failure) => {
      let requests = 0;
      const mock = await mockDeepSeek(() => {
        if (failure === "503" && ++requests === 1)
          return { status: 503, body: { error: "Temporary provider error" } };
        return { body: rawEnvelope("malformed final JSON") };
      });
      const fetch = vi.fn<typeof nativeFetch>().mockImplementation(nativeFetch);
      if (failure === "network")
        fetch.mockRejectedValueOnce(new Error("Temporary connection error"));
      vi.stubGlobal("fetch", fetch);
      const traces: ModelRequestTrace[] = [];
      await expect(
        createModelProvider(mock.env).next(input, signal(), async (trace) => {
          traces.push(trace);
        }),
      ).rejects.toThrow("Model returned invalid JSON");
      expect(fetch).toHaveBeenCalledTimes(2);
      expect(mock.requests).toHaveLength(failure === "network" ? 1 : 2);
      expect(traces).toMatchObject([
        {
          attempt: 1,
          status: "failed",
          errorCode: failure === "network" ? "connection_failed" : "http_503",
        },
        { attempt: 2, status: "failed", errorCode: "invalid_json" },
      ]);
    },
  );

  it("does not retry malformed JSON when cancelled after the first failed request", async () => {
    const mock = await mockDeepSeek(() => ({
      body: rawEnvelope("malformed final JSON"),
    }));
    const controller = new AbortController();
    const traces: ModelRequestTrace[] = [];
    await expect(
      createModelProvider(mock.env).next(
        input,
        controller.signal,
        async (trace) => {
          traces.push(trace);
          controller.abort();
        },
      ),
    ).rejects.toThrow();
    expect(mock.requests).toHaveLength(1);
    expect(traces).toMatchObject([
      { attempt: 1, status: "failed", errorCode: "invalid_json" },
    ]);
  });

  it.each([
    { tool: "execute_sql", reason: "Forbidden tool", finish: false },
    { tool: "ledger", reason: "Conflicting stop", finish: true },
    {
      tool: "ledger",
      reason: "Unsupported property",
      finish: false,
      sql: "SELECT 1",
    },
  ])(
    "rejects invalid planner decisions after provider JSON mode %#",
    async (output) => {
      const mock = await mockDeepSeek(() => ({ body: envelope(output) }));
      await expect(
        createModelProvider(mock.env).next(input, signal()),
      ).rejects.toThrow();
      expect(mock.requests).toHaveLength(1);
    },
  );

  it("does not treat reasoning_content as a missing final JSON answer", async () => {
    const mock = await mockDeepSeek(() => ({
      body: {
        choices: [
          {
            finish_reason: "stop",
            message: {
              content: "",
              reasoning_content: JSON.stringify({
                tool: "ledger",
                reason: "Hidden",
                finish: false,
              }),
            },
          },
        ],
      },
    }));
    await expect(
      createModelProvider(mock.env).next(input, signal()),
    ).rejects.toThrow("no content");
    expect(mock.requests).toHaveLength(2);
  });

  it("fails an authentication error without retrying, leaking the response body, or falling back", async () => {
    const privateBody = `sensitive response containing ${token}`;
    const mock = await mockDeepSeek(() => ({
      status: 401,
      body: { error: privateBody },
    }));
    const traces: ModelRequestTrace[] = [];
    const result = createModelProvider(mock.env).next(
      input,
      signal(),
      async (trace) => {
        traces.push(trace);
      },
    );
    await expect(result).rejects.toThrow("(401)");
    await expect(result).rejects.not.toThrow(token);
    expect(mock.requests).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      provider: "deepseek",
      status: "failed",
      errorCode: "http_401",
    });
    expect(JSON.stringify(traces)).not.toContain(token);
    expect(JSON.stringify(traces)).not.toContain(privateBody);
  });

  it("keeps memory suggestions in JSON mode and validates citations against supplied evidence", async () => {
    const answer = {
      hasSuggestion: true,
      content:
        "Inspect matching ledger evidence before accepting a fee adjustment.",
      conditions: "The bank settlement differs from the original amount.",
      suggestedTools: ["ledger"],
      evidenceIds: ["gl_entries:e1"],
      reason: "The supplied evidence establishes this procedure.",
    };
    const mock = await mockDeepSeek(() => ({ body: envelope(answer) }));
    const evidence: EvidenceReference = {
      id: "gl_entries:e1",
      table: "gl_entries",
      recordId: "J1",
      queryId: "q1",
      datasetVersion: "v1",
      record: {},
    };
    expect(
      await generateMemorySuggestion(
        { evidence: [evidence], verification: {}, gaps: [] },
        signal(),
        undefined,
        mock.env,
      ),
    ).toEqual(answer);
    expect(mock.requests[0].body.max_tokens).toBe(2000);
    await expect(
      generateMemorySuggestion(
        { evidence: [], verification: {}, gaps: [] },
        signal(),
        undefined,
        mock.env,
      ),
    ).rejects.toThrow("unknown evidence");
  });

  it("uses the same compatible provider for one-pass evaluation while rejecting invented evidence", async () => {
    const answer = {
      outcome: "no_anomaly_supported",
      category: "NO_FAILURE",
      evidenceIds: ["e1"],
      explanation: "Only the supplied evidence was assessed.",
    };
    const mock = await mockDeepSeek(() => ({ body: envelope(answer) }));
    expect(
      await onePassBaseline(
        { paymentId: input.paymentId, evidence: [{ id: "e1" }], manifest: {} },
        signal(),
        mock.env,
      ),
    ).toEqual(answer);
    await expect(
      onePassBaseline(
        { paymentId: input.paymentId, evidence: [], manifest: {} },
        signal(),
        mock.env,
      ),
    ).rejects.toThrow("unknown evidence");
  });

  it("cancels a pending HTTP request without retrying it", async () => {
    let requestArrived!: () => void;
    const arrived = new Promise<void>((resolve) => {
      requestArrived = resolve;
    });
    const mock = await mockDeepSeek(() => {
      requestArrived();
      return undefined;
    });
    const controller = new AbortController();
    const traces: ModelRequestTrace[] = [];
    const result = createModelProvider(mock.env).next(
      input,
      controller.signal,
      async (trace) => {
        traces.push(trace);
      },
    );
    await arrived;
    controller.abort();
    await expect(result).rejects.toThrow();
    expect(mock.requests).toHaveLength(1);
    expect(traces).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      provider: "deepseek",
      status: "cancelled",
      errorCode: "cancelled",
    });
  });
});
