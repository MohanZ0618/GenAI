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

test("saved results reopen without new starts and changed data requires an explicit update", async ({
  page,
  request,
}) => {
  const bundle = JSON.parse(
    await readFile(resolve("data/openai-manual/01-main-bundle.json"), "utf8"),
  );
  bundle.manifest.name = "Result reuse browser verification";
  const original = (
    await (await request.post("/api/datasets", { data: bundle })).json()
  ).dataset;
  let starts = 0;
  page.on("request", (req) => {
    if (
      req.method() === "POST" &&
      new URL(req.url()).pathname === "/api/investigations"
    )
      starts++;
  });
  await page.goto("/");
  await page.getByLabel("Active dataset").selectOption(original.id);
  await page.getByLabel("Search cases").fill("PAY_DEMO_NORMAL");
  await page
    .getByRole("button", { name: "Investigate PAY_DEMO_NORMAL", exact: true })
    .click();
  await completedDialog(page);
  const oldUrl = page.url();
  const oldId = new URL(oldUrl).searchParams.get("investigation");
  await caseInbox(page);
  await page
    .getByRole("button", { name: "View result PAY_DEMO_NORMAL", exact: true })
    .click();
  await expect(page).toHaveURL(oldUrl);
  await expect(page.getByText(/Saved result — reopening/)).toBeVisible();
  await page.reload();
  await completedDialog(page);
  expect(starts).toBe(1);
  bundle.manifest.clearingDays++;
  const revised = (
    await (await request.post("/api/datasets", { data: bundle })).json()
  ).dataset;
  await caseInbox(page);
  await page.getByRole("button", { name: "Refresh API connection" }).click();
  await page.getByLabel("Active dataset").selectOption(original.id);
  await page.getByLabel("Search cases").fill("PAY_DEMO_NORMAL");
  await page
    .getByRole("button", { name: "View result PAY_DEMO_NORMAL", exact: true })
    .click();
  await completedDialog(page);
  await expect(
    page.getByText(/Update available — a newer data snapshot/),
  ).toBeVisible();
  expect(starts).toBe(1);
  await caseInbox(page);
  await page.getByLabel("Active dataset").selectOption(revised.id);
  await expect(
    page.locator(".case-table tbody tr").filter({ hasText: "PAY_DEMO_NORMAL" }),
  ).toContainText("Update available");
  await page
    .getByRole("button", {
      name: "Update investigation PAY_DEMO_NORMAL",
      exact: true,
    })
    .click();
  await completedDialog(page);
  const newId = new URL(page.url()).searchParams.get("investigation");
  expect(newId).not.toBe(oldId);
  expect(starts).toBe(2);
  expect(
    (await (await request.get(`/api/investigations/${oldId}`)).json())
      .datasetId,
  ).toBe(original.id);
  await caseInbox(page);
  await page
    .getByRole("button", { name: "View result PAY_DEMO_NORMAL", exact: true })
    .click();
  await completedDialog(page);
  expect(new URL(page.url()).searchParams.get("investigation")).toBe(newId);
  expect(starts).toBe(2);
});
