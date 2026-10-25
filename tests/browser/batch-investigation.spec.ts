import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type {
  Case,
  Dataset,
  Investigation,
} from "../../packages/contracts/src/index";

async function mockInbox(page: Page, count = 35) {
  const datasets: Dataset[] = ["a", "b"].map((suffix) => ({
    id: `batch-${suffix}`,
    name: `Batch packet ${suffix}`,
    version: `v-${suffix}`,
    asOf: "2026-06-30T00:00:00Z",
    caseCount: suffix === "a" ? Math.min(30, count) : Math.max(0, count - 30),
    coverage: {},
    clearingDays: 3,
    currency: "USD",
    createdAt: "2026-07-01T00:00:00Z",
    builtin: false,
  }));
  const cases: Case[] = Array.from({ length: count }, (_, index) => ({
    id: `batch-case-${index}`,
    paymentId: `PAY_BATCH_${String(index).padStart(3, "0")}`,
    datasetId: datasets[index < 30 ? 0 : 1].id,
    vendor: `Batch vendor ${index}`,
    amount: "100",
    currency: "USD",
    date: "2026-06-20T00:00:00Z",
    symptom: "Review requested",
    status: "unreviewed",
    outcome: null,
  }));
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
  await expect(page.locator(".case-table tbody tr")).toHaveCount(
    Math.min(25, count),
  );
  return cases;
}

test("selection spans pages and search, view results stays scoped, and changing datasets clears selection", async ({
  page,
}) => {
  await mockInbox(page);
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST") posts++;
  });
  await page
    .getByRole("checkbox", {
      name: "Select PAY_BATCH_000 in batch-a",
      exact: true,
    })
    .check();
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await page
    .getByRole("checkbox", {
      name: "Select PAY_BATCH_030 in batch-b",
      exact: true,
    })
    .check();
  await page.getByLabel("Search cases").fill("PAY_BATCH_004");
  await expect(
    page.getByRole("group", { name: "Batch investigation" }),
  ).toContainText("2 selected");
  await page
    .getByRole("button", { name: "View selected results (2)", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Selected case results", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".results-table tbody tr")).toHaveCount(2);
  await expect(page.locator(".results-table")).toContainText("PAY_BATCH_000");
  await expect(page.locator(".results-table")).toContainText("PAY_BATCH_030");
  expect(posts).toBe(0);
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
  await page
    .getByRole("button", { name: "Clear selection", exact: true })
    .click();
  await page.getByLabel("Search cases").fill("");
  await page
    .getByRole("checkbox", {
      name: "Select all cases on this page",
      exact: true,
    })
    .check();
  await expect(
    page.getByRole("group", { name: "Batch investigation" }),
  ).toContainText("25 selected");
  await page
    .getByRole("button", { name: "Select all 35 cases", exact: true })
    .click();
  await expect(
    page.getByRole("group", { name: "Batch investigation" }),
  ).toContainText("35 selected");
  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "All case results", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("group", { name: "Filter results" })
      .getByRole("button", { name: /All results/ }),
  ).toContainText("35");
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
  await page.getByLabel("Active dataset").selectOption("batch-b");
  await expect(
    page.getByRole("group", { name: "Batch investigation" }),
  ).toContainText("0 selected");
  expect(posts).toBe(0);
});

const makeRun = (
  item: Case,
  status: Investigation["status"] = "completed",
): Investigation => ({
  id: `run-${item.id}`,
  datasetId: item.datasetId,
  paymentId: item.paymentId,
  status,
  mode: "fixture",
  provider: "deterministic-fixture",
  model: "none",
  createdAt: "2026-06-01T00:00:00Z",
  updatedAt: "2026-06-01T00:00:00Z",
  outcome: status === "completed" ? "no_anomaly_supported" : null,
  findings: [],
  checks: [],
  actions: [],
  evidence: [],
  events: [],
  queries: [],
  memories: [],
  modelTurns: 0,
});

test("legacy server: three completed cases are read, five pending cases run serially and results appear incrementally", async ({
  page,
}, testInfo) => {
  const cases = await mockInbox(page, 8);
  for (const entry of cases.slice(0, 3)) {
    entry.status = "completed";
    entry.investigationId = `run-${entry.id}`;
  }
  let allowance = 0;
  const posts: string[] = [];
  let batchCalls = 0;
  const runs = new Map<string, Investigation>();
  for (const entry of cases.slice(0, 3))
    runs.set(`run-${entry.id}`, makeRun(entry));
  await page.route("**/api/investigations/batch", (route) => {
    batchCalls++;
    return route.fulfill({ status: 404, json: { error: "Route not found" } });
  });
  await page.route("**/api/investigations", (route) => {
    expect(
      [...runs.values()].filter((run) =>
        ["queued", "running"].includes(run.status),
      ),
    ).toHaveLength(0);
    const entry = cases.find(
      (entry) => entry.paymentId === route.request().postDataJSON().paymentId,
    )!;
    posts.push(entry.paymentId);
    const run = makeRun(entry, "running");
    runs.set(run.id, run);
    entry.status = "running";
    entry.investigationId = run.id;
    return route.fulfill({ status: 202, json: run });
  });
  await page.route("**/api/investigations/run-*", (route) => {
    const run = runs.get(
      new URL(route.request().url()).pathname.split("/").at(-1)!,
    )!;
    const index = cases.findIndex((entry) => entry.paymentId === run.paymentId);
    if (index < 3 || index - 3 < allowance) {
      run.status = "completed";
      run.outcome = "no_anomaly_supported";
      cases[index].status = "completed";
      // Deliberately omit outcome from /cases, as the running legacy service does.
    }
    return route.fulfill({ json: run });
  });
  await page.getByRole("button", { name: "Refresh API connection" }).click();
  await expect(page.locator(".case-table tbody tr")).toHaveCount(8);
  await page
    .getByRole("button", { name: "Select all 8 cases", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Investigate selected (8)", exact: true })
    .click();
  await expect(page.locator(".batch-progress")).toContainText(
    "3 of 8 finished · 5 remaining",
  );
  await expect(page.locator(".batch-progress")).toContainText(
    "1 running · 4 waiting",
  );
  expect(posts).toHaveLength(1);
  await expect(
    page
      .locator(".results-table .result-badge")
      .filter({ hasText: "No anomaly supported" }),
  ).toHaveCount(3);
  allowance = 1;
  await expect(page.locator(".batch-progress")).toContainText(
    "4 of 8 finished · 4 remaining",
    { timeout: 10000 },
  );
  await expect(
    page
      .locator(".results-table .result-badge")
      .filter({ hasText: "No anomaly supported" }),
  ).toHaveCount(4);
  expect(posts).toHaveLength(2);
  await page.screenshot({
    path: testInfo.outputPath("serial-progress.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", {
      name: "View result PAY_BATCH_000 in batch-a",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "No anomaly supported", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
  await page
    .getByRole("button", { name: "View investigation progress", exact: true })
    .click();
  allowance = Infinity;
  await expect(page.locator(".batch-progress")).toContainText(
    "8 of 8 finished · 0 remaining",
    { timeout: 15000 },
  );
  expect(posts).toEqual(cases.slice(3).map((entry) => entry.paymentId));
  expect(batchCalls).toBe(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".results-table .result-badge")).toHaveText(
    Array(8).fill("No anomaly supported"),
  );
  expect(
    await page
      .locator(".results-page")
      .evaluate((element) =>
        [...element.childNodes].some(
          (node) =>
            node.nodeType === Node.TEXT_NODE &&
            node.textContent?.trim() === "0",
        ),
      ),
  ).toBe(false);
});

test("a failed start does not block the next selected case", async ({
  page,
}) => {
  const cases = await mockInbox(page);
  const posts: string[] = [];
  await page.route("**/api/investigations", (route) => {
    const item = cases.find(
      (entry) => entry.paymentId === route.request().postDataJSON().paymentId,
    )!;
    posts.push(item.paymentId);
    if (item.id === cases[0].id)
      return route.fulfill({
        status: 503,
        json: { error: "Test start failure" },
      });
    const run = makeRun(item);
    item.status = "completed";
    item.outcome = run.outcome;
    item.investigationId = run.id;
    return route.fulfill({ status: 202, json: run });
  });
  for (const item of cases.slice(0, 2))
    await page
      .getByRole("checkbox", {
        name: `Select ${item.paymentId} in ${item.datasetId}`,
        exact: true,
      })
      .check();
  await page
    .getByRole("button", { name: "Investigate selected (2)", exact: true })
    .click();
  await expect(page.locator(".batch-progress")).toContainText(
    "2 of 2 finished · 0 remaining",
  );
  await expect(page.getByRole("alert")).toContainText("1 case needs attention");
  await expect(page.locator(".results-table")).toContainText(
    "Test start failure",
  );
  await expect(page.locator(".result-badge")).toHaveText([
    "Investigation failed",
    "No anomaly supported",
  ]);
  expect(posts).toHaveLength(2);
});

test("view all hydrates completed results from a legacy list without any POST", async ({
  page,
}) => {
  const cases = await mockInbox(page);
  for (const item of cases) {
    item.status = "completed";
    item.investigationId = `run-${item.id}`;
  }
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST") posts++;
  });
  await page.route("**/api/investigations/run-*", (route) => {
    const item = cases.find((entry) =>
      route.request().url().endsWith(`run-${entry.id}`),
    )!;
    return route.fulfill({ json: makeRun(item) });
  });
  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  await expect(
    page
      .getByRole("group", { name: "Filter results" })
      .getByRole("button", { name: /No anomaly supported/ }),
  ).toContainText("35");
  expect(posts).toBe(0);
});

test("real single-case APIs reuse completed investigations and run the remaining selected fixture cases", async ({
  page,
  request,
}) => {
  const bundle = JSON.parse(
    await readFile(resolve("data/openai-manual/01-main-bundle.json"), "utf8"),
  );
  bundle.manifest.name = "Serial browser integration";
  const dataset = (
    await (await request.post("/api/datasets", { data: bundle })).json()
  ).dataset;
  const saved = new Map<string, string>();
  for (const paymentId of ["PAY_DEMO_NORMAL", "PAY_DEMO_DUP", "PAY_DEMO_FEE"]) {
    const run = await (
      await request.post("/api/investigations", {
        data: { datasetId: dataset.id, paymentId },
      })
    ).json();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/investigations/${run.id}`)).json())
            .status,
      )
      .toBe("completed");
    saved.set(paymentId, run.id);
  }
  await page.route("**/api/cases?*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    for (const item of body.cases) delete item.outcome;
    await route.fulfill({ json: body });
  });
  const started: string[] = [];
  let batchCalls = 0;
  page.on("request", (req) => {
    if (
      req.method() === "POST" &&
      new URL(req.url()).pathname === "/api/investigations"
    )
      started.push(req.postDataJSON().paymentId);
    if (new URL(req.url()).pathname === "/api/investigations/batch")
      batchCalls++;
  });
  await page.goto("/");
  await page.getByLabel("Active dataset").selectOption(dataset.id);
  await page
    .getByRole("button", { name: "Select all 8 cases", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Investigate selected (8)", exact: true })
    .click();
  await expect(page.locator(".batch-progress")).toContainText(
    "8 of 8 finished · 0 remaining",
    { timeout: 20000 },
  );
  expect(started).toHaveLength(5);
  expect(started.some((paymentId) => saved.has(paymentId))).toBe(false);
  expect(batchCalls).toBe(0);
  await expect(page.locator(".results-table tbody tr")).toHaveCount(8);
  await expect(page.getByRole("alert")).toHaveCount(0);
  const list = (
    await (await request.get(`/api/cases?datasetId=${dataset.id}`)).json()
  ).cases;
  for (const item of list) {
    if (saved.has(item.paymentId))
      expect(item.investigationId).toBe(saved.get(item.paymentId));
    const run = await (
      await request.get(`/api/investigations/${item.investigationId}`)
    ).json();
    expect(run.status).toBe("completed");
    expect(run.queries.length).toBeGreaterThan(0);
  }
});
