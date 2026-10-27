import { test, expect, type Page } from "@playwright/test";
import type {
  Case,
  Dataset,
  Investigation,
  InvestigationSummary,
} from "../../packages/contracts/src/index";

test.use({ viewport: { width: 1440, height: 900 } });

const dataset: Dataset = {
  id: "history-snapshot",
  name: "Payment review snapshot",
  version: "a1".repeat(32),
  asOf: "2026-10-22T23:59:59Z",
  createdAt: "2026-10-23T12:00:00Z",
  coverage: {},
  clearingDays: 3,
  currency: "USD",
  builtin: false,
  caseCount: 52,
};

function makeRun(index: number, status: Investigation["status"] = "completed") {
  const createdAt = new Date(Date.UTC(2026, 9, 26, 12, index)).toISOString();
  const run: Investigation = {
    id: `history-run-${String(index).padStart(3, "0")}`,
    datasetId: dataset.id,
    paymentId: index >= 50 || index < 2 ? "PAY_REPEAT" : `PAY_HISTORY_${index}`,
    status,
    mode: "fixture",
    provider: "deterministic-fixture",
    model: "none",
    createdAt,
    updatedAt: createdAt,
    outcome: status === "completed" ? "anomaly_supported" : null,
    findings:
      status === "completed"
        ? [
            {
              id: `finding-${index}`,
              title: `Saved assessment for run ${index}`,
              category: "DUPLICATE_PAYMENT",
              summary: `The saved evidence for investigation ${index} supports this finding.`,
              evidenceIds: [],
              contradictions: [],
              uncertainty: [],
            },
          ]
        : [],
    checks: [],
    actions: [],
    evidence: [],
    events: [],
    queries: [],
    memories: [],
    modelTurns: 0,
  };
  return run;
}

async function mockWorkspace(page: Page, initialRuns: Investigation[]) {
  const state = {
    runs: new Map(initialRuns.map((run) => [run.id, run])),
    listFailures: 0,
    listRequests: 0,
    startRequests: 0,
    detailReads: [] as string[],
    reviewRequests: [] as { id: string; body: Record<string, unknown> }[],
  };
  const cases = new Map<string, Case>();
  for (const run of initialRuns) {
    cases.set(run.paymentId, {
      id: `case-${run.paymentId}`,
      datasetId: dataset.id,
      paymentId: run.paymentId,
      vendor: `Vendor ${run.paymentId}`,
      amount: "1200.00",
      currency: "USD",
      date: "2026-10-21T12:00:00Z",
      symptom: `Check settlement records for ${run.paymentId}`,
      status: run.status,
      investigationId: run.id,
      outcome: run.outcome,
    });
  }
  function summary(run: Investigation): InvestigationSummary {
    return {
      id: run.id,
      datasetId: run.datasetId,
      paymentId: run.paymentId,
      status: run.status,
      createdAt: run.createdAt,
      updatedAt: run.updatedAt,
      outcome: run.outcome,
      vendor: `Vendor ${run.paymentId}`,
      question: `Check settlement records for ${run.paymentId}`,
      datasetName: dataset.name,
      datasetVersion: dataset.version,
      datasetRemoved: false,
      ...(run.review ? { review: run.review } : {}),
    };
  }
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();
    if (pathname === "/api/health")
      return route.fulfill({ json: { mode: "fixture" } });
    if (pathname === "/api/datasets")
      return route.fulfill({ json: { datasets: [dataset] } });
    if (pathname === `/api/datasets/${dataset.id}`)
      return route.fulfill({ json: { dataset } });
    if (pathname === "/api/cases")
      return route.fulfill({ json: { cases: [...cases.values()] } });
    if (pathname === "/api/memories")
      return route.fulfill({ json: { memories: [] } });
    if (pathname === "/api/investigations") {
      if (method === "POST") {
        state.startRequests++;
        return route.fulfill({
          status: 409,
          json: { error: "Viewing history must not start a run." },
        });
      }
      state.listRequests++;
      if (state.listFailures > 0) {
        state.listFailures--;
        return route.fulfill({
          status: 503,
          json: { error: "History is temporarily unavailable." },
        });
      }
      return route.fulfill({
        json: {
          investigations: [...state.runs.values()]
            .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
            .map(summary),
        },
      });
    }
    const reviewMatch = pathname.match(
      /^\/api\/investigations\/([^/]+)\/review$/,
    );
    if (reviewMatch && method === "POST") {
      const id = decodeURIComponent(reviewMatch[1]);
      const current = state.runs.get(id)!;
      const body = request.postDataJSON();
      state.reviewRequests.push({ id, body });
      const updated: Investigation = {
        ...current,
        updatedAt: "2026-10-27T12:00:00Z",
        review: {
          decision: body.decision,
          notes: body.notes,
          at: "2026-10-27T12:00:00Z",
        },
      };
      state.runs.set(id, updated);
      return route.fulfill({ json: updated });
    }
    const runMatch = pathname.match(/^\/api\/investigations\/([^/]+)$/);
    if (runMatch && method === "GET") {
      const id = decodeURIComponent(runMatch[1]);
      state.detailReads.push(id);
      const run = state.runs.get(id);
      return route.fulfill(
        run
          ? { json: run }
          : { status: 404, json: { error: "Investigation not found" } },
      );
    }
    return route.fulfill({
      status: 404,
      json: { error: `Unexpected test request: ${method} ${pathname}` },
    });
  });
  return state;
}

function row(page: Page, id: string) {
  return page.locator(`[data-investigation-id="${id}"]`);
}

async function openHistory(page: Page) {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Investigation", exact: true })
    .click();
  await expect(
    page.getByRole("table", { name: "Investigation history" }),
  ).toBeVisible();
}

test("history keeps repeated investigations distinct and restores the page and scroll after viewing a failed run", async ({
  page,
}, info) => {
  const runs = Array.from({ length: 52 }, (_, index) =>
    makeRun(
      index,
      index === 51
        ? "running"
        : index === 50
          ? "cancelled"
          : index === 3
            ? "failed"
            : "completed",
    ),
  );
  const state = await mockWorkspace(page, runs);
  await openHistory(page);
  const table = page.getByRole("table", { name: "Investigation history" });
  await expect(table.locator("tbody tr")).toHaveCount(25);
  await expect(table.locator("tbody tr").first()).toHaveAttribute(
    "data-investigation-id",
    runs[51].id,
  );
  await expect(row(page, runs[51].id)).toContainText("PAY_REPEAT");
  await expect(row(page, runs[50].id)).toContainText("PAY_REPEAT");
  await expect(
    row(page, runs[51].id).getByRole("button", { name: /^Review / }),
  ).toBeDisabled();
  await expect(
    row(page, runs[50].id).getByRole("button", { name: /^Review / }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("investigation-history-desktop.png"),
    fullPage: false,
  });

  await page
    .getByRole("button", { name: "Next investigations page", exact: true })
    .click();
  await expect(page.getByText("Page 2 of 3", { exact: true })).toBeVisible();
  const failed = runs[3];
  const view = row(page, failed.id).getByRole("button", {
    name: /^View investigation /,
  });
  await view.scrollIntoViewIfNeeded();
  const previousScroll = await page.evaluate(() => window.scrollY);
  expect(previousScroll).toBeGreaterThan(0);
  await view.click();
  await expect(page.locator(".detail-provenance")).toContainText(failed.id);
  await expect(
    page.getByRole("heading", {
      name: "Investigation could not complete",
      exact: true,
    }),
  ).toBeVisible();
  expect(state.detailReads).toContain(failed.id);
  expect(state.startRequests).toBe(0);
  await page
    .locator(".detail-breadcrumb")
    .getByRole("button", { name: "Investigation", exact: true })
    .click();
  await expect(table).toBeVisible();
  await expect(page.getByText("Page 2 of 3", { exact: true })).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(25);
  await expect
    .poll(async () =>
      Math.abs((await page.evaluate(() => window.scrollY)) - previousScroll),
    )
    .toBeLessThan(5);
  expect(state.startRequests).toBe(0);
});

test("review targets the selected historical run and remains editable after returning and reloading", async ({
  page,
}) => {
  const older = makeRun(0);
  const newer = makeRun(1);
  const state = await mockWorkspace(page, [older, newer]);
  await page.goto("/?view=investigations");
  await row(page, older.id)
    .getByRole("button", { name: /^Review / })
    .click();
  const modal = page.getByRole("dialog", { name: "Review the investigation" });
  await expect(modal).toBeVisible();
  await modal
    .getByRole("textbox", { name: "Review notes", exact: true })
    .fill("Checked the original snapshot and linked evidence.");
  await modal
    .getByRole("button", { name: "Save human review", exact: true })
    .click();
  await expect(modal).toHaveCount(0);
  expect(state.reviewRequests).toHaveLength(1);
  expect(state.reviewRequests[0]).toMatchObject({
    id: older.id,
    body: {
      decision: "accepted",
      notes: "Checked the original snapshot and linked evidence.",
      approveMemory: false,
    },
  });
  expect(state.runs.get(newer.id)?.review).toBeUndefined();
  await page
    .locator(".detail-breadcrumb")
    .getByRole("button", { name: "Investigation", exact: true })
    .click();
  await expect(row(page, older.id)).toContainText("Accepted");
  await expect(
    row(page, older.id).getByRole("button", { name: /^Edit review / }),
  ).toBeVisible();
  await expect(
    row(page, newer.id).getByRole("button", { name: /^Review / }),
  ).toBeVisible();
  await page.reload();
  await row(page, older.id)
    .getByRole("button", { name: /^Edit review / })
    .click();
  await expect(
    modal.getByRole("textbox", { name: "Review notes", exact: true }),
  ).toHaveValue("Checked the original snapshot and linked evidence.");
  await modal.getByRole("button", { name: /^Request changes/ }).click();
  await modal
    .getByRole("textbox", { name: "Review notes", exact: true })
    .fill("Please verify the remaining bank settlement evidence.");
  await modal
    .getByRole("button", { name: "Save human review", exact: true })
    .click();
  await expect(modal).toHaveCount(0);
  await page
    .locator(".detail-breadcrumb")
    .getByRole("button", { name: "Investigation", exact: true })
    .click();
  await expect(row(page, older.id)).toContainText("Changes requested");
  expect(state.runs.get(older.id)?.review?.notes).toBe(
    "Please verify the remaining bank settlement evidence.",
  );
  await row(page, older.id)
    .getByRole("button", { name: /^Edit review / })
    .click();
  await expect(
    modal.getByRole("button", { name: /^Request changes/ }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    modal.getByRole("textbox", { name: "Review notes", exact: true }),
  ).toHaveValue("Please verify the remaining bank settlement evidence.");
  expect(state.startRequests).toBe(0);
});

test("an active investigation updates in place and enables review when complete", async ({
  page,
}) => {
  const active = makeRun(2, "running");
  const state = await mockWorkspace(page, [active]);
  await page.goto("/?view=investigations");
  await expect(row(page, active.id)).toContainText("Running");
  await expect(
    row(page, active.id).getByRole("button", { name: /^Review / }),
  ).toBeDisabled();
  state.runs.set(active.id, makeRun(2));
  await expect(row(page, active.id)).toContainText("Completed", {
    timeout: 10000,
  });
  await expect(row(page, active.id)).toContainText("Issues found");
  await expect(
    row(page, active.id).getByRole("button", { name: /^Review / }),
  ).toBeEnabled();
  expect(state.listRequests).toBeGreaterThanOrEqual(2);
});

test("history loading failures offer retry and an empty history offers the case inbox", async ({
  page,
}) => {
  const state = await mockWorkspace(page, []);
  state.listFailures = 1;
  await page.goto("/?view=investigations");
  await expect(page.getByRole("alert")).toContainText(
    "History is temporarily unavailable.",
  );
  await page
    .getByRole("button", { name: "Retry investigations", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "No investigations yet", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: /Choose a case/ }).click();
  await expect(
    page.getByRole("heading", {
      name: "Make sense of every exception.",
      exact: true,
    }),
  ).toBeVisible();
});

test("a delayed initial investigation link cannot replace the history selected by the user", async ({
  page,
}) => {
  const older = makeRun(0);
  await mockWorkspace(page, [older]);
  let releaseResponse!: () => void;
  let markRequested!: () => void;
  const held = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  const requested = new Promise<void>((resolve) => {
    markRequested = resolve;
  });
  await page.route(`**/api/investigations/${older.id}`, async (route) => {
    markRequested();
    await held;
    await route.fulfill({ json: older });
  });
  await page.goto(`/?investigation=${older.id}`);
  await requested;
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Investigation", exact: true })
    .click();
  await expect(
    page.getByRole("table", { name: "Investigation history" }),
  ).toBeVisible();
  const released = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/investigations/${older.id}`,
  );
  releaseResponse();
  await released;
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
  await expect(
    page.getByRole("heading", { name: "Investigations", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".investigation-detail")).toHaveCount(0);
  await expect(page).toHaveURL(/view=investigations/);
  await expect(page).not.toHaveURL(/[?&]investigation=/);
});

test("a historical run retains its saved vendor, amount and date when its snapshot is removed", async ({
  page,
}) => {
  const saved = makeRun(4);
  saved.evidence = [
    {
      id: "saved-payment-evidence",
      table: "payments",
      recordId: saved.paymentId,
      queryId: "saved-payment-query",
      datasetVersion: dataset.version,
      record: {
        payment_id: saved.paymentId,
        vendor_id: "VENDOR_SAVED",
        payment_date: "2026-10-20T12:00:00Z",
        payment_amount: "3456.78",
        payment_currency: "USD",
      },
    },
    {
      id: "saved-vendor-evidence",
      table: "vendors",
      recordId: "VENDOR_SAVED",
      queryId: "saved-payment-query",
      datasetVersion: dataset.version,
      record: {
        vendor_id: "VENDOR_SAVED",
        vendor_name: "Vendor preserved in saved evidence",
      },
    },
  ];
  const state = await mockWorkspace(page, [saved]);
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.route("**/api/cases?*", (route) =>
    route.fulfill({ json: { cases: [] } }),
  );
  await page.route(`**/api/datasets/${dataset.id}`, (route) =>
    route.fulfill({
      json: { dataset: { ...dataset, removedAt: "2026-10-27T10:00:00Z" } },
    }),
  );
  await page.route("**/api/investigations", (route) =>
    route.fulfill({
      json: {
        investigations: [
          {
            id: saved.id,
            datasetId: saved.datasetId,
            paymentId: saved.paymentId,
            status: saved.status,
            createdAt: saved.createdAt,
            updatedAt: saved.updatedAt,
            outcome: saved.outcome,
            vendor: "Vendor preserved in saved evidence",
            question: "Check settlement records from the original snapshot",
            datasetName: dataset.name,
            datasetVersion: dataset.version,
            datasetRemoved: true,
          } satisfies InvestigationSummary,
        ],
      },
    }),
  );
  await page.goto("/?view=investigations");
  await expect(row(page, saved.id)).toContainText("Removed snapshot");
  await row(page, saved.id)
    .getByRole("button", { name: /^View investigation / })
    .click();
  await expect(page.locator(".detail-case-meta")).toContainText(
    "Vendor preserved in saved evidence",
  );
  await expect(page.locator(".detail-case-meta")).toContainText("Oct 20, 2026");
  await expect(page.locator(".detail-case-amount")).toContainText("$3,456.78");
  await expect(page.locator(".detail-provenance")).toContainText(saved.id);
  expect(state.startRequests).toBe(0);
});
