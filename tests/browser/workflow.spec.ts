import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
test("inbox, investigation, evidence, review, export and browser refresh", async ({
  page,
  request,
}, testInfo) => {
  const bundle = JSON.parse(
    await readFile(resolve("data/manual-test/valid-bundle.json"), "utf8"),
  );
  bundle.manifest.name = `Workflow packet ${testInfo.testId}`;
  const imported = await request.post("/api/datasets", { data: bundle });
  expect(imported.ok()).toBe(true);
  const { dataset: packet } = await imported.json();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
  await expect(
    page.getByText("Deterministic rules · no live model or Zetaris"),
  ).toBeVisible();
  await page.getByLabel("Active dataset").selectOption(packet.id);
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Start investigation", exact: true })
    .click();
  const investigationDialog = page.getByRole("dialog", {
    name: "Payment investigation",
    exact: true,
  });
  await expect(investigationDialog).toBeVisible();
  await expect(page.locator("main")).toHaveAttribute("inert", "");
  await expect(page.locator(".run-status")).toHaveText(/Completed/, {
    timeout: 15000,
  });
  const runId = new URL(page.url()).searchParams.get("investigation");
  const savedRun = await (
    await request.get(`/api/investigations/${runId}`)
  ).json();
  const finding =
    savedRun.findings.find(
      (item: { category: string }) =>
        item.category !== "EVIDENCE_GAP" && item.category !== "NO_FAILURE",
    ) ?? savedRun.findings[0];
  await expect(
    page
      .getByRole("region", { name: "Investigation conclusion" })
      .getByRole("heading", { level: 2 }),
  ).toHaveText(finding.title);
  await page.locator(".finding-main").first().click();
  await page.screenshot({ path: testInfo.outputPath("workspace-clean.png") });
  const drawer = investigationDialog.getByRole("region", {
    name: "Original record",
    exact: true,
  });
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(
    drawer.getByRole("heading", { name: "Query provenance" }),
  ).toBeVisible();
  await expect(drawer).toContainText("Query ID");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await page
    .getByLabel("Review notes")
    .fill("Reviewed linked disbursements and invoice.");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  await page.reload();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "HTML report" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.html$/);
  await page.screenshot({
    path: testInfo.outputPath("investigation-desktop.png"),
    fullPage: true,
  });
});
test("mobile layout and invalid import show actionable state", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Make sense of every exception." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Import dataset", exact: true })
    .click();
  await page.getByLabel("Dataset files").setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({ manifest: { name: "invalid" }, files: {} }),
    ),
  });
  await page.getByRole("button", { name: "Validate & import" }).click();
  await expect(page.getByRole("alert")).toContainText("manifest");
  await page.screenshot({
    path: testInfo.outputPath("import-mobile.png"),
    fullPage: true,
  });
});
