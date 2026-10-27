import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

async function completedDialog(page: Page) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveCount(1);
  const status = dialog.locator(".run-status");
  const skip = dialog.getByRole("button", {
    name: "Skip to results",
    exact: true,
  });
  await expect(status.or(skip)).toBeVisible({ timeout: 15000 });
  if (await skip.isVisible()) await skip.click();
  await expect(status).toHaveText(/Completed/, { timeout: 15000 });
  await expect(page).toHaveURL(/[?&]view=dialog(?:&|$)/);
}

async function caseInbox(page: Page) {
  const close = page.getByRole("button", {
    name: "Close investigation",
    exact: true,
  });
  if (new URL(page.url()).searchParams.get("view") === "dialog")
    await expect(close).toBeVisible({ timeout: 15000 });
  if (await close.isVisible()) {
    await close.click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
}

test("manual package exposes eight cases, cutoff checks and Chinese approved memory", async ({
  page,
}, testInfo) => {
  test.setTimeout(60000);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Import dataset", exact: true })
    .click();
  await page
    .getByLabel("Dataset files")
    .setInputFiles(resolve("data/openai-manual/01-main-bundle.json"));
  await page.getByRole("button", { name: "Validate & import" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
  await expect(page.locator(".case-table tbody tr")).toHaveCount(8);
  for (const code of [
    "NORMAL",
    "DUP",
    "STALE",
    "MISSING",
    "FEE",
    "FUTURE_EVENT",
    "FUTURE_FEE",
    "CONTEXT_TAIL",
  ]) {
    await page.getByLabel("Search cases").fill(`PAY_DEMO_${code}`);
    await page
      .getByRole("button", {
        name: `Investigate PAY_DEMO_${code}`,
        exact: true,
      })
      .click();
    await completedDialog(page);
    const titles: Record<string, string> = {
      NORMAL: "The evidence supports normal processing",
      CONTEXT_TAIL: "The evidence supports normal processing",
      DUP: "The invoice was paid more than once",
      STALE: "Superseded vendor instructions caused a return",
      MISSING: "Payment did not reach bank settlement",
      FEE: "Settlement fee has no supporting journal",
      FUTURE_FEE: "Settlement fee has no supporting journal",
      FUTURE_EVENT: "The available evidence does not establish a cause",
    };
    await expect(
      page
        .getByRole("dialog")
        .getByRole("region", { name: "Investigation conclusion" })
        .getByRole("heading", { level: 2 }),
    ).toHaveText(titles[code]);
    if (code.startsWith("FUTURE_")) {
      const validation = page
        .getByRole("dialog")
        .locator("details[aria-label='Validation']");
      await validation.locator("summary").click();
      await expect(validation.locator(".checks-content")).toContainText(
        "Future evidence excluded from the assessment",
      );
    }
    await page
      .getByRole("dialog")
      .locator("details[aria-label='Activity log'] > summary")
      .click();
    await expect(
      page.getByRole("region", { name: "Run diagnostics" }),
    ).toContainText("No model API calls in fixture mode.");
    if (code !== "CONTEXT_TAIL") await caseInbox(page);
  }
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(
    page.getByRole("dialog", { name: "Review the investigation", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Approve a reusable memory").check();
  await page
    .getByRole("textbox", { name: "Confirmed lesson", exact: true })
    .fill("请先检查供应商变更历史，再复核付款分录。");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  await caseInbox(page);
  const revisedBundle = JSON.parse(
    await readFile(
      resolve("data/openai-manual/04-revised-bundle.json"),
      "utf8",
    ),
  );
  const revisedResponse = await page.request.post("/api/datasets", {
    data: revisedBundle,
  });
  const revisedId = (await revisedResponse.json()).dataset.id;
  await page.getByRole("button", { name: "Refresh API connection" }).click();
  await page.getByLabel("Active dataset").selectOption(revisedId);
  await page.getByLabel("Search cases").fill("PAY_DEMO_CONTEXT_TAIL");
  await page
    .getByRole("button", {
      name: "Update investigation PAY_DEMO_CONTEXT_TAIL",
      exact: true,
    })
    .click();
  await completedDialog(page);
  await page
    .getByRole("dialog")
    .locator("details[aria-label='Activity log'] > summary")
    .click();
  await expect(
    page.getByRole("region", { name: "Run diagnostics" }),
  ).toContainText("请先检查供应商变更历史，再复核付款分录。");
  await page.screenshot({
    path: testInfo.outputPath("manual-activity-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("manual-activity-mobile.png"),
    fullPage: true,
  });
});

test("manual coverage, invalid import and revision retain distinct visible datasets", async ({
  request,
}) => {
  const load = async (file: string) =>
    JSON.parse(await readFile(resolve("data/openai-manual", file), "utf8"));
  const original = await request.post("/api/datasets", {
    data: await load("01-main-bundle.json"),
  });
  const originalId = (await original.json()).dataset.id;
  const revised = await request.post("/api/datasets", {
    data: await load("04-revised-bundle.json"),
  });
  expect((await revised.json()).dataset.id).not.toBe(originalId);
  const invalid = await request.post("/api/datasets", {
    data: await load("03-invalid-missing-payments.json"),
  });
  expect(invalid.status()).toBe(400);
  expect((await invalid.json()).error).toContain(
    "payments.csv: required file missing",
  );
  const partial = await request.post("/api/datasets", {
    data: await load("02-partial-coverage.json"),
  });
  const id = (await partial.json()).dataset.id;
  expect(
    (await (await request.get(`/api/cases?datasetId=${id}`)).json()).cases,
  ).toHaveLength(1);
  const start = await request.post("/api/investigations", {
    data: { datasetId: id, paymentId: "PAY_DEMO_NORMAL" },
  });
  const runId = (await start.json()).id;
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${runId}`)).json())
          .outcome,
    )
    .toBe("insufficient_evidence");
});
