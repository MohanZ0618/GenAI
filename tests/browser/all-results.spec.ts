import { test, expect, type Page } from "@playwright/test";
import type {
  Case,
  Dataset,
  Investigation,
} from "../../packages/contracts/src/index";

const datasets: Dataset[] = ["a", "b"].map((suffix) => ({
  id: `results-${suffix}`,
  name: `Results packet ${suffix}`,
  version: `v-${suffix}`,
  asOf: "2026-06-30T00:00:00Z",
  caseCount: suffix === "a" ? 30 : 5,
  coverage: {},
  clearingDays: 3,
  currency: "USD",
  createdAt: "2026-07-01T00:00:00Z",
  builtin: false,
}));
const cases: Case[] = Array.from({ length: 35 }, (_, index) => ({
  id: `result-case-${index}`,
  paymentId: `PAY_RESULT_${String(index).padStart(3, "0")}`,
  datasetId: datasets[index < 30 ? 0 : 1].id,
  vendor: `Vendor ${index}`,
  amount: "100",
  currency: "USD",
  date: "2026-06-20T00:00:00Z",
  symptom: "Review requested",
  status:
    index % 5 < 3 ? "completed" : index % 5 === 3 ? "unreviewed" : "failed",
  investigationId: index % 5 === 3 ? undefined : `result-run-${index}`,
  outcome:
    index % 5 === 0
      ? "anomaly_supported"
      : index % 5 === 1
        ? "no_anomaly_supported"
        : index % 5 === 2
          ? "insufficient_evidence"
          : null,
}));

async function mockResults(page: Page) {
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets } }),
  );
  await page.route("**/api/cases?*", (route) => {
    const scope = new URL(route.request().url()).searchParams.get("datasetId");
    return route.fulfill({
      json: {
        cases: cases.filter(
          (item) => scope === "all" || scope === item.datasetId,
        ),
      },
    });
  });
  await page.goto("/");
  await expect(page.locator(".case-table tbody tr")).toHaveCount(25);
}

test("all results cover every page and ignore inbox filters without starting investigations", async ({
  page,
}, testInfo) => {
  let starts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/investigations"
    )
      starts++;
  });
  await mockResults(page);
  await page.getByLabel("Search cases").fill("PAY_RESULT_001");
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  const filters = page.getByRole("group", { name: "Filter results" });
  await expect(
    filters.getByRole("button", { name: /All results/ }),
  ).toContainText("35");
  for (const title of [
    "Issues found",
    "No anomaly supported",
    "More evidence needed",
  ])
    await expect(
      filters.getByRole("button", { name: new RegExp(title) }),
    ).toContainText("7");
  await expect(
    filters.getByRole("button", { name: /Not ready/ }),
  ).toContainText("14");
  await expect(page.locator(".results-table tbody tr")).toHaveCount(25);
  await page.getByRole("button", { name: "Next results page" }).click();
  await expect(page.locator(".results-table tbody tr")).toHaveCount(10);
  await expect(page.locator(".results-table")).toContainText("PAY_RESULT_034");
  await filters.getByRole("button", { name: /Issues found/ }).click();
  await expect(page.locator(".results-table tbody tr")).toHaveCount(7);
  await expect(page.locator(".result-badge")).toHaveText(
    Array(7).fill("Issues found"),
  );
  await filters.getByRole("button", { name: /Not ready/ }).click();
  await expect(page.locator(".results-table tbody tr")).toHaveCount(14);
  await expect(page.locator(".results-table")).toContainText(
    "Not investigated",
  );
  await expect(page.locator(".results-table")).toContainText("Failed");
  await page.getByLabel("Search results").fill("PAY_RESULT_003");
  await expect(page.locator(".results-table tbody tr")).toHaveCount(1);
  expect(starts).toBe(0);
  await page.getByLabel("Search results").fill("");
  await filters.getByRole("button", { name: /All results/ }).click();
  await page.screenshot({
    path: testInfo.outputPath("all-results-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("all-results-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
});

test("dataset scope is preserved and saved results reopen without a new run", async ({
  page,
}) => {
  await mockResults(page);
  await page.getByLabel("Active dataset").selectOption("results-b");
  await expect(page.locator(".case-table tbody tr")).toHaveCount(5);
  let starts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST") starts++;
  });
  const run: Investigation = {
    id: "result-run-31",
    datasetId: "results-b",
    paymentId: "PAY_RESULT_031",
    status: "completed",
    mode: "fixture",
    provider: "deterministic-fixture",
    model: "none",
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    outcome: "no_anomaly_supported",
    findings: [],
    checks: [],
    actions: [],
    evidence: [],
    events: [],
    queries: [],
    memories: [],
    modelTurns: 0,
  };
  await page.route("**/api/investigations/result-run-31", (route) =>
    route.fulfill({ json: run }),
  );
  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  await expect(
    page
      .getByRole("group", { name: "Filter results" })
      .getByRole("button", { name: /All results/ }),
  ).toContainText("5");
  await expect(page.locator(".results-table tbody tr")).toHaveCount(5);
  await page
    .getByRole("button", {
      name: "View result PAY_RESULT_031 in results-b",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "No anomaly supported", exact: true }),
  ).toBeVisible();
  expect(starts).toBe(0);
});

test("a failed summary request shows an error and can be retried", async ({
  page,
}) => {
  await mockResults(page);
  let fail = true;
  await page.route("**/api/cases?*", (route) =>
    fail
      ? route.fulfill({
          status: 503,
          json: { error: "Results temporarily unavailable" },
        })
      : route.fulfill({ json: { cases } }),
  );
  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Results temporarily unavailable",
  );
  fail = false;
  await page.getByRole("button", { name: "Retry results" }).click();
  await expect(page.locator(".results-table tbody tr")).toHaveCount(25);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("unfinished results remain unresolved and refresh when the run completes", async ({
  page,
}) => {
  await mockResults(page);
  const rows: Case[] = [
    { ...cases[1], status: "running", outcome: "no_anomaly_supported" },
    { ...cases[3], updateAvailable: true },
    { ...cases[4], outcome: "no_anomaly_supported" },
    { ...cases[2], outcome: null },
  ];
  let complete = false;
  await page.route("**/api/cases?*", (route) =>
    route.fulfill({
      json: {
        cases: rows.map((item, index) =>
          index === 0 && complete ? { ...item, status: "completed" } : item,
        ),
      },
    }),
  );
  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  const filters = page.getByRole("group", { name: "Filter results" });
  await expect(
    filters.getByRole("button", { name: /No anomaly supported/ }),
  ).toHaveText("0No anomaly supported");
  await expect(filters.getByRole("button", { name: /Not ready/ })).toHaveText(
    "4Not ready",
  );
  await expect(page.locator(".result-badge")).toHaveText([
    "Running",
    "Update required",
    "Failed",
    "Result unavailable",
  ]);
  complete = true;
  await expect(
    filters.getByRole("button", { name: /No anomaly supported/ }),
  ).toHaveText("1No anomaly supported", { timeout: 10000 });
  await expect(filters.getByRole("button", { name: /Not ready/ })).toHaveText(
    "3Not ready",
  );
});
