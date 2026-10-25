import { test, expect, type Page } from "@playwright/test";
import { resolve } from "node:path";

async function assertLocked(page: Page) {
  await expect(
    page.getByRole("button", { name: "Close dialog" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.locator(".modal-overlay").click({ position: { x: 4, y: 4 } });
  await expect(page.getByRole("dialog")).toBeVisible();
}

test("review consent stays valid and saving uses the POST result", async ({
  page,
  request,
}) => {
  const { datasets } = await (await request.get("/api/datasets")).json();
  const packet = datasets.find(
    (item: { name: string }) => item.name === "Review packet 002",
  );
  const { cases } = await (
    await request.get(`/api/cases?datasetId=${packet.id}`)
  ).json();
  const run = await (
    await request.post("/api/investigations", {
      data: { datasetId: packet.id, paymentId: cases[0].paymentId },
    })
  ).json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${run.id}`)).json())
          .status,
    )
    .toBe("completed");
  await page.goto(`/?investigation=${run.id}`);
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  const consent = page.getByLabel("Approve a reusable memory");
  await consent.check();
  await page
    .getByLabel("Confirmed lesson", { exact: true })
    .fill("Confirmed source evidence.");
  await page.getByRole("button", { name: /Request changes/ }).click();
  await expect(consent).not.toBeChecked();
  await expect(consent).toBeDisabled();
  await page.getByRole("button", { name: /Accept findings/ }).click();
  await expect(consent).toBeEnabled();
  await expect(consent).not.toBeChecked();
  await page.getByLabel("Review notes").fill("Saved without a second fetch.");
  let release!: () => void;
  const pending = new Promise<void>((done) => {
    release = done;
  });
  let posted: unknown;
  await page.route(`**/api/investigations/${run.id}/review`, async (route) => {
    posted = route.request().postDataJSON();
    await pending;
    await route.continue();
  });
  let detailRequests = 0;
  await page.route(`**/api/investigations/${run.id}`, (route) => {
    detailRequests++;
    return route.abort();
  });
  await page.getByRole("button", { name: "Save human review" }).click();
  try {
    await assertLocked(page);
    await expect(page.getByLabel("Review notes")).toBeDisabled();
    await expect(
      page.getByRole("button", { name: /Request changes/ }),
    ).toBeDisabled();
    await expect(consent).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  expect(posted).toMatchObject({ decision: "accepted", approveMemory: false });
  expect(detailRequests).toBe(0);
});

test("import remains locked while pending and unlocks after failure", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Import dataset", exact: true })
    .click();
  await page
    .getByLabel("Dataset files")
    .setInputFiles(resolve("data/manual-test/valid-bundle.json"));
  let release!: () => void;
  const pending = new Promise<void>((done) => {
    release = done;
  });
  await page.route("**/api/datasets", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await pending;
    await route.fulfill({
      status: 400,
      json: { error: "Test validation failure" },
    });
  });
  await page.getByRole("button", { name: "Validate & import" }).click();
  try {
    await assertLocked(page);
    await expect(page.getByLabel("Dataset files")).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Remove valid-bundle.json" }),
    ).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.getByRole("alert")).toContainText(
    "Test validation failure",
  );
  await expect(
    page.getByRole("button", { name: "Validate & import" }),
  ).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("button depth preserves layout and respects reduced motion", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  const button = page.getByRole("button", {
    name: "Import dataset",
    exact: true,
  });
  await button.hover();
  await expect(button).toHaveCSS("transform", "matrix(1, 0, 0, 1, 0, -1)");
  await page.mouse.down();
  await expect(button).toHaveCSS("transform", "matrix(1, 0, 0, 1, 0, 1)");
  await page.mouse.move(1, 1);
  await page.mouse.up();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await button.hover();
  await expect(button).toHaveCSS("transform", "none");
  await page.screenshot({
    path: testInfo.outputPath("buttons-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await button.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("buttons-mobile.png"),
    fullPage: true,
  });
});
