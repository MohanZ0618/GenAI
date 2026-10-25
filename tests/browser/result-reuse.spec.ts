import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

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
  await expect(page.locator(".run-status")).toHaveText(/Completed/);
  const oldUrl = page.url();
  const oldId = new URL(oldUrl).searchParams.get("investigation");
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
  await page
    .getByRole("button", { name: "View result PAY_DEMO_NORMAL", exact: true })
    .click();
  await expect(page).toHaveURL(oldUrl);
  await expect(page.getByText(/Saved result — reopening/)).toBeVisible();
  await page.reload();
  await expect(page.locator(".run-status")).toHaveText(/Completed/);
  expect(starts).toBe(1);
  bundle.manifest.clearingDays++;
  const revised = (
    await (await request.post("/api/datasets", { data: bundle })).json()
  ).dataset;
  await page.getByRole("button", { name: "Refresh API connection" }).click();
  await expect(
    page.getByText(/Update available — a newer data snapshot/),
  ).toBeVisible();
  expect(starts).toBe(1);
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
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
  await expect(page.locator(".run-status")).toHaveText(/Completed/);
  const newId = new URL(page.url()).searchParams.get("investigation");
  expect(newId).not.toBe(oldId);
  expect(starts).toBe(2);
  expect(
    (await (await request.get(`/api/investigations/${oldId}`)).json())
      .datasetId,
  ).toBe(original.id);
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
  await page
    .getByRole("button", { name: "View result PAY_DEMO_NORMAL", exact: true })
    .click();
  expect(new URL(page.url()).searchParams.get("investigation")).toBe(newId);
  expect(starts).toBe(2);
});
