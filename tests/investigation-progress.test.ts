import { describe, expect, it } from "vitest";
import type { Investigation, RunEvent } from "../packages/contracts/src/index";
import {
  investigationProgressSummary,
  investigationSteps,
  localizeRecordedActivityText,
  progressIsOpen,
} from "../apps/web/src/investigationActivity";

const at = (second: number) =>
  `2026-06-01T12:00:${String(second).padStart(2, "0")}Z`;
function run(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: "run-progress",
    datasetId: "dataset",
    paymentId: "payment-1",
    status: "running",
    mode: "fixture",
    provider: "fixture",
    model: "none",
    createdAt: at(0),
    updatedAt: at(4),
    outcome: null,
    findings: [],
    checks: [],
    actions: [],
    evidence: [],
    events: [],
    queries: [],
    memories: [],
    modelTurns: 0,
    ...overrides,
  };
}
const event = (
  id: string,
  second: number,
  fields: Partial<RunEvent>,
): RunEvent => ({
  id,
  at: at(second),
  type: "planning",
  message: "",
  ...fields,
});

describe("recorded investigation progress", () => {
  it("preserves disclosure choices across polls and completion and resets for a different run", () => {
    const running = run();
    const done = { ...running, status: "completed" as const };
    expect(progressIsOpen(null, running)).toBe(true);
    expect(progressIsOpen(null, done)).toBe(false);
    const expanded = { key: running.id, open: true };
    const collapsed = { key: running.id, open: false };
    expect(progressIsOpen(expanded, { ...running })).toBe(true);
    expect(progressIsOpen(expanded, done)).toBe(true);
    expect(progressIsOpen(collapsed, { ...running })).toBe(false);
    expect(progressIsOpen(collapsed, done)).toBe(false);
    expect(progressIsOpen(collapsed, { ...running, id: "new-run" })).toBe(true);
    expect(progressIsOpen(expanded, { ...done, id: "new-run" })).toBe(false);
  });

  it("merges activity transitions once, preserves purpose, and links only recorded evidence", () => {
    const entry = run({
      events: [
        event("start", 1, {
          tool: "allocations",
          activity: {
            id: "tool-1",
            kind: "tool",
            status: "running",
            source: "rules",
            reason:
              "Retrieve the next source required by the independent verifier.",
          },
        }),
        event("end", 3, {
          type: "evidence",
          tool: "allocations",
          activity: {
            id: "tool-1",
            kind: "tool",
            status: "completed",
            queryId: "q-1",
            evidenceIds: ["e-1", "missing", "e-1"],
            relatedCount: 1,
          },
        }),
      ],
      queries: [
        {
          id: "q-1",
          tool: "allocations",
          status: "succeeded",
          at: at(3),
          durationMs: 35,
          rowCount: 8,
          tables: ["payment_allocations"],
          coverage: {},
        },
      ],
      evidence: [
        {
          id: "e-1",
          table: "payment_allocations",
          recordId: "allocation-1",
          queryId: "q-1",
          datasetVersion: "v1",
          record: { payment_id: "payment-1" },
        },
      ],
    });
    const steps = investigationSteps(entry);
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      id: "tool-1",
      status: "completed",
      startedAt: at(1),
      updatedAt: at(3),
      evidenceIds: ["e-1"],
      tables: ["payment_allocations"],
      durationMs: 35,
      summary: "Found 8 source records, 1 related to this payment.",
    });
    expect(steps[0].reason).toContain("duplicate-payment checks");
  });

  it("does not invent completion or tool failure when a terminal run lacks an activity result", () => {
    for (const status of ["completed", "failed", "cancelled"] as const) {
      const entry = run({
        status,
        events: [
          event("start", 1, {
            tool: "settlements",
            activity: { id: "open", kind: "tool", status: "running" },
          }),
        ],
      });
      expect(investigationSteps(entry)[0].status).toBe("unconfirmed");
      expect(
        investigationProgressSummary(entry, investigationSteps(entry)),
      ).not.toContain("1 tool check completed");
    }
  });

  it("reads legacy query identity without exposing raw context or guessing further tools", () => {
    const entry = run({
      status: "completed",
      events: [
        event("old-start", 1, {
          tool: "overview",
          message:
            "Establish the payment, vendor, and invoice context before forming a conclusion.",
        }),
        event("old-end", 2, {
          tool: "overview",
          type: "evidence",
          message: "Retrieved 2 source records. Query q-old.",
        }),
        event("context", 3, {
          type: "context",
          message: "DO NOT DISPLAY RAW CONTEXT",
        }),
      ],
      queries: [
        {
          id: "q-old",
          tool: "overview",
          tables: ["payments"],
          at: at(2),
          durationMs: 10,
          rowCount: 2,
          status: "succeeded",
          coverage: {},
        },
      ],
    });
    const steps = investigationSteps(entry);
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      title: "Understand this payment",
      status: "completed",
      queryId: "q-old",
      summary: "Found 2 source records.",
    });
    expect(JSON.stringify(steps)).not.toContain("DO NOT DISPLAY RAW CONTEXT");
  });

  it("preserves public purpose and treats failed queries as failures rather than empty results", () => {
    const entry = run({
      status: "failed",
      events: [
        event("plan", 1, {
          tool: "ledger",
          message: "核对已记录的手续费差额。",
        }),
      ],
      queries: [
        {
          id: "q-failed",
          tool: "ledger",
          tables: [],
          at: at(2),
          durationMs: 0,
          rowCount: 0,
          status: "failed",
          error: "connection lost",
          coverage: {},
        },
      ],
    });
    const steps = investigationSteps(entry);
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({
      reason: "核对已记录的手续费差额。",
      status: "failed",
    });
    expect(steps[0].summary).toContain(
      "does not establish whether records are present",
    );
  });

  it("can show trace-only history and leaves a completely empty run empty", () => {
    expect(investigationSteps(run())).toEqual([]);
    expect(investigationProgressSummary(run({ status: "queued" }), [])).toBe(
      "Waiting to start",
    );
    const entry = run({
      queries: [
        {
          id: "q-only",
          tool: "vendor_history",
          tables: ["vendor_change_log"],
          at: at(2),
          durationMs: 1,
          rowCount: 0,
          status: "succeeded",
          coverage: {},
        },
      ],
    });
    expect(investigationSteps(entry)).toMatchObject([
      {
        status: "completed",
        queryId: "q-only",
        summary: "Found 0 source records.",
      },
    ]);
  });

  it("renders generated Chinese history in English while retaining counts, citations and stored records", () => {
    const entry = run({
      status: "completed",
      evidence: [
        {
          id: "allocation:1",
          table: "payment_allocations",
          recordId: "allocation-1",
          queryId: "q-saved",
          datasetVersion: "v1",
          record: { payment_id: "payment-1" },
        },
      ],
      events: [
        event("saved-tool", 1, {
          tool: "allocations",
          activity: {
            id: "recorded-operation",
            kind: "tool",
            status: "completed",
            source: "model",
            reason: "核对付款与发票的分配关系，查找同一义务关联的付款。",
            summary:
              "读取 8 条来源记录，2 条与本次付款相关。关联到 1 张发票、2 笔付款的分配记录。",
            queryId: "q-saved",
            evidenceIds: ["allocation:1"],
            rowCount: 8,
            relatedCount: 2,
          },
        }),
        event("saved-check", 2, {
          activity: {
            id: "check",
            kind: "verification",
            status: "completed",
            summary:
              "已执行 4 项规则检查：3 项通过，0 项未通过，1 项待确认。接下来补查银行结算、总账分录。",
          },
        }),
        event("saved-memory", 3, {
          type: "memory",
          message: "Provided 0 approved memory snapshots to the planner.",
        }),
      ],
    });
    const original = structuredClone(entry);
    const steps = investigationSteps(entry);
    expect(steps[0]).toMatchObject({
      id: "recorded-operation",
      tool: "allocations",
      source: "model",
      title: "Check payment allocations",
      reason:
        "Check payment-to-invoice allocations and find payments linked to the same obligation.",
      summary:
        "Read 8 source records, 2 related to this payment. The returned allocations link 1 invoice and 2 payments.",
      queryId: "q-saved",
      rowCount: 8,
      relatedCount: 2,
      evidenceIds: ["allocation:1"],
    });
    expect(steps[1].summary).toBe(
      "Ran 4 rule checks: 3 passed, 0 failed, 1 unresolved. Next, retrieve: bank settlements, ledger entries.",
    );
    expect(steps[2].summary).toContain("Provided 0 approved memories");
    expect(
      steps
        .flatMap((step) => [step.title, step.reason, step.summary])
        .join(" "),
    ).not.toMatch(/\p{Script=Han}/u);
    expect(entry).toEqual(original);
  });

  it("localizes bank status and interruption history without changing the scope of the recorded claim", () => {
    expect(
      localizeRecordedActivityText(
        "读取 7 条来源记录，1 条与本次付款相关。返回记录中匹配到 1 条普通银行交易，其中 1 条标记为已入账、0 条标记为退回。",
      ),
    ).toBe(
      "Read 7 source records, 1 related to this payment. Matched 1 non-fee bank transaction in the returned records: 1 marked posted and 0 marked returned.",
    );
    expect(
      localizeRecordedActivityText(
        "证据查询未完成；请求失败不代表来源中没有记录。",
      ),
    ).toContain("does not establish that source records are missing");
    expect(
      localizeRecordedActivityText(
        "查询成功，这次没有返回来源记录；还需核对资料是否完整。",
      ),
    ).toContain("Source coverage still needs to be checked");
    expect(
      localizeRecordedActivityText(
        "找到 1 条可参考的已批准经验，接下来继续核对本次资料。",
      ),
    ).toBe(
      "Found 1 approved memory for reference. Continue checking the current evidence.",
    );
  });

  it("does not fabricate translations for arbitrary reviewer or model content", () => {
    for (const value of [
      "核对已记录的手续费差额。",
      "Original reviewer wording",
      "constructor",
      "toString",
    ])
      expect(localizeRecordedActivityText(value)).toBe(value);
  });
});
