import { test, expect, type Page } from "@playwright/test";
import type {
  Case,
  Dataset,
  Investigation,
} from "../../packages/contracts/src/index";

const snapshots: Dataset[] = ["a", "b"].map((suffix, index) => ({
  id: `layout-${suffix}`,
  name: `Layout packet ${suffix}`,
  version: `v${index + 1}`,
  asOf: "2026-06-30T12:00:00Z",
  caseCount: index ? 5 : 30,
  coverage: {},
  clearingDays: 3,
  currency: "USD",
  createdAt: `2026-06-${20 + index}T12:00:00Z`,
  builtin: false,
}));
const cases: Case[] = Array.from({ length: 35 }, (_, index) => ({
  id: `layout-case-${index + 1}`,
  paymentId: `PAY_LAYOUT_${String(index + 1).padStart(3, "0")}`,
  datasetId: snapshots[index < 30 ? 0 : 1].id,
  vendor: `Vendor ${String(index + 1).padStart(3, "0")}`,
  amount: String((index + 1) * 10),
  currency: index === 34 ? "EUR" : "USD",
  date: new Date(Date.UTC(2026, 0, index + 1)).toISOString(),
  symptom: index === 34 ? "Settlement missing" : "Payment discrepancy",
  status: index % 3 === 0 ? "reviewed" : "unreviewed",
  updateAvailable: index === 34,
}));

async function mockInbox(page: Page) {
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets: snapshots } }),
  );
  await page.route("**/api/cases?*", (route) => {
    const datasetId = new URL(route.request().url()).searchParams.get(
      "datasetId",
    );
    return route.fulfill({
      json: {
        cases: cases.filter(
          (item) => datasetId === "all" || item.datasetId === datasetId,
        ),
      },
    });
  });
  await page.goto("/");
  await expect(page.locator(".case-table tbody tr")).toHaveCount(25);
}

test("search, status, datasets and pagination keep the selected action on a visible case", async ({
  page,
}) => {
  await mockInbox(page);
  const rows = page.locator(".case-table tbody tr");
  const selected = page.locator(".selected-case-bar");
  await expect(
    page.locator(".stat-card").filter({ hasText: "Total cases" }),
  ).toContainText("35");
  await expect(
    page.locator(".stat-card").filter({ hasText: "Awaiting review" }),
  ).toContainText("23");
  await expect(
    page.locator(".stat-card").filter({ hasText: "Updates available" }),
  ).toContainText("1");
  await expect(
    page.getByRole("button", { name: "All cases", exact: true }),
  ).toContainText("35");
  await expect(rows.first().locator(".snapshot-label")).toHaveText(
    "v1 · layout-a",
  );
  await expect(page.locator(".quiet-footer")).toContainText(
    "view cutoff and coverage per snapshot",
  );
  await expect(page.locator(".page-range")).toHaveText("1–25 of 35 cases");
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(rows).toHaveCount(10);
  await expect(page.locator(".page-range")).toHaveText("26–35 of 35 cases");
  await expect(selected).toContainText("PAY_LAYOUT_026");
  await rows.last().click();
  await expect(selected).toContainText("PAY_LAYOUT_035");
  await expect(
    selected.getByRole("button", { name: "Update investigation", exact: true }),
  ).toBeVisible();

  await page.getByLabel("Search cases").fill("  vendor 002  ");
  await expect(rows).toHaveCount(1);
  await expect(selected).toContainText("PAY_LAYOUT_002");
  await expect(page.locator(".page-range")).toHaveText("1–1 of 1 cases");
  await page.getByLabel("Search cases").fill("no-such-case");
  await expect(
    page.getByRole("heading", { name: "No matching cases" }),
  ).toBeVisible();
  await expect(selected).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Start investigation", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Next page", exact: true }),
  ).toBeDisabled();

  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("button", { name: "Reviewed", exact: true }).click();
  await expect(rows).toHaveCount(12);
  await expect(selected).toContainText("PAY_LAYOUT_001");
  await page.getByLabel("Search cases").fill("Vendor 002");
  await expect(selected).toHaveCount(0);
  await page.getByRole("button", { name: "Unreviewed", exact: true }).click();
  await expect(rows).toHaveCount(1);
  await expect(selected).toContainText("PAY_LAYOUT_002");
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("button", { name: "All cases", exact: true }).click();
  await page.getByLabel("Rows per page").selectOption("10");
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  let finishLoading!: () => void;
  const loading = new Promise<void>((resolve) => {
    finishLoading = resolve;
  });
  await page.route("**/api/cases?datasetId=layout-b", async (route) => {
    await loading;
    await route.fulfill({ json: { cases: cases.slice(30) } });
  });
  await page.getByLabel("Active dataset").selectOption("layout-b");
  await expect(selected).toHaveCount(0);
  await expect(
    page.getByText("Loading payment cases…", { exact: true }),
  ).toBeVisible();
  finishLoading();
  await expect(rows).toHaveCount(5);
  await expect(page.locator(".page-range")).toHaveText("1–5 of 5 cases");
  await expect(selected).toContainText("PAY_LAYOUT_035");
  await expect(rows.filter({ hasText: "PAY_LAYOUT_035" })).toHaveClass(
    "selected",
  );
  await expect(page.locator(".snapshot-label")).toHaveCount(0);
  await expect(page.locator(".quiet-footer")).toContainText(
    "v2 · Cutoff Jun 30, 2026",
  );
});

test("import finishes refreshing before dismissing the modal and allowing inbox navigation", async ({
  page,
}) => {
  await mockInbox(page);
  let finishRefresh!: () => void;
  let refreshStarted!: () => void;
  const refreshing = new Promise<void>((resolve) => {
    finishRefresh = resolve;
  });
  const started = new Promise<void>((resolve) => {
    refreshStarted = resolve;
  });
  await page.route("**/api/datasets", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: { dataset: snapshots[1] } });
      return;
    }
    refreshStarted();
    await refreshing;
    await route.fulfill({ json: { datasets: snapshots } });
  });
  await page
    .getByRole("button", { name: "Import dataset", exact: true })
    .click();
  await page.getByLabel("Dataset files").setInputFiles({
    name: "layout.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ manifest: {}, files: {} })),
  });
  await page.getByRole("button", { name: "Validate & import" }).click();
  await started;
  await expect(page.getByRole("dialog")).toBeVisible();
  finishRefresh();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Your data. A clear provenance." }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
  await expect(page.locator(".case-table tbody tr")).toHaveCount(5);
  await expect(page.getByLabel("Active dataset")).toHaveValue("layout-b");
});

test("amount and date sorting apply before pagination and reset its position", async ({
  page,
}) => {
  await mockInbox(page);
  const rows = page.locator(".case-table tbody tr");
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await page
    .getByRole("button", { name: "Sort by amount", exact: true })
    .click();
  await expect(page.locator(".page-range")).toHaveText("1–25 of 35 cases");
  await expect(rows.nth(0)).toContainText("PAY_LAYOUT_035");
  await expect(rows.nth(1)).toContainText("PAY_LAYOUT_001");
  await expect(rows.nth(2)).toContainText("PAY_LAYOUT_002");
  await expect(
    page.getByRole("columnheader").filter({ hasText: "AMOUNT" }),
  ).toHaveAttribute("aria-sort", "ascending");
  await page
    .getByRole("button", { name: "Sort by amount", exact: true })
    .click();
  await expect(rows.nth(0)).toContainText("PAY_LAYOUT_035");
  await expect(rows.nth(1)).toContainText("PAY_LAYOUT_034");
  await page.getByRole("button", { name: "Sort by date", exact: true }).click();
  await expect(rows.first()).toContainText("PAY_LAYOUT_001");
  await page.getByRole("button", { name: "Sort by date", exact: true }).click();
  await expect(rows.first()).toContainText("PAY_LAYOUT_035");
  await expect(
    page.getByRole("columnheader").filter({ hasText: "DATE" }),
  ).toHaveAttribute("aria-sort", "descending");
});

test("updated case opens its snapshot and the shared footer stays available across tabs on mobile", async ({
  page,
}, testInfo) => {
  const item = cases[34];
  const run: Investigation = {
    id: "layout-run",
    datasetId: item.datasetId,
    paymentId: item.paymentId,
    status: "completed",
    mode: "fixture",
    provider: "deterministic-fixture",
    model: "none",
    createdAt: "2026-07-01T10:00:00Z",
    updatedAt: "2026-07-01T10:01:00Z",
    outcome: "insufficient_evidence",
    modelTurns: 0,
    memories: [],
    queries: [],
    evidence: [],
    findings: [
      {
        id: "finding",
        title: "Settlement needs review",
        category: "settlement",
        summary: "A bank record is missing.",
        evidenceIds: [],
        contradictions: [],
        uncertainty: ["Obtain the bank statement."],
      },
    ],
    checks: [
      {
        id: "check",
        label: "Statement coverage",
        status: "unknown",
        detail: "The statement period is incomplete.",
        evidenceIds: [],
      },
    ],
    actions: [
      {
        id: "action",
        title: "Request statement",
        description: "Obtain a complete statement before deciding.",
        prerequisites: ["Confirm the statement date range."],
        verified: false,
      },
    ],
    events: [
      {
        id: "event",
        at: "2026-07-01T10:01:00Z",
        type: "completed",
        message: "Investigation finished.",
      },
    ],
  };
  let started: unknown;
  await page.route("**/api/investigations", (route) => {
    started = route.request().postDataJSON();
    return route.fulfill({ json: run });
  });
  await page.route("**/api/investigations/layout-run/review", (route) => {
    const review = route.request().postDataJSON();
    run.review = {
      decision: review.decision,
      notes: review.notes,
      at: "2026-07-01T11:00:00Z",
    };
    return route.fulfill({ json: run });
  });
  await page.route("**/api/investigations/layout-run", (route) =>
    route.fulfill({ json: run }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await mockInbox(page);
  await expect(page.getByLabel("Search cases")).toBeVisible();
  await expect(page.locator(".case-table")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("Search cases").fill("Settlement missing");
  await expect(page.locator(".selected-case-bar")).toContainText(
    item.paymentId,
  );
  await page.screenshot({
    path: testInfo.outputPath("inbox-mobile.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Update investigation", exact: true })
    .click();
  expect(started).toEqual({ datasetId: "layout-b", paymentId: item.paymentId });
  await expect(page.getByRole("tab")).toHaveText([
    "Findings1",
    "Validation1",
    "Activity log1",
  ]);
  const followup = page.getByRole("region", {
    name: "Next steps and human review",
  });
  await expect(followup).toContainText("Request statement");
  await expect(followup).toContainText("Confirm the statement date range.");
  await expect(followup).toContainText("NOT EXECUTED");
  await expect(followup).toContainText("Obtain the bank statement.");
  await expect(followup).toContainText("The statement period is incomplete.");
  await expect(followup).toContainText("Awaiting human review");
  await page.getByRole("tab", { name: /Activity log/ }).click();
  await expect(
    followup.getByRole("button", { name: "Review findings", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: /Validation/ }).click();
  await followup
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await page.getByRole("button", { name: /Request changes/ }).click();
  await page.getByLabel("Review notes").fill("Need the full bank statement.");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Needs Changes");
  await expect(page.locator(".review-receipt")).toContainText(
    "Need the full bank statement.",
  );
  await expect(page.locator(".review-receipt")).toContainText(
    "Jul 1, 2026, 11:00 AM UTC",
  );
  await expect(page.locator(".workspace-bottom")).toContainText(
    "Layout packet b · v2",
  );
  await expect(page.locator(".workspace-bottom")).toContainText(
    "Investigation updated",
  );
  await expect(
    followup.getByRole("button", { name: "Export", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("followup-mobile.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: testInfo.outputPath("followup-desktop.png"),
    fullPage: true,
  });
});
