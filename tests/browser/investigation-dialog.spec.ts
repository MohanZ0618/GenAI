import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type {
  Case,
  Dataset,
  Investigation,
  RunEvent,
} from "../../packages/contracts/src/index";

type Fixture = { dataset: Dataset; payment: Case; completed: Investigation };
let a: Fixture;
let b: Fixture;

// Capture actual fixture-mode service events and financial evidence. The page's
// requests below are isolated mocks; no model or third-party service is called.
test.beforeAll(async ({ request }) => {
  expect((await (await request.get("/api/health")).json()).mode).toBe(
    "fixture",
  );
  const bundle = JSON.parse(
    await readFile(resolve("data/openai-manual/01-main-bundle.json"), "utf8"),
  );
  bundle.manifest.name = `Dialog fixture ${Date.now()}`;
  const imported = await request.post("/api/datasets", { data: bundle });
  expect(imported.ok()).toBe(true);
  const { dataset } = await imported.json();
  const { cases } = await (
    await request.get(`/api/cases?datasetId=${dataset.id}`)
  ).json();
  const fixtures: Fixture[] = [];
  for (const paymentId of ["PAY_DEMO_DUP", "PAY_DEMO_FEE"]) {
    const payment = cases.find((item: Case) => item.paymentId === paymentId);
    expect(payment).toBeTruthy();
    const response = await request.post("/api/investigations", {
      data: { datasetId: dataset.id, paymentId },
    });
    expect(response.ok()).toBe(true);
    const { id } = await response.json();
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/investigations/${id}`)).json())
            .status,
      )
      .toBe("completed");
    let completed = await (
      await request.get(`/api/investigations/${id}`)
    ).json();
    if (paymentId === "PAY_DEMO_DUP") {
      const draft = await request.post(
        `/api/investigations/${id}/memory-draft`,
        { data: { retry: false } },
      );
      expect(draft.ok()).toBe(true);
      completed = await draft.json();
    }
    fixtures.push({
      dataset,
      payment: {
        ...payment,
        status: "unreviewed",
        investigationId: undefined,
        outcome: null,
      },
      completed,
    });
  }
  [a, b] = fixtures;
});

function running(fixture: Fixture): Investigation {
  const completed = fixture.completed;
  const index = completed.events.findIndex(
    (event) =>
      event.activity?.kind === "tool" && event.activity.status === "running",
  );
  expect(index).toBeGreaterThanOrEqual(0);
  return {
    ...completed,
    status: "running",
    outcome: null,
    findings: [],
    checks: [],
    actions: [],
    evidence: [],
    queries: [],
    events: completed.events.slice(0, index + 1),
    review: undefined,
    memoryDraft: undefined,
  };
}

function terminal(
  previous: Investigation,
  status: "cancelled" | "failed",
): Investigation {
  const started = [...previous.events]
    .reverse()
    .find((event) => event.activity?.status === "running");
  const ending: RunEvent = {
    id: `end-${status}`,
    at: new Date(Date.parse(previous.updatedAt) + 1000).toISOString(),
    type: status,
    message:
      status === "failed"
        ? "Evidence source unavailable"
        : "Cancelled by reviewer",
    tool: started?.tool,
    activity: started?.activity
      ? {
          ...started.activity,
          status,
          summary:
            status === "failed"
              ? "来源查询失败，未生成财务结论。"
              : "调查已停止，未生成财务结论。",
        }
      : undefined,
  };
  return {
    ...previous,
    status,
    outcome: null,
    updatedAt: ending.at,
    events: [...previous.events, ending],
    error: status === "failed" ? "Evidence source unavailable" : undefined,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function pauseClock(page: Page) {
  const at = new Date("2026-10-27T12:00:00Z");
  await page.clock.install({ time: at });
  await page.clock.pauseAt(new Date(at.getTime() + 1000));
}

async function mockWorkspace(
  page: Page,
  options: {
    start?: (fixture: Fixture) => Investigation | Promise<Investigation>;
    saved?: boolean;
    fillers?: number;
    reviewGate?: Promise<void>;
  } = {},
) {
  const runs = new Map(
    [a, b].map((fixture) => [fixture.completed.id, fixture.completed]),
  );
  const failures = new Set<string>();
  const starts: string[] = [];
  const reads: string[] = [];
  const cancels: string[] = [];
  const reviews: Record<string, unknown>[] = [];
  const unexpected: string[] = [];
  const fillers: Case[] = Array.from(
    { length: options.fillers ?? 0 },
    (_, index) => ({
      ...a.payment,
      id: `dialog-filler-${index}`,
      paymentId: `PAY_FILL_${String(index).padStart(3, "0")}`,
      vendor: `Queue vendor ${index}`,
    }),
  );
  const rows = [
    ...fillers,
    ...[a, b].map((fixture) => ({
      ...fixture.payment,
      ...(options.saved
        ? {
            status: "completed",
            investigationId: fixture.completed.id,
            outcome: fixture.completed.outcome,
          }
        : {}),
    })),
  ];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET") {
      if (path === "/api/health")
        return route.fulfill({ json: { mode: "fixture", integrations: {} } });
      if (path === "/api/datasets")
        return route.fulfill({ json: { datasets: [a.dataset] } });
      if (path === `/api/datasets/${a.dataset.id}`)
        return route.fulfill({ json: { dataset: a.dataset } });
      if (path === "/api/cases")
        return route.fulfill({ json: { cases: rows } });
      if (path === "/api/memories")
        return route.fulfill({ json: { memories: [] } });
      const id = path.match(/^\/api\/investigations\/([^/]+)$/)?.[1];
      if (id && runs.has(decodeURIComponent(id))) {
        const runId = decodeURIComponent(id);
        reads.push(runId);
        return failures.has(runId)
          ? route.fulfill({
              status: 503,
              json: { error: "Temporary progress disconnection" },
            })
          : route.fulfill({ json: runs.get(runId) });
      }
    }
    if (request.method() === "POST") {
      if (path === "/api/investigations") {
        const fixture = [a, b].find(
          (item) => item.payment.paymentId === request.postDataJSON().paymentId,
        );
        if (fixture) {
          starts.push(fixture.payment.paymentId);
          const attempt = starts.filter(
            (id) => id === fixture.payment.paymentId,
          ).length;
          const source = await (options.start?.(fixture) ?? running(fixture));
          const next =
            attempt === 1
              ? source
              : {
                  ...source,
                  id: `${fixture.completed.id}-retry-${attempt}`,
                  createdAt: new Date(
                    Date.parse(source.updatedAt) + attempt * 1000,
                  ).toISOString(),
                  updatedAt: new Date(
                    Date.parse(source.updatedAt) + attempt * 1000,
                  ).toISOString(),
                };
          runs.set(next.id, next);
          return route.fulfill({ status: 202, json: next });
        }
      }
      const cancelId = path.match(
        /^\/api\/investigations\/([^/]+)\/cancel$/,
      )?.[1];
      if (cancelId && runs.has(cancelId)) {
        cancels.push(cancelId);
        const cancelled = terminal(runs.get(cancelId)!, "cancelled");
        runs.set(cancelId, cancelled);
        return route.fulfill({ json: cancelled });
      }
      const reviewId = path.match(
        /^\/api\/investigations\/([^/]+)\/review$/,
      )?.[1];
      if (reviewId && runs.has(reviewId)) {
        const body = request.postDataJSON();
        reviews.push(body);
        await options.reviewGate;
        const previous = runs.get(reviewId)!;
        const next = {
          ...previous,
          updatedAt: new Date(
            Date.parse(previous.updatedAt) + 1000,
          ).toISOString(),
          review: {
            decision: body.decision,
            notes: body.notes,
            at: new Date(Date.parse(previous.updatedAt) + 1000).toISOString(),
            ...(body.approveMemory
              ? { memoryId: "approved-dialog-memory" }
              : {}),
          },
        };
        runs.set(reviewId, next);
        return route.fulfill({ json: next });
      }
    }
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({
      status: 405,
      json: { error: "Unexpected request in dialog test" },
    });
  });
  return {
    starts,
    reads,
    cancels,
    reviews,
    unexpected,
    failures,
    publish(next: Investigation) {
      runs.set(next.id, next);
    },
  };
}

const dialog = (page: Page) =>
  page.getByRole("dialog", { name: "Payment investigation", exact: true });
const conclusion = (page: Page) =>
  page.getByRole("region", { name: "Investigation conclusion", exact: true });
const action = (page: Page, fixture: Fixture, name = "Investigate") =>
  page.getByRole("button", {
    name: `${name} ${fixture.payment.paymentId}`,
    exact: true,
  });

test("start opens one dismissible pending window while preserving inbox filters, pagination and scroll", async ({
  page,
}, info) => {
  const pending = deferred<Investigation>();
  const mock = await mockWorkspace(page, {
    fillers: 30,
    start: () => pending.promise,
  });
  await page.goto("/");
  await page.getByLabel("Active dataset").selectOption(a.dataset.id);
  await page.getByLabel("Search cases").fill("PAY_");
  await page.getByRole("button", { name: "Unreviewed", exact: true }).click();
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.locator(".page-range")).toHaveText("26–32 of 32 cases");
  const start = action(page, a);
  await start.scrollIntoViewIfNeeded();
  const scrollBefore = await page.evaluate(() => Math.round(scrollY));
  const tableBefore = await page
    .locator(".case-table")
    .evaluate((element) => element.parentElement!.scrollTop);
  await start.click();
  try {
    await expect(dialog(page)).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await expect(dialog(page)).toContainText("Preparing investigation");
    await expect(conclusion(page)).toHaveCount(0);
    await expect(page.locator(".inbox-page")).toHaveCount(1);
    await expect(
      page.locator(".workspace-page:not(.investigation-detail-embedded)"),
    ).toHaveCount(0);
    await expect(page.locator("main.main-content")).toHaveJSProperty(
      "inert",
      true,
    );
    await expect(
      dialog(page).getByRole("button", { name: "Close investigation" }),
    ).toBeEnabled();
    await page.screenshot({ path: info.outputPath("dialog-pending.png") });
    await dialog(page)
      .getByRole("button", { name: "Close investigation" })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByLabel("Search cases")).toHaveValue("PAY_");
    await expect(page.getByLabel("Active dataset")).toHaveValue(a.dataset.id);
    await expect(
      page.getByRole("button", { name: "Unreviewed", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".page-range")).toHaveText("26–32 of 32 cases");
    await expect
      .poll(() => page.evaluate(() => Math.round(scrollY)))
      .toBe(scrollBefore);
    expect(
      await page
        .locator(".case-table")
        .evaluate((element) => element.parentElement!.scrollTop),
    ).toBe(tableBefore);
    await expect(start).toBeFocused();
    expect(mock.cancels).toEqual([]);
  } finally {
    pending.resolve(a.completed);
  }
  await expect.poll(() => mock.starts.length).toBe(1);
  expect(mock.unexpected).toEqual([]);
});

test("a completed fresh POST types actual recorded steps before revealing and collapsing into the result", async ({
  page,
}, info) => {
  await pauseClock(page);
  const mock = await mockWorkspace(page, {
    start: (fixture) => fixture.completed,
  });
  await page.goto("/");
  await action(page, a).click();
  await expect(dialog(page)).toContainText(
    "Investigation complete. Showing recorded steps…",
  );
  await expect(conclusion(page)).toHaveCount(0);
  await expect(
    dialog(page).getByRole("button", { name: "Review findings", exact: true }),
  ).toHaveCount(0);
  const progress = dialog(page).getByRole("region", {
    name: "Investigation activity",
    exact: true,
  });
  await expect(progress).toHaveAttribute("data-playback-phase", "process");
  await page.clock.runFor(120);
  const partial = progress.locator(".investigation-progress-reason").first();
  await expect(partial).toBeVisible();
  const firstText = await partial.innerText();
  await page.clock.runFor(120);
  expect((await partial.innerText()).length).toBeGreaterThan(firstText.length);
  await expect(conclusion(page)).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("dialog-playback.png") });
  await page.clock.runFor(20000);
  await expect(conclusion(page)).toContainText(a.completed.findings[0].title);
  await expect(
    dialog(page).getByRole("button", { name: "Review findings", exact: true }),
  ).toBeVisible();
  await expect(progress).toHaveAttribute("data-playback-phase", "results");
  await expect(
    progress.getByRole("button", { name: "Expand investigation activity" }),
  ).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(page.locator(".inbox-page")).toHaveCount(1);
  await page.screenshot({
    path: info.outputPath("dialog-results-desktop.png"),
  });
  expect(mock.starts).toEqual([a.payment.paymentId]);
  expect(mock.unexpected).toEqual([]);
});

test("investigating one checked payment opens the same live dialog and retains its selection after completion", async ({
  page,
}) => {
  await pauseClock(page);
  const batchRequests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/") && /batch|queue/.test(path))
      batchRequests.push(`${request.method()} ${path}`);
  });
  const mock = await mockWorkspace(page);
  await page.goto("/");
  const selected = page.getByRole("checkbox", {
    name: `Select ${a.payment.paymentId} in ${a.payment.datasetId}`,
    exact: true,
  });
  await selected.check();
  const start = page.getByRole("button", {
    name: "Investigate selected (1)",
    exact: true,
  });
  await start.click();
  await expect(dialog(page)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(page.locator(".inbox-page")).toHaveCount(1);
  await expect(page.locator(".results-page")).toHaveCount(0);
  await expect(dialog(page)).toContainText("Investigating payment…");
  await expect(conclusion(page)).toHaveCount(0);
  const progress = dialog(page).getByRole("region", {
    name: "Investigation activity",
    exact: true,
  });
  await expect(progress).toHaveAttribute("data-playback-phase", "process");
  await page.clock.runFor(120);
  const reason = progress.locator(".investigation-progress-reason").first();
  await expect(reason).toBeVisible();
  const partial = await reason.innerText();
  await page.clock.runFor(120);
  expect((await reason.innerText()).length).toBeGreaterThan(partial.length);

  mock.publish(a.completed);
  const update = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        `/api/investigations/${a.completed.id}` &&
      response.request().method() === "GET",
  );
  await page.clock.runFor(1500);
  await (await update).finished();
  await expect(dialog(page)).toContainText(
    "Investigation complete. Showing recorded steps…",
  );
  await expect(conclusion(page)).toHaveCount(0);
  await page.clock.runFor(20000);
  await expect(conclusion(page)).toContainText(a.completed.findings[0].title);
  await expect(progress).toHaveAttribute("data-playback-phase", "results");
  await dialog(page)
    .getByRole("button", { name: "Close investigation" })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".inbox-page")).toHaveCount(1);
  await expect(page.locator(".results-page")).toHaveCount(0);
  await expect(selected).toBeChecked();
  await expect(start).toBeEnabled();
  await expect(start).toBeFocused();
  expect(mock.starts).toEqual([a.payment.paymentId]);
  expect(mock.cancels).toEqual([]);
  expect(batchRequests).toEqual([]);
  expect(mock.unexpected).toEqual([]);
});

test("closing pauses text while background polling continues and reopening reuses both run and cursor", async ({
  page,
}) => {
  await pauseClock(page);
  const mock = await mockWorkspace(page);
  await page.goto("/");
  await action(page, a).click();
  await expect(dialog(page)).toContainText("Investigating payment…");
  await page.clock.runFor(160);
  const reason = dialog(page).locator(".investigation-progress-reason").first();
  const before = await reason.innerText();
  await dialog(page)
    .getByRole("button", { name: "Close investigation" })
    .click();
  // Let each network response settle before advancing the next poll tick; a
  // single large clock jump correctly skips overlapping requests for one run.
  for (let tick = 0; tick < 2; tick++) {
    const response = page.waitForResponse(
      (reply) =>
        new URL(reply.url()).pathname ===
          `/api/investigations/${a.completed.id}` &&
        reply.request().method() === "GET",
    );
    await page.clock.runFor(1500);
    await (await response).finished();
    await page.evaluate(() => Promise.resolve());
    await expect
      .poll(() => mock.reads.filter((id) => id === a.completed.id).length)
      .toBeGreaterThanOrEqual(tick + 1);
  }
  await expect
    .poll(() => mock.reads.filter((id) => id === a.completed.id).length)
    .toBeGreaterThanOrEqual(2);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await action(page, a, "View run").click();
  await expect(
    dialog(page).locator(".investigation-progress-reason").first(),
  ).toHaveText(before);
  await page.clock.runFor(100);
  expect(
    (
      await dialog(page)
        .locator(".investigation-progress-reason")
        .first()
        .innerText()
    ).length,
  ).toBeGreaterThan(before.length);
  expect(mock.starts).toEqual([a.payment.paymentId]);
  expect(mock.cancels).toEqual([]);
  expect(mock.unexpected).toEqual([]);
});

test("a late response for closed A cannot replace the visible B investigation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const slow = deferred<Investigation>();
  const mock = await mockWorkspace(page, {
    start: (fixture) =>
      fixture.payment.id === a.payment.id ? slow.promise : fixture.completed,
  });
  await page.goto("/");
  await action(page, a).click();
  await expect(dialog(page)).toContainText("Preparing investigation");
  await dialog(page)
    .getByRole("button", { name: "Close investigation" })
    .click();
  await action(page, b).click();
  await expect(conclusion(page)).toBeVisible();
  slow.resolve(a.completed);
  await expect(dialog(page).locator(".modal-heading")).toContainText(
    b.payment.paymentId,
  );
  await expect(dialog(page).locator(".modal-heading")).not.toContainText(
    a.payment.paymentId,
  );
  await expect(conclusion(page)).toContainText(b.completed.findings[0].title);
  await expect(page.getByRole("dialog")).toHaveCount(1);
  expect(mock.starts).toEqual([a.payment.paymentId, b.payment.paymentId]);
  expect(mock.unexpected).toEqual([]);
});

test("saved results use GET directly, dialog deep links survive refresh and old links keep the standalone page", async ({
  page,
}) => {
  const mock = await mockWorkspace(page, { saved: true });
  await page.goto("/");
  await action(page, a, "View result").click();
  await expect(conclusion(page)).toBeVisible();
  await expect(dialog(page)).not.toContainText(
    "Investigation complete. Showing recorded steps…",
  );
  await expect(page).toHaveURL(
    new RegExp(`investigation=${a.completed.id}.*view=dialog`),
  );
  await page.reload();
  await expect(dialog(page)).toBeVisible();
  await expect(conclusion(page)).toBeVisible();
  await expect(page.locator(".inbox-page")).toHaveCount(1);
  await page.goto(`/?investigation=${a.completed.id}`);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.locator(".workspace-page:not(.investigation-detail-embedded) h1"),
  ).toHaveText(a.payment.paymentId);
  await expect(page.locator(".inbox-page")).toHaveCount(0);
  expect(mock.starts).toEqual([]);
  expect(mock.unexpected).toEqual([]);
});

test("a saved investigation expands its recorded process without replaying or requesting another run", async ({
  page,
}) => {
  await pauseClock(page);
  const requests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) requests.push(`${request.method()} ${path}`);
  });
  const mock = await mockWorkspace(page, { saved: true });
  await page.goto("/");
  await action(page, a, "View result").click();
  await expect(conclusion(page)).toContainText(a.completed.findings[0].title);
  const progress = dialog(page).getByRole("region", {
    name: "Investigation activity",
    exact: true,
  });
  await expect(progress).toHaveAttribute("data-playback-phase", "results");
  const readsBefore = [...mock.reads];
  const requestsBefore = [...requests];
  await expect(
    dialog(page).getByRole("button", { name: /replay/i }),
  ).toHaveCount(0);
  await expect(
    progress.getByRole("button", { name: "Expand investigation activity" }),
  ).toHaveAttribute("aria-expanded", "false");
  await progress
    .getByRole("button", { name: "Expand investigation activity" })
    .click();
  const records = a.completed.events.filter(
    (event) =>
      event.activity?.kind === "tool" &&
      event.activity.status === "completed" &&
      event.activity.reason &&
      event.activity.summary,
  );
  expect(records.length).toBeGreaterThan(0);
  for (const recorded of records) {
    const step = progress.locator(
      `[data-activity-id="${recorded.activity!.id}"]`,
    );
    await expect(step).toContainText(recorded.tool!);
    await expect(step).toContainText(recorded.activity!.reason!);
    await expect(step).toContainText(recorded.activity!.summary!);
  }
  await expect(conclusion(page)).toContainText(a.completed.findings[0].title);
  await expect(progress).toHaveAttribute("data-playback-phase", "results");
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await page.clock.runFor(1000);
  expect(mock.reads).toEqual(readsBefore);
  expect(mock.starts).toEqual([]);
  expect(requests).toEqual(requestsBefore);
  expect(mock.unexpected).toEqual([]);
});

test("connection recovery, failed snapshots and explicit stop preserve uncertainty and reopening never retries automatically", async ({
  page,
}) => {
  await pauseClock(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const mock = await mockWorkspace(page);
  await page.goto("/");
  await action(page, a).click();
  await expect(dialog(page)).toContainText("Investigating payment…");
  mock.failures.add(a.completed.id);
  await page.clock.runFor(1500);
  await expect(dialog(page)).toContainText("Temporary progress disconnection");
  await expect(conclusion(page)).toHaveCount(0);
  mock.failures.delete(a.completed.id);
  mock.publish(terminal(running(a), "failed"));
  await page.clock.runFor(1500);
  await expect(dialog(page)).toContainText("Investigation failed");
  await expect(dialog(page)).not.toContainText(
    "Temporary progress disconnection",
  );
  await expect(conclusion(page)).toHaveCount(0);
  await dialog(page)
    .getByRole("button", { name: "Close investigation" })
    .click();
  await action(page, a, "Retry investigation").click();
  await expect(dialog(page)).toContainText("Investigation failed");
  expect(mock.starts).toEqual([a.payment.paymentId]);
  await dialog(page)
    .getByRole("button", { name: "Retry investigation" })
    .click();
  await expect(dialog(page)).toContainText("Investigating payment…");
  expect(mock.starts).toEqual([a.payment.paymentId, a.payment.paymentId]);
  await dialog(page)
    .getByRole("button", { name: "Close investigation" })
    .click();
  await action(page, b).click();
  await expect(dialog(page)).toContainText("Investigating payment…");
  await dialog(page)
    .getByRole("button", { name: "Stop investigation", exact: true })
    .click();
  await expect(dialog(page)).toContainText("Investigation stopped");
  await expect(conclusion(page)).toHaveCount(0);
  await dialog(page)
    .getByRole("button", { name: "Close investigation" })
    .click();
  await action(page, b, "Retry investigation").click();
  await expect(dialog(page)).toContainText("Investigation stopped");
  expect(mock.starts).toEqual([
    a.payment.paymentId,
    a.payment.paymentId,
    b.payment.paymentId,
  ]);
  expect(mock.cancels).toEqual([b.completed.id]);
  expect(mock.unexpected).toEqual([]);
});

test("evidence and review-memory subviews share one focus trap and preserve notes during evidence navigation", async ({
  page,
}) => {
  const saving = deferred<void>();
  const mock = await mockWorkspace(page, {
    saved: true,
    reviewGate: saving.promise,
  });
  await page.goto("/");
  await action(page, a, "View result").click();
  const record = a.completed.evidence[0];
  const evidence = dialog(page).getByRole("button", {
    name: `View evidence ${record.id}`,
    exact: true,
  });
  await evidence.click();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(
    page.getByRole("region", { name: "Original record", exact: true }),
  ).toContainText(record.recordId);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("region", { name: "Original record", exact: true }),
  ).toHaveCount(0);
  await expect(evidence).toBeFocused();
  await dialog(page)
    .getByRole("button", { name: "Review memory suggestion", exact: true })
    .click();
  const review = page.getByRole("dialog", {
    name: "Review the investigation",
    exact: true,
  });
  await expect(review).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await review
    .getByLabel("Review notes")
    .fill("Confirmed allocations and bank disbursements.");
  if (
    a.completed.memoryDraft?.status === "ready" &&
    a.completed.memoryDraft.evidenceIds?.length
  ) {
    await review
      .getByRole("link", {
        name: a.completed.memoryDraft.evidenceIds[0],
        exact: true,
      })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await expect(
      page.getByRole("region", { name: "Original record", exact: true }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(
      page
        .getByRole("dialog", { name: "Review the investigation", exact: true })
        .getByLabel("Review notes"),
    ).toHaveValue("Confirmed allocations and bank disbursements.");
  }
  const consent = review.getByLabel("Approve a reusable memory");
  await expect(consent).not.toBeChecked();
  await review
    .getByRole("button", { name: "Save human review", exact: true })
    .click();
  try {
    await expect(
      review.getByRole("button", { name: "Close investigation" }),
    ).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(1);
  } finally {
    saving.resolve();
  }
  await expect(dialog(page)).toBeVisible();
  await expect(dialog(page).locator(".review-receipt")).toContainText(
    "Confirmed allocations and bank disbursements.",
  );
  expect(mock.reviews[0]).toMatchObject({
    decision: "accepted",
    approveMemory: false,
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(mock.starts).toEqual([]);
  expect(mock.unexpected).toEqual([]);
});

test("the mobile dialog is full-screen, traps focus and reveals saved results without motion", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const mock = await mockWorkspace(page, {
    start: (fixture) => fixture.completed,
  });
  await page.goto("/");
  await action(page, a).click();
  const modal = dialog(page);
  await expect(conclusion(page)).toBeVisible();
  const bounds = await modal.boundingBox();
  expect(bounds).toEqual({ x: 0, y: 0, width: 390, height: 844 });
  // A non-overflowing outer dialog is insufficient: the conclusion must keep
  // a readable line width instead of being squeezed beside the action panel.
  const minimumReadingWidth = page.viewportSize()!.width * 0.65;
  const copyBounds = await conclusion(page)
    .locator(".detail-outcome-copy")
    .boundingBox();
  const titleBounds = await conclusion(page)
    .getByRole("heading", { level: 2 })
    .boundingBox();
  const actionBounds = await conclusion(page)
    .locator(".detail-next-action")
    .boundingBox();
  expect(copyBounds).not.toBeNull();
  expect(titleBounds).not.toBeNull();
  expect(actionBounds).not.toBeNull();
  expect(copyBounds!.width).toBeGreaterThanOrEqual(minimumReadingWidth);
  expect(titleBounds!.width).toBeGreaterThanOrEqual(minimumReadingWidth);
  expect(actionBounds!.width).toBeGreaterThanOrEqual(minimumReadingWidth);
  expect(actionBounds!.y).toBeGreaterThanOrEqual(
    copyBounds!.y + copyBounds!.height - 1,
  );
  expect(actionBounds!.x).toBeGreaterThanOrEqual(0);
  expect(actionBounds!.x + actionBounds!.width).toBeLessThanOrEqual(
    page.viewportSize()!.width,
  );
  await expect(modal).toHaveCSS("border-radius", "0px");
  await expect(modal).toHaveCSS("animation-name", "none");
  const close = modal.getByRole("button", { name: "Close investigation" });
  await close.focus();
  await page.keyboard.press("Shift+Tab");
  expect(
    await modal.evaluate((element) => element.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await expect(page.locator("main.main-content")).toHaveJSProperty(
    "inert",
    true,
  );
  await expect
    .poll(() =>
      modal.evaluate((element) => element.scrollWidth <= element.clientWidth),
    )
    .toBe(true);
  await modal.locator(".investigation-dialog-scroll").evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({ path: info.outputPath("dialog-results-mobile.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(mock.starts).toEqual([a.payment.paymentId]);
  expect(mock.unexpected).toEqual([]);
});
