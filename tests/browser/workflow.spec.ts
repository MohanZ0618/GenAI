import { test, expect } from "@playwright/test";
test("inbox, investigation, evidence, review, export and browser refresh", async ({
  page,
  request,
}, testInfo) => {
  const response = await request.get("/api/datasets");
  const datasets = (await response.json()).datasets;
  const packet = datasets.find(
    (d: { name: string }) => d.name === "Review packet 001",
  );
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
  await expect(page.locator(".run-status")).toHaveText(/Completed/, {
    timeout: 15000,
  });
  await expect(
    page.getByRole("heading", { name: "Anomaly supported by evidence" }),
  ).toBeVisible();
  await page.locator(".finding-main").first().click();
  await page.screenshot({ path: testInfo.outputPath("workspace-clean.png") });
  await page.getByRole("button", { name: "Provenance", exact: true }).click();
  await expect(page.locator(".provenance-details")).toContainText("Query ID");
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
