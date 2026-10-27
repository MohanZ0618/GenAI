import { test, expect } from "@playwright/test";

test("memory card actions align on desktop and mobile", async ({
  page,
}, info) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const memories = ["active", "inactive"].map((status, index) => ({
    id: `layout-memory-${index}`,
    content: "Review allocations against bank and ledger evidence.",
    source: "layout-source",
    namespace: "workspace",
    status,
    scope: "workspace",
    approvedAt: "2026-10-26T12:00:00Z",
    generationSource: "manual",
    conditions: "Payment reconciliation",
    suggestedTools: ["allocations"],
    evidenceIds: [],
  }));
  await page.route("**/api/memories", (route) =>
    route.fulfill({ json: { memories } }),
  );
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets: [] } }),
  );
  await page.route("**/api/cases?*", (route) =>
    route.fulfill({ json: { cases: [] } }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Investigation memories", exact: true })
    .click();
  const cards = page.locator(".memory-panel article");
  await expect(cards).toHaveCount(2);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const card of await cards.all()) {
      const buttons = card.locator(".memory-card-buttons .button");
      const first = await buttons.nth(0).boundingBox();
      const second = await buttons.nth(1).boundingBox();
      expect(first).not.toBeNull();
      expect(second).not.toBeNull();
      expect(Math.abs(first!.y - second!.y)).toBeLessThan(1);
      expect(Math.abs(first!.height - second!.height)).toBeLessThan(1);
      expect(second!.x - first!.x - first!.width).toBeGreaterThanOrEqual(9);
      const checkbox = await card
        .locator(".memory-card-header input")
        .boundingBox();
      const title = await card
        .locator(".memory-card-header strong")
        .boundingBox();
      expect(
        Math.abs(
          checkbox!.y + checkbox!.height / 2 - title!.y - title!.height / 2,
        ),
      ).toBeLessThan(1);
      if (width === 390) {
        const link = await card
          .getByRole("link", { name: "Open source investigation" })
          .boundingBox();
        expect(first!.y).toBeGreaterThanOrEqual(link!.y + link!.height);
      }
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`memory-actions-${width}.png`),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page
    .getByRole("button", { name: "Investigation memories", exact: true })
    .click();
  await expect(cards.locator(".memory-card-buttons")).toHaveCount(2);
});

test("request changes, suggest, accept and correct an existing memory without losing notes", async ({
  page,
  request,
}) => {
  const { datasets } = await (await request.get("/api/datasets")).json();
  const ds = datasets.find(
    (item: { name: string }) => item.name === "Review packet 005",
  );
  const { cases } = await (
    await request.get(`/api/cases?datasetId=${ds.id}`)
  ).json();
  const run = await (
    await request.post("/api/investigations", {
      data: { datasetId: ds.id, paymentId: cases[0].paymentId },
    })
  ).json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${run.id}`)).json())
          .status,
    )
    .toBe("completed");
  const seeded = await request.post(`/api/investigations/${run.id}/review`, {
    data: { decision: "accepted", approveMemory: true, memoryContent: "test" },
  });
  expect(seeded.ok()).toBe(true);
  await page.goto(`/?investigation=${run.id}`);
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await expect(
    page.getByText("Existing approved memory", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Request changes/ }).click();
  await page
    .getByRole("button", { name: "Suggest memory", exact: true })
    .click();
  await expect(page.getByText(/Draft: ready/)).toBeVisible();
  await expect(page.getByLabel("Approve a reusable memory")).toBeDisabled();
  await page.getByRole("button", { name: /Accept findings/ }).click();
  await page.getByLabel("Approve a reusable memory").check();
  await page.getByLabel("Review notes").fill("Keep my review notes");
  await page
    .getByLabel("Confirmed lesson", { exact: true })
    .fill("Reconcile allocations with bank and ledger evidence.");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Deactivate the existing memory",
  );
  await page
    .getByRole("button", { name: "Deactivate existing memory", exact: true })
    .click();
  await expect(
    page.getByText("Existing approved memory", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Review notes")).toHaveValue(
    "Keep my review notes",
  );
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  const { memories } = await (await request.get("/api/memories")).json();
  const sourceMemories = memories.filter(
    (item: { source: string }) => item.source === run.id,
  );
  expect(
    sourceMemories.find((item: { content: string }) => item.content === "test")
      .status,
  ).toBe("inactive");
  expect(
    sourceMemories.filter(
      (item: { status: string }) => item.status === "active",
    ),
  ).toHaveLength(1);
});

test("memory draft, approval, immutable management, source and mobile refresh", async ({
  page,
  request,
}, info) => {
  const { datasets } = await (await request.get("/api/datasets")).json();
  const ds = datasets.find(
    (d: { name: string }) => d.name === "Review packet 003",
  );
  const { cases } = await (
    await request.get(`/api/cases?datasetId=${ds.id}`)
  ).json();
  const run = await (
    await request.post("/api/investigations", {
      data: { datasetId: ds.id, paymentId: cases[0].paymentId },
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
  await page
    .getByRole("button", { name: "Suggest memory", exact: true })
    .click();
  await expect(page.getByText(/Draft: ready/)).toBeVisible();
  await expect(
    page.getByText(/Deterministic fixture example · no model called/),
  ).toBeVisible();
  const draft = (
    await (await request.get(`/api/investigations/${run.id}`)).json()
  ).memoryDraft;
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.reload();
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await expect(page.getByText(/Draft: ready/)).toBeVisible();
  await page
    .getByRole("button", { name: "Suggest memory", exact: true })
    .click();
  expect(
    (await (await request.get(`/api/investigations/${run.id}`)).json())
      .memoryDraft.id,
  ).toBe(draft.id);
  await page.getByLabel("Approve a reusable memory").check();
  const content = `Browser verified procedure: inspect vendor history and allocations before ledger review. ${run.id}`;
  await page.getByLabel("Confirmed lesson", { exact: true }).fill(content);
  await page.getByLabel("Memory scope", { exact: true }).selectOption("vendor");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  await page
    .getByRole("button", { name: "Investigation memories", exact: true })
    .click();
  const card = page
    .locator(".memory-panel article")
    .filter({ hasText: content });
  await expect(card).toContainText("vendor");
  await expect(card).toContainText("Generated by: fixture");
  await card.getByRole("button", { name: "Deactivate", exact: true }).click();
  await expect(card).toContainText("inactive");
  await card.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(
    card.getByRole("button", { name: "Deactivate", exact: true }),
  ).toBeEnabled();
  await page.screenshot({
    path: info.outputPath("memories-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(async () => {
      const box = await page.locator(".sidebar").boundingBox();
      return box ? box.x + box.width : 0;
    })
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: info.outputPath("memories-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await card.getByRole("link", { name: "Open source investigation" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  await page.reload();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
});

test("failed draft keeps manual approval available", async ({
  page,
  request,
}) => {
  const { datasets } = await (await request.get("/api/datasets")).json();
  const ds = datasets.find(
    (d: { name: string }) => d.name === "Review packet 004",
  );
  const { cases } = await (
    await request.get(`/api/cases?datasetId=${ds.id}`)
  ).json();
  const run = await (
    await request.post("/api/investigations", {
      data: { datasetId: ds.id, paymentId: cases[0].paymentId },
    })
  ).json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/investigations/${run.id}`)).json())
          .status,
    )
    .toBe("completed");
  await page.route(
    `**/api/investigations/${run.id}/memory-draft`,
    async (route) => {
      const completed = await (
        await request.get(`/api/investigations/${run.id}`)
      ).json();
      await route.fulfill({
        json: {
          ...completed,
          memoryDraft: {
            id: "mock-failure",
            status: "failed",
            source: "model",
            provider: "openai",
            model: "mock",
            createdAt: "",
            error: "Model connection failed; manual entry remains available.",
          },
        },
      });
    },
  );
  await page.goto(`/?investigation=${run.id}`);
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Suggest memory", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Model connection failed",
  );
  await expect(
    page.getByRole("button", { name: "Retry memory suggestion" }),
  ).toBeEnabled();
  await page.getByLabel("Approve a reusable memory").check();
  await page
    .getByLabel("Confirmed lesson", { exact: true })
    .fill(
      "Manual procedure: inspect allocations and reconcile current settlement evidence.",
    );
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
});
