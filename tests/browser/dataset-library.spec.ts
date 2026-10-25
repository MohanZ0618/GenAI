import { test, expect, type Page } from "@playwright/test";
import type { Dataset } from "../../packages/contracts/src/index";

test.use({ reducedMotion: "reduce" });

const datasets: Dataset[] = [
  {
    name: "Coverage packet 001",
    id: "ds-0123456789abcdef",
    version: "a1".repeat(32),
  },
  {
    name: "Manual payment review",
    id: "ds-fedcba9876543210",
    version: "b2".repeat(32),
  },
  {
    name: "供应商变更记录",
    id: "ds-1234567890abcdef",
    version: "c3".repeat(32),
  },
].map((item) => ({
  ...item,
  asOf: "2026-06-30T12:00:00Z",
  createdAt: "2026-07-01T10:00:00Z",
  caseCount: 1,
  coverage: {},
  clearingDays: 3,
  currency: "USD",
  builtin: false,
}));

async function openLibrary(page: Page) {
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets } }),
  );
  await page.route("**/api/cases?*", (route) =>
    route.fulfill({ json: { cases: [] } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await expect(page.locator(".dataset-card")).toHaveCount(3);
}

test("dataset library searches names, IDs and versions, then selects the matching dataset", async ({
  page,
}) => {
  await openLibrary(page);
  const search = page.getByRole("textbox", {
    name: "Search datasets",
    exact: true,
  });
  const cards = page.locator(".dataset-card");
  await search.fill("  MANUAL PAYMENT  ");
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText(datasets[1].name);
  await expect(page.locator(".dataset-match-count")).toHaveText(
    "1 of 3 datasets",
  );
  await search.fill(datasets[0].id);
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText(datasets[0].name);
  await search.fill(datasets[2].version.slice(12, 38));
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText(datasets[2].name);
  await search.fill("供应商");
  await expect(cards).toHaveCount(1);
  await search.fill("not-a-dataset");
  await expect(
    page.getByRole("heading", { name: "No matching datasets" }),
  ).toBeVisible();
  await expect(page.locator(".dataset-match-count")).toHaveText(
    "0 of 3 datasets",
  );
  await page.getByRole("button", { name: "Show all datasets" }).click();
  await expect(cards).toHaveCount(3);
  await search.fill("Manual payment review");
  await cards
    .getByRole("button", { name: "Select dataset & open cases", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
  await expect(page.getByLabel("Active dataset")).toHaveValue(datasets[1].id);
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await expect(cards.locator(".dataset-selected")).toHaveText("Selected");
  await expect(
    cards.getByRole("button", { name: "Open active dataset", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear dataset search", exact: true })
    .click();
  await expect(cards).toHaveCount(3);
});

test("dataset ID and full version stay readable and copy correctly on desktop and mobile", async ({
  page,
  context,
}, testInfo) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openLibrary(page);
  const card = page.locator(".dataset-card").filter({
    has: page.getByRole("heading", { name: datasets[0].name, exact: true }),
  });
  const id = card.getByRole("button", { name: "Copy dataset ID", exact: true });
  const version = card.getByRole("button", {
    name: "Copy dataset version ID",
    exact: true,
  });
  await expect(id.locator("code")).toHaveText(datasets[0].id);
  await expect(version.locator("code")).toHaveText(datasets[0].version);
  await id.click();
  await expect(id).toContainText("Copied!");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    datasets[0].id,
  );
  await version.click();
  await expect(version).toContainText("Copied!");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    datasets[0].version,
  );
  await expect(page.getByLabel("Search datasets")).toBeVisible();
  await expect(page.locator(".dataset-card")).toHaveCount(3);
  for (const code of [id.locator("code"), version.locator("code")]) {
    expect(
      await code.evaluate((el) =>
        Number.parseFloat(getComputedStyle(el).fontSize),
      ),
    ).toBeGreaterThanOrEqual(16);
    expect(await code.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
      true,
    );
  }
  await page.screenshot({
    path: testInfo.outputPath("dataset-library-desktop.png"),
    fullPage: true,
  });
  await page.getByLabel("Search datasets").fill(datasets[0].id);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Search datasets")).toBeVisible();
  for (const code of [id.locator("code"), version.locator("code")]) {
    expect(
      await code.evaluate((el) =>
        Number.parseFloat(getComputedStyle(el).fontSize),
      ),
    ).toBeGreaterThanOrEqual(16);
    expect(await code.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
      true,
    );
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("dataset-library-mobile.png"),
    fullPage: true,
  });
});

test("clicking a searched dataset card opens its cases and the same action works by keyboard", async ({
  page,
}) => {
  await openLibrary(page);
  await page.getByLabel("Search datasets").fill(datasets[1].name);
  const card = page.getByRole("article", {
    name: `Dataset ${datasets[1].name}`,
    exact: true,
  });
  await card.click({ position: { x: 16, y: 16 } });
  await expect(page.getByLabel("Active dataset")).toHaveValue(datasets[1].id);
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await expect(card.locator(".dataset-selected")).toHaveText("Selected");
  await page
    .getByRole("button", { name: "Clear dataset search", exact: true })
    .click();
  const otherCard = page.getByRole("article", {
    name: `Dataset ${datasets[2].name}`,
    exact: true,
  });
  const open = otherCard.getByRole("button", {
    name: "Select dataset & open cases",
    exact: true,
  });
  await open.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Active dataset")).toHaveValue(datasets[2].id);
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await otherCard
    .getByRole("button", { name: "Open active dataset", exact: true })
    .focus();
  await page.keyboard.press("Space");
  await expect(page.getByLabel("Active dataset")).toHaveValue(datasets[2].id);
});
