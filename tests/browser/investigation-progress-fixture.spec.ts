import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type {
  Case,
  Dataset,
  Investigation,
} from "../../packages/contracts/src/index";

test("a real fixture investigation exposes recorded tools and their source evidence", async ({
  page,
  request,
}, info) => {
  const packet = JSON.parse(
    await readFile(resolve("data/manual-test/valid-bundle.json"), "utf8"),
  );
  // Keep this new investigation separate from the seeded inbox workflow case.
  packet.manifest.name = `Progress fixture ${info.testId}`;
  const imported = await request.post("/api/datasets", {
    data: packet,
  });
  expect(imported.ok()).toBe(true);
  const { dataset } = (await imported.json()) as { dataset: Dataset };
  const { cases } = (await (
    await request.get(`/api/cases?datasetId=${dataset.id}`)
  ).json()) as { cases: Case[] };
  const started = await request.post("/api/investigations", {
    data: { datasetId: dataset.id, paymentId: cases[0].paymentId },
  });
  expect(started.ok()).toBe(true);
  const { id } = (await started.json()) as Investigation;
  let run!: Investigation;
  await expect
    .poll(async () => {
      run = (await (
        await request.get(`/api/investigations/${id}`)
      ).json()) as Investigation;
      return run.status;
    })
    .toBe("completed");
  expect(run.outcome).toBe("anomaly_supported");

  await page.goto(`/?investigation=${id}`);
  const progress = page.getByRole("region", {
    name: "Investigation activity",
    exact: true,
  });
  await progress
    .getByRole("button", { name: "Expand investigation activity" })
    .click();
  await expect(progress).toContainText("Rule-based checks");
  const tools = run.events.filter(
    (event) =>
      event.activity?.kind === "tool" && event.activity.status === "completed",
  );
  expect(tools).toHaveLength(run.queries.length);
  for (const event of tools) {
    const step = progress.locator(`[data-activity-id="${event.activity!.id}"]`);
    await expect(step).toHaveAttribute("data-status", "completed");
    await expect(step).toContainText(event.activity!.reason!);
    await expect(step).toContainText(event.activity!.summary!);
  }
  await expect(progress.locator('[data-status="running"]')).toHaveCount(0);
  await progress.screenshot({
    path: info.outputPath("real-fixture-investigation-progress.png"),
  });

  const bank = tools.find((event) => event.tool === "settlements")!;
  const evidenceId = bank.activity!.evidenceIds![0];
  const bankStep = progress.locator(
    `[data-activity-id="${bank.activity!.id}"]`,
  );
  const button = bankStep.getByRole("button", {
    name: `View evidence ${evidenceId}`,
    exact: true,
  });
  await expect(button).toBeHidden();
  await bankStep
    .locator("details.investigation-progress-evidence-disclosure > summary")
    .click();
  await button.click();
  const drawer = page.getByRole("dialog", { name: "Original record" });
  await expect(drawer.getByLabel("Evidence record")).toHaveValue(evidenceId);
  await expect(drawer).toContainText(bank.activity!.queryId!);
  await page.keyboard.press("Escape");
  await expect(button).toBeFocused();
});
