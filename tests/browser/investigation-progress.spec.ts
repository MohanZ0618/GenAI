import { test, expect, type Locator, type Page } from "@playwright/test";
import type {
  Case,
  Dataset,
  EvidenceReference,
  Investigation,
  RunEvent,
} from "../../packages/contracts/src/index";

type Activity = NonNullable<RunEvent["activity"]>;

const dataset: Dataset = {
  id: "progress-dataset",
  name: "Investigation progress packet",
  version: "progress-snapshot-v1",
  asOf: "2026-06-30T23:59:59Z",
  caseCount: 1,
  coverage: {},
  clearingDays: 10,
  currency: "USD",
  createdAt: "2026-07-01T00:00:00Z",
  builtin: false,
};
const payment: Case = {
  id: "progress-case",
  datasetId: dataset.id,
  paymentId: "PAY_PROGRESS_DUP",
  vendor: "Synthetic progress supplier",
  amount: "1192.95",
  currency: "USD",
  date: "2026-06-20",
  symptom: "Review settled invoice allocations",
};
const reason = "核对同一发票的全部已结算分配，区分分期与重复付款。";
const toolSummary = "找到 5 条来源记录，其中 3 条与本次付款相关。";
const evidence: EvidenceReference = {
  id: "invoices:INV_PROGRESS_DUP",
  table: "invoices",
  recordId: "INV_PROGRESS_DUP",
  datasetVersion: dataset.version,
  queryId: "query-progress-allocations",
  record: {
    invoice_id: "INV_PROGRESS_DUP",
    vendor_id: "VENDOR_PROGRESS",
    invoice_total: "1192.95",
    currency: "USD",
    status: "paid",
  },
};

function event(
  id: string,
  type: string,
  activity: Activity,
  tool?: RunEvent["tool"],
): RunEvent {
  return {
    id,
    at: "2026-07-01T10:00:00Z",
    type,
    message: activity.summary ?? activity.reason ?? type,
    tool,
    activity,
  };
}

const planning: RunEvent = event("event-plan-completed", "planning_completed", {
  id: "plan-allocations",
  kind: "planning",
  status: "completed",
  source: "rules",
  summary: "先检查付款分配，再核对银行结算证据。",
});
const toolStarted: RunEvent = event(
  "event-tool-started",
  "tool_started",
  {
    id: "tool-allocations",
    kind: "tool",
    status: "running",
    source: "rules",
    reason,
    tables: ["invoices", "payments", "payment_allocations"],
  },
  "allocations",
);
const toolCompleted: RunEvent = event(
  "event-tool-completed",
  "tool_completed",
  {
    ...toolStarted.activity!,
    status: "completed",
    summary: toolSummary,
    rowCount: 5,
    relatedCount: 3,
    evidenceIds: [evidence.id],
    queryId: evidence.queryId,
    durationMs: 34,
  },
  "allocations",
);
const verificationStarted: RunEvent = event(
  "event-verification-started",
  "verification_started",
  {
    id: "verification-final",
    kind: "verification",
    status: "running",
    source: "rules",
    reason: "比较发票义务与已结算分配，并检查证据引用。",
  },
);

function snapshot(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: "investigation-progress-run",
    datasetId: dataset.id,
    paymentId: payment.paymentId,
    status: "running",
    mode: "fixture",
    provider: "deterministic-fixture",
    model: "none",
    createdAt: "2026-07-01T10:00:00Z",
    updatedAt: "2026-07-01T10:00:01Z",
    outcome: null,
    findings: [],
    checks: [],
    actions: [],
    evidence: [],
    events: [planning, toolStarted],
    queries: [],
    memories: [],
    modelTurns: 0,
    ...overrides,
  };
}

function retrievedSnapshot(): Investigation {
  return snapshot({
    events: [planning, toolStarted, toolCompleted, verificationStarted],
    evidence: [evidence],
    queries: [
      {
        id: evidence.queryId,
        tool: "allocations",
        tables: ["invoices", "payments", "payment_allocations"],
        at: "2026-07-01T10:00:02Z",
        durationMs: 34,
        rowCount: 5,
        status: "succeeded",
        coverage: {},
      },
    ],
  });
}

function completedSnapshot(): Investigation {
  return snapshot({
    ...retrievedSnapshot(),
    status: "completed",
    outcome: "anomaly_supported",
    updatedAt: "2026-07-01T10:00:03Z",
    events: [
      ...retrievedSnapshot().events,
      event("event-verification-completed", "verification_completed", {
        ...verificationStarted.activity!,
        status: "completed",
        summary: "已核验来源引用，已结算分配超过发票义务。",
        evidenceIds: [evidence.id],
      }),
    ],
    findings: [
      {
        id: "finding-progress-duplicate",
        category: "F06",
        title: "The invoice was paid more than once",
        summary: "Settled allocations exceed the invoice by 1192.95 USD.",
        evidenceIds: [evidence.id],
        contradictions: [],
        uncertainty: [],
      },
    ],
  });
}

// Serve snapshots through the same GET endpoint used by normal resume/polling.
// Unexpected writes fail locally; this suite never starts a real model request.
async function mockProgress(page: Page, initial = snapshot()) {
  let current = initial;
  let detailReads = 0;
  const unexpectedRequests: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET") {
      if (path === "/api/health")
        return route.fulfill({ json: { mode: "fixture", integrations: {} } });
      if (path === "/api/datasets")
        return route.fulfill({ json: { datasets: [dataset] } });
      if (path === "/api/cases")
        return route.fulfill({
          json: {
            cases: [
              {
                ...payment,
                status: current.status,
                investigationId: current.id,
                outcome: current.outcome,
              },
            ],
          },
        });
      if (path === `/api/investigations/${current.id}`) {
        detailReads++;
        return route.fulfill({ json: current });
      }
    }
    unexpectedRequests.push(`${request.method()} ${path}`);
    return route.fulfill({
      status: 405,
      json: { error: "Unexpected request in isolated progress test" },
    });
  });
  await page.goto(`/?investigation=${initial.id}`);
  const progress = page.getByRole("region", {
    name: "Investigation activity",
    exact: true,
  });
  await expect(progress).toBeVisible();
  return {
    progress,
    unexpectedRequests,
    get detailReads() {
      return detailReads;
    },
    publish(next: Investigation) {
      current = next;
    },
  };
}

async function expand(progress: Locator) {
  const toggle = progress.getByRole("button", {
    name: "Expand investigation activity",
  });
  if (await toggle.isVisible()) await toggle.click();
}

test("polling updates one activity per operation, exposes recorded purpose/results and opens related evidence", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const mock = await mockProgress(page);
  const step = mock.progress.locator('[data-activity-id="tool-allocations"]');
  await expect(step).toHaveAttribute("data-status", "running");
  await expect(step).toHaveClass(/is-current/);
  await expect(step.locator(".investigation-progress-reason")).toContainText(
    reason,
  );
  await expect(step.locator(".investigation-progress-summary")).toHaveCount(0);
  await expect(
    mock.progress.getByRole("button", { name: `View evidence ${evidence.id}` }),
  ).toHaveCount(0);
  await expect(page.locator(".detail-status-row")).toContainText(
    "Not determined",
  );
  await page.screenshot({
    path: info.outputPath("investigation-progress-running-desktop.png"),
    fullPage: true,
  });

  mock.publish(retrievedSnapshot());
  await expect(step).toHaveAttribute("data-status", "completed", {
    timeout: 10000,
  });
  await expect(step).toHaveCount(1);
  await expect(step).not.toHaveClass(/is-current/);
  await expect(step.locator(".investigation-progress-reason")).toContainText(
    reason,
  );
  await expect(step.locator(".investigation-progress-summary")).toContainText(
    toolSummary,
  );
  await expect(
    mock.progress.locator('[data-activity-id="verification-final"]'),
  ).toHaveAttribute("data-status", "running");
  const evidenceButton = step.getByRole("button", {
    name: `View evidence ${evidence.id}`,
    exact: true,
  });
  await expect(evidenceButton).toBeHidden();
  await step
    .locator("details.investigation-progress-evidence-disclosure > summary")
    .click();
  await evidenceButton.click();
  const drawer = page.getByRole("dialog", { name: "Original record" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByLabel("Evidence record")).toHaveValue(evidence.id);
  await expect(drawer).toContainText(evidence.queryId);
  await expect(drawer).toContainText(dataset.version);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(evidenceButton).toBeFocused();

  mock.publish(completedSnapshot());
  await expect(page.locator(".detail-status-row")).toContainText("Completed", {
    timeout: 10000,
  });
  await expect(
    page.getByRole("region", { name: "Investigation conclusion" }),
  ).toContainText("The invoice was paid more than once");
  await expand(mock.progress);
  await expect(step).toHaveCount(1);
  await expect(mock.progress.locator('[data-status="running"]')).toHaveCount(0);
  await expect(
    mock.progress.locator('[data-activity-id="verification-final"]'),
  ).toHaveAttribute("data-status", "completed");
  expect(mock.detailReads).toBeGreaterThanOrEqual(3);
  expect(mock.unexpectedRequests).toEqual([]);
});

for (const status of ["failed", "cancelled"] as const) {
  test(`${status} polling stops the active operation without a successful assessment`, async ({
    page,
  }) => {
    const mock = await mockProgress(page);
    const summary =
      status === "failed"
        ? "来源查询失败，未获得可验证记录。"
        : "查询已取消，未生成财务结论。";
    mock.publish(
      snapshot({
        status,
        error: status === "failed" ? "Evidence query unavailable" : undefined,
        events: [
          planning,
          toolStarted,
          event(
            `event-tool-${status}`,
            `tool_${status}`,
            { ...toolStarted.activity!, status, summary },
            "allocations",
          ),
        ],
      }),
    );
    await expect(page.locator(".detail-status-row")).toContainText(
      status === "failed" ? "Failed" : "Cancelled",
      { timeout: 10000 },
    );
    await expand(mock.progress);
    const step = mock.progress.locator('[data-activity-id="tool-allocations"]');
    await expect(step).toHaveCount(1);
    await expect(step).toHaveAttribute("data-status", status);
    await expect(step).not.toHaveClass(/is-current/);
    await expect(step.locator(".investigation-progress-summary")).toContainText(
      summary,
    );
    await expect(mock.progress.locator('[data-status="running"]')).toHaveCount(
      0,
    );
    await expect(page.locator(".detail-status-row")).toContainText(
      "Not determined",
    );
    await expect(page.locator(".detail-status-row")).not.toContainText(
      "No anomaly supported",
    );
    await expect(page.locator(".detail-status-row")).not.toContainText(
      "Issues found",
    );
    await expect(
      page.getByRole("region", { name: "Investigation conclusion" }),
    ).toContainText(
      status === "failed"
        ? "Investigation could not complete"
        : "Investigation cancelled",
    );
    expect(mock.unexpectedRequests).toEqual([]);
  });
}

test("an interrupted operation in a terminal run is marked unconfirmed rather than completed", async ({
  page,
}) => {
  const mock = await mockProgress(
    page,
    snapshot({ status: "cancelled", events: [planning, toolStarted] }),
  );
  await expand(mock.progress);
  const step = mock.progress.locator('[data-activity-id="tool-allocations"]');
  await expect(step).toHaveAttribute("data-status", "unconfirmed");
  await expect(step).toContainText("Completion not recorded");
  await expect(step).not.toHaveClass(/is-current/);
  await expect(step.locator(".investigation-progress-summary")).toHaveCount(0);
  await expect(mock.progress).not.toContainText(toolSummary);
  await expect(page.locator(".detail-status-row")).toContainText(
    "Not determined",
  );
  expect(mock.unexpectedRequests).toEqual([]);
});

test("saved legacy events retain their recorded evidence without invented planning details", async ({
  page,
}) => {
  const legacy = completedSnapshot();
  legacy.events = [
    {
      id: "legacy-query-event",
      at: "2026-07-01T10:00:02Z",
      type: "query",
      message: "Historical source lookup returned 5 rows.",
      tool: "allocations",
    },
  ];
  const mock = await mockProgress(page, legacy);
  await expand(mock.progress);
  await expect(mock.progress).toContainText("Found 5 source records.");
  await expect(mock.progress).not.toContainText(reason);
  await expect(mock.progress.locator('[data-status="running"]')).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Investigation conclusion" }),
  ).toContainText("The invoice was paid more than once");
  await page
    .getByRole("button", { name: `View evidence ${evidence.id}`, exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog", { name: "Original record" })
      .getByLabel("Evidence record"),
  ).toHaveValue(evidence.id);
  expect(mock.unexpectedRequests).toEqual([]);
});

test("progress fits its allocated mobile width and evidence respects reduced motion", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const mock = await mockProgress(page, retrievedSnapshot());
  const current = mock.progress.locator(".is-current");
  await expect(current).toHaveCount(1);
  await expect(current).toHaveAttribute("data-status", "running");
  // Record the existing desktop shell separately from this feature's bounds.
  // Hiding the progress section must not disguise unrelated page overflow.
  const baseline = await mock.progress.evaluate((progress) => {
    const bounds = (element: Element) => {
      const rect = element.getBoundingClientRect();
      return {
        tag: element.tagName.toLowerCase(),
        className: element.getAttribute("class"),
        parentClassName: element.parentElement?.getAttribute("class"),
        text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 100),
        x: Math.round(rect.x),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      };
    };
    const before = document.documentElement.scrollWidth;
    const previousDisplay = progress.style.display;
    progress.style.display = "none";
    const withoutProgress = document.documentElement.scrollWidth;
    const overflowing = [...document.querySelectorAll("body *")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.right > innerWidth + 1;
      })
      .map(bounds)
      .sort((a, b) => b.right - a.right)
      .slice(0, 12);
    const shell = [
      ".sidebar",
      ".main-content",
      ".topbar",
      ".detail-case-header",
      ".detail-status-row",
      ".detail-outcome",
    ].map((selector) => {
      const element = document.querySelector(selector)!;
      const style = getComputedStyle(element);
      return {
        selector,
        ...bounds(element),
        marginLeft: style.marginLeft,
        transform: style.transform,
      };
    });
    progress.style.display = previousDisplay;
    return {
      viewport: innerWidth,
      before,
      withoutProgress,
      overflowing,
      shell,
    };
  });
  await info.attach("mobile-shell-baseline", {
    body: JSON.stringify(baseline, null, 2),
    contentType: "application/json",
  });
  if (baseline.before > baseline.viewport)
    console.log("Existing mobile shell overflow:", JSON.stringify(baseline));
  const progressBounds = await mock.progress.boundingBox();
  expect(progressBounds).not.toBeNull();
  expect(progressBounds!.x).toBeGreaterThanOrEqual(0);
  expect(progressBounds!.x + progressBounds!.width).toBeLessThanOrEqual(390);
  const checkProgressWidth = async () => {
    await expect
      .poll(() =>
        mock.progress.evaluate((progress) => {
          const bounds = progress.getBoundingClientRect();
          return [...progress.querySelectorAll("*")]
            .filter((element) => {
              const rect = element.getBoundingClientRect();
              return (
                !element.classList.contains(
                  "investigation-progress-announcement",
                ) &&
                rect.width > 0 &&
                rect.height > 0 &&
                (rect.left < bounds.left - 1 || rect.right > bounds.right + 1)
              );
            })
            .map((element) => element.getAttribute("class"));
        }),
      )
      .toEqual([]);
  };
  await checkProgressWidth();
  await expect
    .poll(() =>
      current.evaluate((element) =>
        [element, ...element.querySelectorAll("*")].every(
          (item) => getComputedStyle(item).animationName === "none",
        ),
      ),
    )
    .toBe(true);
  const evidenceStep = mock.progress.locator(
    '[data-activity-id="tool-allocations"]',
  );
  await evidenceStep
    .locator("details.investigation-progress-evidence-disclosure > summary")
    .click();
  await evidenceStep
    .getByRole("button", { name: `View evidence ${evidence.id}`, exact: true })
    .click();
  const drawer = page.getByRole("dialog", { name: "Original record" });
  await expect(drawer).toBeVisible();
  const drawerBounds = await drawer.boundingBox();
  expect(drawerBounds).not.toBeNull();
  expect(drawerBounds!.x).toBeGreaterThanOrEqual(0);
  expect(drawerBounds!.x + drawerBounds!.width).toBeLessThanOrEqual(390);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  mock.publish(completedSnapshot());
  await expect(page.locator(".detail-status-row")).toContainText("Completed", {
    timeout: 10000,
  });
  await expand(mock.progress);
  await expect(mock.progress).toContainText(toolSummary);
  await expect(mock.progress.locator(".is-current")).toHaveCount(0);
  await checkProgressWidth();
  await mock.progress.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("investigation-progress-completed-mobile.png"),
    fullPage: false,
  });
  expect(mock.unexpectedRequests).toEqual([]);
});
