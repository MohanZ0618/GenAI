import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  Investigation,
  InvestigationActivity,
  RunEvent,
} from "../packages/contracts/src/index";
import {
  createInvestigationPlaybackCache,
  InvestigationPlaybackController,
  mainInvestigationSteps,
} from "../apps/web/src/useInvestigationPlayback";
import { investigationSteps } from "../apps/web/src/investigationActivity";

const visible = { animate: true, visible: true };
const controllers: InvestigationPlaybackController[] = [];
const controller = (cache = createInvestigationPlaybackCache()) => {
  vi.useFakeTimers();
  const current = new InvestigationPlaybackController(cache);
  controllers.push(current);
  return current;
};
afterEach(() => {
  controllers.splice(0).forEach((current) => current.pause());
  vi.useRealTimers();
});
const activityEvent = (
  id: string,
  fields: Partial<InvestigationActivity> = {},
): RunEvent => ({
  id,
  at: "2026-07-01T12:00:00Z",
  type: "evidence",
  tool: "overview",
  message: "diagnostic information",
  activity: {
    id,
    kind: "tool",
    status: "completed",
    reason: "核对付款",
    summary: "查到一条记录",
    ...fields,
  },
});
function run(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: "run-playback",
    datasetId: "dataset",
    paymentId: "payment",
    status: "completed",
    mode: "fixture",
    provider: "fixture",
    model: "none",
    createdAt: "2026-07-01T12:00:00Z",
    updatedAt: "2026-07-01T12:00:01Z",
    outcome: "insufficient_evidence",
    findings: [],
    checks: [],
    actions: [],
    evidence: [],
    events: [activityEvent("tool-1")],
    queries: [],
    memories: [],
    modelTurns: 0,
    ...overrides,
  };
}

describe("investigation presentation playback", () => {
  it("types two characters every 20ms, then collapses for 200ms before releasing completed results", () => {
    const playback = controller();
    playback.configure(run(), visible);
    expect(playback.getSnapshot()).toMatchObject({
      ready: false,
      replaying: true,
      phase: "process",
      currentStepId: "tool-1",
    });
    expect(playback.getSnapshot().steps[0].reason).toBe("");
    vi.advanceTimersByTime(19);
    expect(playback.getSnapshot().steps[0].reason).toBe("");
    vi.advanceTimersByTime(1);
    expect(playback.getSnapshot().steps[0].reason).toBe("核对");
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0]).toMatchObject({
      reason: "核对付款",
      summary: "",
    });
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0].summary).toBe("查到");
    vi.advanceTimersByTime(40);
    expect(playback.getSnapshot()).toMatchObject({
      ready: false,
      phase: "collapsing",
      currentStepId: undefined,
    });
    vi.advanceTimersByTime(199);
    expect(playback.getSnapshot().ready).toBe(false);
    vi.advanceTimersByTime(1);
    expect(playback.getSnapshot()).toMatchObject({
      ready: true,
      replaying: false,
      phase: "results",
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("caps a long step at 1.2 seconds and does not expose the next recorded step early", () => {
    const playback = controller();
    playback.configure(
      run({
        events: [
          activityEvent("long", {
            reason: "字".repeat(1000),
            summary: "长".repeat(1000),
          }),
          activityEvent("next", { reason: "下一步", summary: "完成" }),
        ],
      }),
      visible,
    );
    vi.advanceTimersByTime(1180);
    expect(playback.getSnapshot().steps).toHaveLength(1);
    expect(playback.getSnapshot().steps[0].reason).toHaveLength(118);
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0].reason).toHaveLength(1000);
    expect(playback.getSnapshot().steps[0].summary).toHaveLength(1000);
    expect(playback.getSnapshot().steps[1]).toMatchObject({
      id: "next",
      reason: "",
      summary: "",
    });
    vi.runAllTimers();
    expect(playback.getSnapshot().ready).toBe(true);
  });

  it("pauses while hidden and resumes the exact presentation cursor without catching up hidden time", () => {
    const playback = controller();
    const entry = run({
      events: [activityEvent("tool", { reason: "字".repeat(20) })],
    });
    playback.configure(entry, visible);
    vi.advanceTimersByTime(40);
    playback.configure(entry, { ...visible, visible: false });
    expect(playback.getSnapshot().steps[0].reason).toHaveLength(4);
    vi.advanceTimersByTime(5000);
    expect(playback.getSnapshot().steps[0].reason).toHaveLength(4);
    expect(vi.getTimerCount()).toBe(0);
    playback.configure(entry, visible);
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0].reason).toHaveLength(6);
    expect(playback.getSnapshot().ready).toBe(false);
  });

  it("isolates two run cursors and retains them when a dialog controller remounts", () => {
    const cache = createInvestigationPlaybackCache();
    const playback = controller(cache);
    const first = run({
      events: [activityEvent("a", { reason: "甲".repeat(20) })],
    });
    const second = run({
      id: "second",
      events: [activityEvent("b", { reason: "乙".repeat(20) })],
    });
    playback.configure(first, visible);
    vi.advanceTimersByTime(40);
    playback.configure(second, visible);
    expect(playback.getSnapshot().steps[0].reason).toBe("");
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0].reason).toBe("乙乙");
    playback.configure(first, visible);
    expect(playback.getSnapshot().steps[0].reason).toBe("甲甲甲甲");
    playback.pause();
    const reopened = controller(cache);
    reopened.configure(first, visible);
    expect(reopened.getSnapshot().steps[0].reason).toBe("甲甲甲甲");
    vi.advanceTimersByTime(20);
    expect(reopened.getSnapshot().steps[0].reason).toBe("甲".repeat(6));
  });

  it("never retypes a visible reason when a real completion adds its result summary", () => {
    const playback = controller();
    const active = run({
      status: "running",
      outcome: null,
      events: [
        activityEvent("tool", {
          status: "running",
          reason: "核对付款",
          summary: undefined,
        }),
      ],
    });
    playback.configure(active, visible);
    vi.advanceTimersByTime(1000);
    expect(playback.getSnapshot().steps[0].reason).toBe("核对付款");
    expect(vi.getTimerCount()).toBe(0);
    const completed = run({ events: [activityEvent("tool")] });
    playback.configure(completed, visible);
    expect(playback.getSnapshot().steps[0]).toMatchObject({
      reason: "核对付款",
      summary: "",
    });
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0]).toMatchObject({
      reason: "核对付款",
      summary: "查到",
    });
    playback.configure(structuredClone(completed), visible);
    expect(playback.getSnapshot().steps[0].summary).toBe("查到");
  });

  it("replaces an amended public description without deleting and retyping visible text", () => {
    const playback = controller();
    playback.configure(
      run({
        status: "running",
        events: [
          activityEvent("tool", { status: "running", summary: undefined }),
        ],
      }),
      visible,
    );
    vi.advanceTimersByTime(20);
    expect(playback.getSnapshot().steps[0].reason).toBe("核对");
    playback.configure(
      run({
        status: "running",
        events: [
          activityEvent("tool", {
            status: "running",
            reason: "更正后的查询目的",
            summary: undefined,
          }),
        ],
      }),
      visible,
    );
    expect(playback.getSnapshot().steps[0].reason).toBe("更正后的查询目的");
  });

  it("opens saved results and reduced-motion runs with complete recorded text immediately", () => {
    const playback = controller();
    playback.configure(run(), { animate: false, visible: true });
    expect(playback.getSnapshot()).toMatchObject({
      ready: true,
      phase: "results",
      replaying: false,
    });
    expect(playback.getSnapshot().steps[0].summary).toBe("查到一条记录");
    const reduced = controller();
    reduced.configure(run(), { ...visible, reducedMotion: true });
    expect(reduced.getSnapshot().ready).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["failed", "cancelled"] as const)(
    "shows %s immediately, retains its real records, and never collapses",
    (status) => {
      const playback = controller();
      const entry = run({
        status,
        outcome: null,
        error: "真实服务端错误",
        events: [activityEvent("tool", { status, summary: "真实结束记录" })],
      });
      playback.configure(entry, visible);
      expect(playback.getSnapshot()).toMatchObject({
        ready: true,
        replaying: false,
        phase: "interrupted",
      });
      expect(playback.getSnapshot().steps[0].summary).toBe("真实结束记录");
      vi.advanceTimersByTime(5000);
      expect(playback.getSnapshot().phase).toBe("interrupted");
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("skips presentation without declaring a backend running investigation complete", () => {
    const playback = controller();
    const entry = run({
      status: "running",
      outcome: null,
      events: [activityEvent("tool", { status: "running" })],
    });
    playback.configure(entry, visible);
    playback.skip();
    expect(playback.getSnapshot()).toMatchObject({
      ready: false,
      replaying: false,
      phase: "process",
    });
    expect(playback.getSnapshot().steps[0].reason).toBe("核对付款");
    playback.configure(
      run({ events: [activityEvent("tool"), activityEvent("new-record")] }),
      visible,
    );
    expect(playback.getSnapshot()).toMatchObject({
      ready: true,
      phase: "results",
    });
    expect(playback.getSnapshot().steps).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never invents steps for absent or empty historical records and includes only recorded primary activity", () => {
    const playback = controller();
    playback.configure(undefined, visible);
    expect(playback.getSnapshot()).toMatchObject({ ready: false, steps: [] });
    playback.configure(run({ events: [] }), visible);
    expect(playback.getSnapshot()).toMatchObject({
      ready: true,
      steps: [],
      fullSteps: [],
    });
    const entry = run({
      status: "running",
      events: [
        activityEvent("old-plan", { kind: "planning" }),
        activityEvent("old-check", { kind: "verification" }),
        activityEvent("tool"),
        activityEvent("memory", { kind: "memory" }),
        activityEvent("current-plan", { kind: "planning", status: "running" }),
        activityEvent("last-check", { kind: "verification" }),
      ],
    });
    expect(
      mainInvestigationSteps(investigationSteps(entry)).map((step) => step.id),
    ).toEqual(["tool", "memory", "current-plan", "last-check"]);
    playback.configure(entry, visible);
    expect(playback.getSnapshot().fullSteps).toHaveLength(6);
    expect(playback.getSnapshot().steps).toHaveLength(1);
  });
});
