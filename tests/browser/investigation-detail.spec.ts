import { test, expect, type APIRequestContext } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

async function duplicateInvestigation(request: APIRequestContext) {
  const bundle = JSON.parse(
    await readFile(resolve("data/openai-manual/01-main-bundle.json"), "utf8"),
  );
  bundle.manifest.name = `Investigation detail ${test.info().testId}`;
  const imported = await request.post("/api/datasets", { data: bundle });
  expect(imported.ok()).toBe(true);
  const { dataset } = await imported.json();
  const started = await request.post("/api/investigations", {
    data: { datasetId: dataset.id, paymentId: "PAY_DEMO_DUP" },
  });
  expect(started.ok()).toBe(true);
  const { id } = await started.json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${id}`)).json()).status,
    )
    .toBe("completed");
  return (await request.get(`/api/investigations/${id}`)).json();
}

test("specific conclusion, evidence drawer, collapsed details and deliberate inline review", async ({
  page,
  request,
}, info) => {
  const run = await duplicateInvestigation(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/?investigation=${run.id}`);

  const conclusion = page.getByRole("region", {
    name: "Investigation conclusion",
  });
  const headline = conclusion.getByRole("heading", { level: 2 });
  await expect(headline).toHaveText("The invoice was paid more than once");
  await expect(conclusion).toContainText(run.findings[0].summary);
  await expect(page.locator(".detail-status-row")).toContainText("Completed");
  await expect(page.locator(".detail-status-row")).toContainText(
    "Issues found",
  );
  await expect(page.locator(".detail-status-row")).toContainText(
    "Awaiting review",
  );
  const headlineBounds = await headline.boundingBox();
  expect(headlineBounds).not.toBeNull();
  expect(headlineBounds!.y).toBeGreaterThanOrEqual(0);
  expect(headlineBounds!.y + headlineBounds!.height).toBeLessThan(900);

  const validation = page.locator('details[aria-label="Validation"]');
  const activity = page.locator('details[aria-label="Activity log"]');
  await expect(validation).toHaveJSProperty("open", false);
  await expect(activity).toHaveJSProperty("open", false);
  const runReference = activity.locator(".detail-run-reference");
  await expect(runReference).toBeHidden();
  await expect(page.locator(".detail-status-row")).not.toContainText(run.id);
  await validation.locator("summary").click();
  await expect(
    validation.getByRole("heading", {
      name: "Successful allocations do not exceed the obligation",
    }),
  ).toBeVisible();
  await validation.locator("summary").click();
  await activity.locator("summary").click();
  await expect(runReference).toBeVisible();
  await expect(runReference.locator("code")).toHaveText(run.id);
  await expect(runReference).toContainText("Snapshot");
  await expect(
    activity.getByRole("region", { name: "Run diagnostics" }),
  ).toBeVisible();
  await activity.locator("summary").click();
  await expect(runReference).toBeHidden();

  const record = run.evidence[0];
  const evidenceButton = page.getByRole("button", {
    name: `View evidence ${record.id}`,
    exact: true,
  });
  await evidenceButton.click();
  const drawer = page.getByRole("dialog", { name: "Original record" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByLabel("Evidence record")).toHaveValue(record.id);
  await expect(drawer).toContainText(record.recordId);
  await expect(drawer).toContainText(record.datasetVersion);
  await expect(drawer).toContainText(record.queryId);
  await expect(
    drawer.getByRole("heading", { name: "Query provenance" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(evidenceButton).toBeFocused();

  const review = page.locator(".detail-review");
  await review
    .getByLabel("Reviewer note")
    .fill("Checked settled allocations and linked bank records.");
  const posted = page.waitForRequest(
    (req) =>
      req.method() === "POST" &&
      new URL(req.url()).pathname === `/api/investigations/${run.id}/review`,
  );
  await review
    .getByRole("button", { name: "Accept findings", exact: true })
    .click();
  expect((await posted).postDataJSON()).toMatchObject({
    decision: "accepted",
    notes: "Checked settled allocations and linked bank records.",
    approveMemory: false,
  });
  await expect(review.locator(".review-receipt")).toContainText("Accepted");
  const reviewed = await (
    await request.get(`/api/investigations/${run.id}`)
  ).json();
  expect(reviewed.review.memoryId).toBeUndefined();
  expect(reviewed.evidence).toEqual(run.evidence);
  await page.reload();
  await expect(page.locator(".detail-review .review-receipt")).toContainText(
    "Checked settled allocations and linked bank records.",
  );
  await expect(page.locator(".detail-memory")).toContainText("Not approved");
  await page.screenshot({
    path: info.outputPath("investigation-detail-desktop.png"),
    fullPage: true,
  });
});
