import { test, expect, type Page } from "@playwright/test";
import { readFile, readdir, mkdtemp, mkdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { spawn } from "node:child_process";

async function waitForCompletedInvestigation(page: Page) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveCount(1);
  await expect(dialog).toBeVisible();
  const status = dialog.locator(".run-status");
  const skipPlayback = dialog.getByRole("button", {
    name: "Skip to results",
    exact: true,
  });
  // This suite covers the product features; dedicated playback tests cover the
  // paced presentation. Skip only after the backend has actually completed.
  await expect(status.or(skipPlayback)).toBeVisible({ timeout: 15000 });
  if (await skipPlayback.isVisible()) await skipPlayback.click();
  await expect(status).toHaveText(/Completed/, { timeout: 15000 });
  await expect(page).toHaveURL(/[?&]view=dialog(?:&|$)/);
  const params = new URL(page.url()).searchParams;
  expect(params.get("view")).toBe("dialog");
  expect(params.get("investigation")).toBeTruthy();
  return params.get("investigation")!;
}

async function investigate(page: Page) {
  await page
    .getByRole("button", {
      name: /^(Start investigation|View result|Update investigation|Retry investigation)$/,
    })
    .click();
  return waitForCompletedInvestigation(page);
}

async function caseInbox(page: Page) {
  const close = page.getByRole("button", {
    name: "Close investigation",
    exact: true,
  });
  // A dialog deep link resumes after the initial dataset load. Wait for that
  // restoration before closing it, so it cannot open later over inbox actions.
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

test("navigation, search, review decisions, approved memory, all exports and connection recovery", async ({
  page,
  request,
}) => {
  const datasets = (await (await request.get("/api/datasets")).json()).datasets;
  const packet = datasets.find(
    (d: { name: string }) => d.name === "Review packet 013",
  );
  await page.goto("/");
  await page.getByLabel("Active dataset").selectOption(packet.id);
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  await page.getByLabel("Search cases").fill("no-such-payment-xyz");
  await expect(
    page.getByRole("heading", { name: "No matching cases" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByLabel("Search cases").fill("PAY_0424562");
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "Clear search" }).click();
  await page.getByRole("button", { name: "How FinTrace works" }).click();
  await expect(
    page.getByRole("heading", { name: "Confidence comes from evidence." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Explore the case inbox" }).click();
  const id = await investigate(page);
  const activity = page
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: "Activity log" }) });
  await activity.locator("summary").click();
  await expect(activity).toContainText(
    /(?:Read|Retrieved) \d+ source records?/,
  );
  const validation = page
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: "Validation" }) });
  await validation.locator("summary").click();
  await expect(validation).toContainText(/passed|Pass/i);
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(
    page.getByRole("dialog", { name: "Review the investigation", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Request changes/ })
    .click();
  await page
    .getByLabel("Review notes")
    .fill("Please check the effective change date.");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Needs Changes");
  await caseInbox(page);
  await page.getByRole("button", { name: "Reviewed", exact: true }).click();
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Investigation", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const savedRun = page.locator(`[data-investigation-id="${id}"]`);
  await expect(savedRun).toBeVisible();
  await savedRun
    .getByRole("button", { name: /^View investigation / })
    .click();
  await expect(
    page.getByRole("region", { name: "Investigation conclusion" }),
  ).toBeVisible();
  expect(
    (await (await request.get(`/api/investigations/${id}`)).json()).review
      .memoryId,
  ).toBeUndefined();
  await caseInbox(page);
  expect(await investigate(page)).toBe(id);
  await page
    .getByRole("button", { name: "Review findings", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Accept findings/ })
    .click();
  await page
    .getByLabel("Review notes")
    .fill("Confirmed against source records.");
  await page.getByLabel("Approve a reusable memory").check();
  await expect(
    page.getByRole("button", { name: "Save human review" }),
  ).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Confirmed lesson", exact: true })
    .fill("Inspect ledger before settlements during payment review.");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  expect(
    (await (await request.get(`/api/investigations/${id}`)).json()).review
      .memoryId,
  ).toBeTruthy();
  await page.reload();
  await expect(page.locator(".review-receipt")).toContainText("Accepted");
  for (const [name, extension] of [
    ["HTML report", "html"],
    ["JSON", "json"],
    ["CSV", "csv"],
  ]) {
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: new RegExp(name) }).click();
    const download = await pending;
    expect(download.suggestedFilename()).toMatch(
      new RegExp(`\\.${extension}$`),
    );
    const content = await readFile((await download.path())!, "utf8");
    expect(content.length).toBeGreaterThan(100);
    if (extension === "json")
      expect(JSON.parse(content).review.memoryId).toBeTruthy();
    if (extension === "csv")
      expect(content).toContain("execution_mode,model_provider,model");
  }
  await caseInbox(page);
  // Refreshing a dialog preserves the inbox's own scope. Explicitly restore the
  // single reviewed packet before checking its empty unreviewed filter.
  await page.getByLabel("Active dataset").selectOption(packet.id);
  await page.getByRole("button", { name: "Reviewed", exact: true }).click();
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "Unreviewed", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No matching cases" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "All cases", exact: true }).click();
  const nextId = await investigate(page);
  expect(nextId).toBe(id);
  expect(
    (await (await request.get(`/api/investigations/${nextId}`)).json()).review
      .memoryId,
  ).toBeTruthy();
  await caseInbox(page);
  await page.route("**/api/health", (route) => route.abort());
  await page.getByRole("button", { name: "Refresh API connection" }).click();
  await expect(page.getByRole("alert")).toContainText("Cannot reach");
  await page.unroute("**/api/health");
  await page.getByRole("button", { name: "Refresh API connection" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("template, valid bundle and CSV imports, errors, immutable versions and old results", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Datasets", exact: true }).click();
  const templateDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Get template", exact: true }).click();
  const template = JSON.parse(
    await readFile((await (await templateDownload).path())!, "utf8"),
  );
  expect(Object.keys(template.files)).toHaveLength(9);
  async function importFiles(files: string | string[]) {
    await page
      .getByRole("button", { name: "Import dataset", exact: true })
      .click();
    await page.getByLabel("Dataset files").setInputFiles(files);
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/datasets") &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Validate & import" }).click();
    const response = await responsePromise;
    if (response.ok()) {
      const { dataset } = await response.json();
      await expect(page.locator(".dataset-card.active .dataset-id")).toHaveText(
        dataset.id,
      );
    }
  }
  await importFiles(resolve("data/manual-test/valid-bundle.json"));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
  const oldDatasetId = await page.getByLabel("Active dataset").inputValue();
  const oldRunId = await investigate(page);
  await caseInbox(page);
  await importFiles(resolve("data/manual-test/invalid-missing-payments.json"));
  await expect(page.getByRole("alert")).toContainText("payments.csv");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await importFiles(resolve("data/manual-test/revised-bundle.json"));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
  const revisedId = await page.getByLabel("Active dataset").inputValue();
  expect(revisedId).not.toBe(oldDatasetId);
  const csvDir = resolve("data/manual-test/csv");
  await importFiles((await readdir(csvDir)).map((name) => join(csvDir, name)));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: /^Case inbox/ })
    .click();
  expect(await page.getByLabel("Active dataset").inputValue()).toBe(
    oldDatasetId,
  );
  await expect(page.locator(".case-table tbody tr")).toHaveCount(1);
  expect(
    await (await request.get(`/api/investigations/${oldRunId}`)).json(),
  ).toMatchObject({ datasetId: oldDatasetId, status: "completed" });
});

test("local-model browser flow uses mocked OpenAI, shows failures and cancels waiting calls", async ({
  page,
}, testInfo) => {
  test.setTimeout(90000);
  let responseStatus = 200;
  let waitMs = 0;
  const mock = createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    if (req.headers.authorization !== "Bearer browser-test-token") {
      res.writeHead(401);
      res.end();
      return;
    }
    if (waitMs) await new Promise((done) => setTimeout(done, waitMs));
    if (res.destroyed) return;
    res.writeHead(responseStatus, {
      "Content-Type": "application/json",
      "x-request-id": "mock-browser-request",
    });
    if (responseStatus !== 200) {
      res.end('{"error":"test rejection"}');
      return;
    }
    const context = JSON.parse(JSON.parse(raw).messages[1].content).context;
    res.end(
      JSON.stringify({
        model: "mock-returned-model",
        usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 },
        choices: [
          {
            message: {
              content: JSON.stringify({
                tool: context.availableTools[0],
                reason: "Retrieve required evidence",
                finish: false,
              }),
            },
          },
        ],
      }),
    );
  });
  await new Promise<void>((done) => mock.listen(0, "127.0.0.1", done));
  await mkdir(".local", { recursive: true });
  const storageDir = await mkdtemp(
    join(process.cwd(), ".local", "browser-model-"),
  );
  const reservation = createServer();
  await new Promise<void>((done) => reservation.listen(0, "127.0.0.1", done));
  const port = (reservation.address() as AddressInfo).port;
  await new Promise<void>((done) => reservation.close(() => done()));
  const base = `http://127.0.0.1:${port}`;
  // Run with the app's TS loader; Playwright's loader cannot import its JSON schema.
  const child = spawn(
    process.execPath,
    ["--import", "tsx", "apps/api/src/server.ts"],
    {
      cwd: process.cwd(),
      env: {
        ...process.env,
        FINTRACE_MODE: "local-model",
        FINTRACE_STORAGE_DIR: storageDir,
        PORT: String(port),
        HOST: "127.0.0.1",
        MODEL_PROVIDER: "openai",
        OPENAI_API_KEY: "browser-test-token",
        OPENAI_MODEL: "gpt-4.1-mini",
        OPENAI_BASE_URL: `http://127.0.0.1:${(mock.address() as AddressInfo).port}/v1`,
      },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  try {
    await expect
      .poll(
        async () => {
          try {
            return (
              await fetch(`${base}/api/health`, {
                signal: AbortSignal.timeout(1000),
              })
            ).status;
          } catch {
            return 0;
          }
        },
        { timeout: 15000 },
      )
      .toBe(200);
    const datasets = (await (await fetch(`${base}/api/datasets`)).json())
      .datasets;
    const packet = datasets.find(
      (d: { name: string }) => d.name === "Review packet 001",
    );
    await page.goto(base);
    await expect(
      page.getByText("OpenAI + local data", { exact: true }),
    ).toBeVisible();
    await page.getByLabel("Active dataset").selectOption(packet.id);
    const localRunId = await investigate(page);
    const localRun = await (
      await fetch(`${base}/api/investigations/${localRunId}`)
    ).json();
    expect(localRun).toMatchObject({
      mode: "local-model",
      provider: "openai",
      model: "gpt-4.1-mini",
    });
    expect(localRun.events[0].message).toContain("local snapshots; no Zetaris");
    const health = await (await fetch(`${base}/api/health`)).json();
    expect(health.integrations).toMatchObject({
      zetaris: { status: "not used" },
      storage: { backend: "local immutable files" },
    });
    await expect(page.locator(".investigation-dialog-footer")).toContainText(
      "Reviews do not execute payments",
    );
    await page.screenshot({
      path: testInfo.outputPath("local-model.png"),
      fullPage: true,
    });
    await page.locator("details[aria-label='Activity log'] > summary").click();
    await expect(
      page.getByRole("region", { name: "Run diagnostics" }),
    ).toContainText("mock-browser-request");
    await expect(
      page.getByRole("region", { name: "Run diagnostics" }),
    ).toContainText("input 100");
    const manual = JSON.parse(
      await readFile(resolve("data/openai-manual/01-main-bundle.json"), "utf8"),
    );
    const imported = await fetch(`${base}/api/datasets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(manual),
    });
    const manualId = (await imported.json()).dataset.id;
    await page.reload();
    await caseInbox(page);
    await page.getByLabel("Active dataset").selectOption(manualId);
    await expect(page.locator(".case-table tbody tr")).toHaveCount(8);
    for (const code of [
      "NORMAL",
      "DUP",
      "STALE",
      "MISSING",
      "FEE",
      "FUTURE_EVENT",
      "FUTURE_FEE",
      "CONTEXT_TAIL",
    ]) {
      await page.getByLabel("Search cases").fill(`PAY_DEMO_${code}`);
      await page
        .getByRole("button", {
          name: `Investigate PAY_DEMO_${code}`,
          exact: true,
        })
        .click();
      await waitForCompletedInvestigation(page);
      const titles: Record<string, string> = {
        NORMAL: "The evidence supports normal processing",
        CONTEXT_TAIL: "The evidence supports normal processing",
        DUP: "The invoice was paid more than once",
        STALE: "Superseded vendor instructions caused a return",
        MISSING: "Payment did not reach bank settlement",
        FEE: "Settlement fee has no supporting journal",
        FUTURE_FEE: "Settlement fee has no supporting journal",
        FUTURE_EVENT: "The available evidence does not establish a cause",
      };
      await expect(
        page
          .getByRole("region", { name: "Investigation conclusion" })
          .getByRole("heading", { level: 2 }),
      ).toHaveText(titles[code]);
      await caseInbox(page);
    }
    await page.getByLabel("Search cases").fill("PAY_DEMO_NORMAL");
    await page.locator(".case-table tbody tr").click();
    await investigate(page);
    responseStatus = 401;
    manual.manifest.clearingDays++;
    const changed = await fetch(`${base}/api/datasets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(manual),
    });
    const changedId = (await changed.json()).dataset.id;
    await page.reload();
    await caseInbox(page);
    await page.getByLabel("Active dataset").selectOption(changedId);
    await page.getByLabel("Search cases").fill("PAY_DEMO_NORMAL");
    await page.locator(".case-table tbody tr").click();
    await page
      .getByRole("button", { name: "Update investigation", exact: true })
      .click();
    const failedDialog = page.getByRole("dialog");
    await expect(
      failedDialog.locator(".investigation-dialog-stage"),
    ).toHaveText("Investigation failed", {
      timeout: 15000,
    });
    await expect(
      failedDialog.locator(".investigation-progress-end.has-error"),
    ).toContainText("401");
    await expect(
      failedDialog.getByRole("region", { name: "Investigation conclusion" }),
    ).toHaveCount(0);
    await expect(
      failedDialog.getByRole("button", {
        name: "Review findings",
        exact: true,
      }),
    ).toHaveCount(0);
    const failedId = new URL(page.url()).searchParams.get("investigation")!;
    expect(
      await (await fetch(`${base}/api/investigations/${failedId}`)).json(),
    ).toMatchObject({ status: "failed", outcome: null, actions: [] });
    responseStatus = 200;
    waitMs = 2000;
    await caseInbox(page);
    await page
      .getByRole("button", { name: "Retry investigation", exact: true })
      .click();
    // Opening a failed case resumes its saved record. Only the explicit retry
    // inside the dialog starts a new backend investigation.
    await expect(
      page.getByRole("dialog").locator(".investigation-dialog-stage"),
    ).toHaveText("Investigation failed");
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Retry investigation", exact: true })
      .click();
    // Wait for a real in-flight model call rather than cancelling a local
    // presentation of a run that has already finished.
    await expect
      .poll(
        async () => {
          const currentId = new URL(page.url()).searchParams.get(
            "investigation",
          );
          if (!currentId || currentId === failedId) return false;
          const current = await (
            await fetch(`${base}/api/investigations/${currentId}`)
          ).json();
          const planning = [...current.events]
            .reverse()
            .find(
              (event: { activity?: { kind: string; source?: string } }) =>
                event.activity?.kind === "planning" &&
                event.activity.source === "model",
            );
          return (
            current.status === "running" &&
            planning?.activity.status === "running"
          );
        },
        { timeout: 15000 },
      )
      .toBe(true);
    await page
      .getByRole("button", { name: "Stop investigation", exact: true })
      .click();
    const cancelledDialog = page.getByRole("dialog");
    await expect(
      cancelledDialog.locator(".investigation-dialog-stage"),
    ).toHaveText("Investigation stopped");
    await expect(
      cancelledDialog.getByRole("button", {
        name: "Review findings",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      cancelledDialog.getByRole("region", { name: "Investigation conclusion" }),
    ).toHaveCount(0);
    const id = new URL(page.url()).searchParams.get("investigation")!;
    expect(id).not.toBe(failedId);
    expect(
      await (await fetch(`${base}/api/investigations/${id}`)).json(),
    ).toMatchObject({ status: "cancelled", outcome: null, actions: [] });
  } finally {
    if (child.exitCode === null) {
      const exited = new Promise<void>((done) =>
        child.once("exit", () => done()),
      );
      child.kill();
      await exited;
    }
    mock.closeAllConnections();
    await new Promise<void>((done) => mock.close(() => done()));
  }
});
