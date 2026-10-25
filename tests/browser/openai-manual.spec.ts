import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

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
    await expect(page.locator(".run-status")).toHaveText(/Completed/, {
      timeout: 15000,
    });
    const title =
      code === "FUTURE_EVENT"
        ? "More evidence is needed"
        : ["NORMAL", "CONTEXT_TAIL"].includes(code)
          ? "No anomaly supported"
          : "Anomaly supported by evidence";
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    if (code.startsWith("FUTURE_")) {
      await page.getByRole("tab", { name: /Validation/ }).click();
      await expect(page.locator(".checks-content")).toContainText(
        "Future evidence excluded from the assessment",
      );
    }
    await page.getByRole("tab", { name: /Activity log/ }).click();
    await expect(
      page.getByRole("region", { name: "Run diagnostics" }),
    ).toContainText("No model API calls in fixture mode.");
    if (code !== "CONTEXT_TAIL")
      await page
        .getByRole("button", { name: "Case inbox", exact: true })
        .click();
  }
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await page.getByLabel("Approve a reusable memory").check();
  await page
    .getByRole("textbox", { name: "Confirmed lesson", exact: true })
    .fill("请先检查供应商变更历史，再复核付款分录。");
  await page.getByRole("button", { name: "Save human review" }).click();
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
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
  await expect(page.locator(".run-status")).toHaveText(/Completed/, {
    timeout: 15000,
  });
  await page.getByRole("tab", { name: /Activity log/ }).click();
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
