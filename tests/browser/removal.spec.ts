import { test, expect, type APIRequestContext } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

async function dataset(request: APIRequestContext, name: string) {
  const packet = JSON.parse(
    await readFile(resolve("data/fresh-manual/fresh-test-bundle.json"), "utf8"),
  );
  packet.manifest.name = name;
  const response = await request.post("/api/datasets", {
    data: packet,
  });
  expect(response.status()).toBe(201);
  return (await response.json()).dataset;
}

test("failed removal keeps the confirmation open for retry and historical investigations retain dataset metadata", async ({
  page,
  request,
}) => {
  const ds = await dataset(request, "Historical removal packet");
  const started = await request.post("/api/investigations", {
    data: { datasetId: ds.id, paymentId: "PAY_NEW_NORMAL_01" },
  });
  expect(started.ok()).toBe(true);
  const run = await started.json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${run.id}`)).json())
          .status,
    )
    .toBe("completed");
  await page.route(
    "**/api/datasets/removal",
    (route) =>
      route.fulfill({
        status: 503,
        json: { error: "Removal service unavailable. Please retry." },
      }),
    { times: 1 },
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await page.getByLabel("Search datasets", { exact: true }).fill(ds.name);
  await page
    .getByRole("button", { name: `Remove dataset ${ds.name}`, exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Remove 1 dataset", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Removal service unavailable",
  );
  await expect(page.locator(".dataset-card")).toHaveCount(1);
  await dialog
    .getByRole("button", { name: "Remove 1 dataset", exact: true })
    .click();
  await expect(page.locator(".dataset-card")).toHaveCount(0);
  await page.goto(`/?investigation=${run.id}`);
  await expect(
    page.getByRole("heading", { name: "Your data. A clear provenance." }),
  ).toHaveCount(0);
  await expect(page.locator(".workspace-bottom")).toContainText(
    `${ds.name} · ${ds.version}`,
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
  await expect(page.getByLabel("Active dataset")).toHaveValue("all");
});

test("datasets support filtered bulk selection, confirmation, undo and persistent single removal", async ({
  page,
  request,
}, info) => {
  const first = await dataset(request, "Removal browser packet A");
  await dataset(request, "Removal browser packet B");
  await page.goto("/");
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await page
    .getByLabel("Search datasets", { exact: true })
    .fill("Removal browser packet");
  await page.getByRole("heading", { name: first.name, exact: true }).click();
  await expect(page.getByLabel("Active dataset")).toHaveValue(first.id);
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await page.getByLabel("Select all matching datasets").check();
  await expect(page.getByLabel("dataset selection")).toContainText(
    "2 datasets selected",
  );
  await page
    .getByRole("button", { name: "Remove selected", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Remove 2 datasets?" });
  await expect(dialog).toContainText(first.name);
  await expect(dialog).toContainText(
    "Existing investigations and source evidence remain available",
  );
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.locator(".dataset-card")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Remove selected", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Remove 2 datasets", exact: true })
    .click();
  await expect(page.locator(".dataset-card")).toHaveCount(0);
  await expect(page.locator(".resource-notice")).toContainText(
    "2 datasets removed",
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".dataset-card")).toHaveCount(2);
  await page
    .getByRole("button", { name: `Remove dataset ${first.name}`, exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Remove 1 dataset", exact: true })
    .click();
  await expect(page.locator(".dataset-card")).toHaveCount(1);
  await page.getByRole("button", { name: /^Case inbox/ }).click();
  await expect(page.getByLabel("Active dataset")).toHaveValue("all");
  await page.reload();
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await page
    .getByLabel("Search datasets", { exact: true })
    .fill("Removal browser packet");
  await expect(page.locator(".dataset-card")).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const box = await page.locator(".sidebar").boundingBox();
      return box ? box.x + box.width : 0;
    })
    .toBeLessThanOrEqual(1);
  await expect(page.getByLabel("Select all matching datasets")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("dataset-removal-mobile.png"),
    fullPage: true,
  });
});

test("partial dataset removal keeps failed items selected and explains the failure", async ({
  page,
  request,
}) => {
  const first = await dataset(request, "Partial removal packet A");
  const second = await dataset(request, "Partial removal packet B");
  await page.route("**/api/datasets/removal", async (route) => {
    const payload = route.request().postDataJSON();
    if (!payload.removed) return route.continue();
    const result = await request.post("/api/datasets/removal", {
      data: { ids: [first.id], removed: true },
    });
    const { results } = await result.json();
    await route.fulfill({
      json: {
        results: [
          ...results,
          {
            id: second.id,
            success: false,
            error: "This dataset has an active investigation.",
          },
        ],
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  await page
    .getByLabel("Search datasets", { exact: true })
    .fill("Partial removal packet");
  await page.getByLabel("Select all matching datasets").check();
  await page
    .getByRole("button", { name: "Remove selected", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Remove 2 datasets", exact: true })
    .click();
  await expect(page.locator(".dataset-card")).toHaveCount(1);
  await expect(
    page.getByLabel(`Select dataset ${second.name}`, { exact: true }),
  ).toBeChecked();
  await expect(page.getByRole("alert")).toContainText("active investigation");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".dataset-card")).toHaveCount(2);
});

test("memory removal supports single and bulk confirmation, preserves status on undo and persists on reload", async ({
  page,
  request,
}, info) => {
  const ds = await dataset(request, "Memory removal packet");
  const run = await (
    await request.post("/api/investigations", {
      data: { datasetId: ds.id, paymentId: "PAY_NEW_NORMAL_01" },
    })
  ).json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${run.id}`)).json())
          .status,
    )
    .toBe("completed");
  const reviewed = await (
    await request.post(`/api/investigations/${run.id}/review`, {
      data: {
        decision: "accepted",
        approveMemory: true,
        memoryContent: "Removal browser memory A: review allocations.",
      },
    })
  ).json();
  await request.patch(`/api/memories/${reviewed.review.memoryId}`, {
    data: { status: "inactive" },
  });
  expect(
    (
      await request.post(`/api/investigations/${run.id}/review`, {
        data: {
          decision: "accepted",
          approveMemory: true,
          memoryContent: "Removal browser memory B: review ledger.",
        },
      })
    ).ok(),
  ).toBe(true);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Investigation memories", exact: true })
    .click();
  const firstCard = page
    .locator(".memory-panel article")
    .filter({ hasText: "Removal browser memory A" });
  await firstCard.getByRole("button", { name: /Remove memory/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Remove 1 memory", exact: true })
    .click();
  await expect(firstCard).toHaveCount(0);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(firstCard).toContainText("inactive");
  await page.getByLabel("Memory status").selectOption("active");
  const activeCount = await page.locator(".memory-panel article").count();
  await page.getByLabel("Select all matching memories").check();
  await expect(page.getByLabel("memory selection")).toContainText(
    `${activeCount} memories selected`,
  );
  await page
    .getByRole("button", { name: "Remove selected", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", {
      name: `Remove ${activeCount} ${activeCount === 1 ? "memory" : "memories"}`,
      exact: true,
    })
    .click();
  await expect(page.locator(".memory-panel article")).toHaveCount(0);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".memory-panel article")).toHaveCount(activeCount);
  await page.getByLabel("Memory status").selectOption("all");
  await firstCard.getByRole("button", { name: /Remove memory/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Remove 1 memory", exact: true })
    .click();
  await expect(firstCard).toHaveCount(0);
  await page.reload();
  await page
    .getByRole("button", { name: "Investigation memories", exact: true })
    .click();
  await expect(firstCard).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const box = await page.locator(".sidebar").boundingBox();
      return box ? box.x + box.width : 0;
    })
    .toBeLessThanOrEqual(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("memory-removal-mobile.png"),
    fullPage: true,
  });
  expect(
    (
      await request.get(`/api/investigations/${run.id}/export?format=json`)
    ).ok(),
  ).toBe(true);
});
