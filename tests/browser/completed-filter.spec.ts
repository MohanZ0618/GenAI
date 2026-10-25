import { test, expect } from "@playwright/test";
import type {
  Case,
  Dataset,
  Investigation,
} from "../../packages/contracts/src/index";

test("completing three of eight cases updates filters and survives reload", async ({
  page,
}) => {
  const dataset: Dataset = {
    id: "completed-filter",
    name: "Completed filter regression",
    version: "v1",
    asOf: "2026-06-30T12:00:00Z",
    caseCount: 8,
    coverage: {},
    clearingDays: 3,
    currency: "USD",
    createdAt: "2026-06-30T12:00:00Z",
    builtin: false,
  };
  const cases: Case[] = Array.from({ length: 8 }, (_, index) => ({
    id: `filter-case-${index}`,
    paymentId: `PAY_FILTER_${index}`,
    datasetId: dataset.id,
    vendor: `Filter vendor ${index}`,
    amount: "100",
    currency: "USD",
    date: "2026-06-30",
    symptom: "Payment discrepancy",
    status: [
      "unreviewed",
      "unreviewed",
      "unreviewed",
      "unreviewed",
      "queued",
      "running",
      "failed",
      "cancelled",
    ][index],
  }));
  const runs = new Map<string, Investigation>();
  await page.route("**/api/datasets", (route) =>
    route.fulfill({ json: { datasets: [dataset] } }),
  );
  await page.route("**/api/cases?*", (route) =>
    route.fulfill({ json: { cases } }),
  );
  await page.route("**/api/investigations", (route) => {
    const { paymentId } = route.request().postDataJSON();
    const item = cases.find((entry) => entry.paymentId === paymentId)!;
    const run: Investigation = {
      id: `run-${item.id}`,
      datasetId: dataset.id,
      paymentId,
      status: "queued",
      mode: "fixture",
      provider: "deterministic-fixture",
      model: "none",
      createdAt: "2026-06-30T12:00:00Z",
      updatedAt: "2026-06-30T12:00:00Z",
      outcome: null,
      findings: [],
      checks: [],
      actions: [],
      evidence: [],
      events: [],
      queries: [],
      memories: [],
      modelTurns: 0,
    };
    runs.set(run.id, run);
    item.investigationId = run.id;
    return route.fulfill({ json: run });
  });
  await page.route("**/api/investigations/*", (route) => {
    const run = runs.get(
      new URL(route.request().url()).pathname.split("/").at(-1)!,
    )!;
    run.status = "completed";
    cases.find((item) => item.paymentId === run.paymentId)!.status =
      "completed";
    return route.fulfill({ json: run });
  });

  await page.goto("/");
  await page.getByLabel("Active dataset").selectOption(dataset.id);
  const rows = page.locator(".case-table tbody tr");
  const unreviewed = page.getByRole("button", {
    name: "Unreviewed",
    exact: true,
  });
  const reviewed = page.getByRole("button", { name: "Reviewed", exact: true });
  await unreviewed.click();
  await expect(rows).toHaveCount(8);
  await expect(reviewed.locator(".filter-count")).toHaveText("0");

  for (let index = 0; index < 3; index++) {
    await page
      .getByRole("button", {
        name: `Investigate PAY_FILTER_${index}`,
        exact: true,
      })
      .click();
    await expect(page.locator(".run-status")).toHaveText(/Completed/);
    await expect(
      page.getByRole("region", { name: "Next steps and human review" }),
    ).toContainText("Awaiting human review");
    await page.getByRole("button", { name: "Case inbox", exact: true }).click();
    await expect(unreviewed.locator(".filter-count")).toHaveText(
      String(7 - index),
    );
    await expect(reviewed.locator(".filter-count")).toHaveText(
      String(index + 1),
    );
    await expect(rows).toHaveCount(7 - index);
  }

  await expect(
    page
      .locator(".stat-card")
      .filter({ hasText: "Awaiting review" })
      .locator("strong"),
  ).toHaveText("5");
  await reviewed.click();
  await expect(rows).toHaveCount(3);
  await expect(rows.locator(".status-pill")).toHaveText([
    "Completed",
    "Completed",
    "Completed",
  ]);
  await page.getByLabel("Search cases").fill("PAY_FILTER_0");
  await expect(reviewed.locator(".filter-count")).toHaveText("1");
  await expect(unreviewed.locator(".filter-count")).toHaveText("0");
  await expect(rows).toHaveCount(1);

  await page.reload();
  await expect(page.locator(".run-status")).toHaveText(/Completed/);
  await page.getByRole("button", { name: "Case inbox", exact: true }).click();
  await expect(unreviewed.locator(".filter-count")).toHaveText("5");
  await expect(reviewed.locator(".filter-count")).toHaveText("3");
  await reviewed.click();
  await expect(rows).toHaveCount(3);
  await unreviewed.click();
  await expect(rows).toHaveCount(5);
  await page.getByLabel("Active dataset").selectOption("all");
  await expect(unreviewed.locator(".filter-count")).toHaveText("5");
  await expect(reviewed.locator(".filter-count")).toHaveText("3");
  expect([...runs.values()].every((run) => run.review === undefined)).toBe(
    true,
  );
});
