import { test, expect, type Page, type TestInfo } from "@playwright/test";
import type { Case, Dataset } from "../../packages/contracts/src/index";

test.use({ viewport: { width: 1440, height: 900 } });

const datasets: Dataset[] = [
  {
    id: "desktop-reconciliation-001",
    name: "Desktop reconciliation packet",
    version: "a1".repeat(32),
    caseCount: 3,
  },
  {
    id: "desktop-vendor-review-002",
    name: "Vendor instructions packet",
    version: "b2".repeat(32),
    caseCount: 1,
  },
].map((dataset) => ({
  ...dataset,
  asOf: "2026-10-22T23:59:59Z",
  createdAt: "2026-10-23T12:00:00Z",
  coverage: {},
  clearingDays: 3,
  currency: "USD",
  builtin: false,
}));

const cases: Case[] = Array.from({ length: 4 }, (_, index) => ({
  id: `desktop-case-${index + 1}`,
  paymentId: `PAY_DESKTOP_${String(index + 1).padStart(3, "0")}`,
  datasetId: datasets[index < 3 ? 0 : 1].id,
  vendor: [
    "Northstar Office Supplies",
    "Cobalt Works",
    "Lumen Services",
    "Atlas Parts",
  ][index],
  amount: ["24800.00", "1884.15", "7200.00", "960.00"][index],
  currency: "USD",
  date: "2026-10-21T12:00:00Z",
  symptom: "Payment exception awaiting source investigation",
  status: "unreviewed",
}));

async function openDesktopWorkspace(page: Page) {
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets } }),
  );
  await page.route("**/api/cases?*", (route) => {
    const scope = new URL(route.request().url()).searchParams.get("datasetId");
    return route.fulfill({
      json: {
        cases: cases.filter(
          (item) => scope === "all" || item.datasetId === scope,
        ),
      },
    });
  });
  await page.route("**/api/memories", (route) =>
    route.fulfill({ json: { memories: [] } }),
  );
  await page.goto("/");
  await expect(page.locator(".case-table tbody tr")).toHaveCount(cases.length);
}

async function captureDesktopPage(page: Page, info: TestInfo, name: string) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    `${name} must not overflow the desktop viewport`,
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath(`desktop-${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}

test("desktop pages retain navigation and primary operations across inbox, results, datasets, memories and guide", async ({
  page,
}, info) => {
  await openDesktopWorkspace(page);
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Import dataset", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start investigation", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search cases")).toBeVisible();
  await expect(page.getByLabel("Active dataset")).toBeVisible();
  await captureDesktopPage(page, info, "inbox");

  await page
    .getByRole("button", { name: "View All Results", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "All case results", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Refresh results", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search results")).toBeVisible();
  await expect(
    page.getByRole("group", { name: "Filter results" }),
  ).toBeVisible();
  await expect(page.locator(".results-table tbody tr")).toHaveCount(
    cases.length,
  );
  await captureDesktopPage(page, info, "results");

  await navigation
    .getByRole("button", { name: "Datasets", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your data. A clear provenance." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Import dataset", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Get template", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search datasets")).toBeVisible();
  await expect(page.locator(".dataset-card")).toHaveCount(datasets.length);
  await captureDesktopPage(page, info, "datasets");

  await navigation
    .getByRole("button", { name: "Investigation memories", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Investigation memories", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("No approved memories yet.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Memory status")).toBeVisible();
  await page.getByLabel("Memory status").selectOption("active");
  await expect(
    page.getByText("No approved memories yet.", { exact: true }),
  ).toBeVisible();
  await captureDesktopPage(page, info, "memories-empty");

  await page
    .getByRole("button", { name: "How FinTrace works", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Confidence comes from evidence." }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Start with the records", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Keep the decision human", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Explore the case inbox", exact: true }),
  ).toBeVisible();
  await captureDesktopPage(page, info, "guide");
  await page
    .getByRole("button", { name: "Explore the case inbox", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
});

test("desktop dataset search keeps matching identifiers and copy operations available", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openDesktopWorkspace(page);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Datasets", exact: true })
    .click();
  const search = page.getByLabel("Search datasets");
  await search.fill(datasets[1].name);
  const cards = page.locator(".dataset-card");
  await expect(cards).toHaveCount(1);
  await expect(
    cards.getByRole("heading", { name: datasets[1].name }),
  ).toBeVisible();
  const datasetCopy = cards.getByRole("button", {
    name: "Copy dataset ID",
    exact: true,
  });
  const versionCopy = cards.getByRole("button", {
    name: "Copy dataset version ID",
    exact: true,
  });
  await datasetCopy.click();
  await expect(datasetCopy).toContainText("Copied!");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    datasets[1].id,
  );
  await versionCopy.click();
  await expect(versionCopy).toContainText("Copied!");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    datasets[1].version,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await search.fill("missing-desktop-dataset");
  await expect(
    page.getByRole("heading", { name: "No matching datasets", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Show all datasets", exact: true })
    .click();
  await expect(cards).toHaveCount(datasets.length);
});
