import { expect, test, type Locator, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type {
  Case,
  Dataset,
  Investigation,
} from "../../packages/contracts/src/index";

let dataset: Dataset;
let payment: Case;
let recorded: Investigation;

// Obtain actual service records, then isolate every browser request. No model
// request or user-workspace mutation occurs in these scrolling tests.
test.beforeAll(async ({ request }) => {
  expect((await (await request.get("/api/health")).json()).mode).toBe(
    "fixture",
  );
  const bundle = JSON.parse(
    await readFile(resolve("data/openai-manual/01-main-bundle.json"), "utf8"),
  );
  bundle.manifest.name = `Follow activity fixture ${Date.now()}`;
  const imported = await request.post("/api/datasets", { data: bundle });
  expect(imported.ok()).toBe(true);
  ({ dataset } = await imported.json());
  const { cases } = await (
    await request.get(`/api/cases?datasetId=${dataset.id}`)
  ).json();
  payment = cases.find(
    (item: Case) => item.paymentId === "PAY_DEMO_FUTURE_EVENT",
  );
  expect(payment).toBeTruthy();
  const started = await request.post("/api/investigations", {
    data: { datasetId: dataset.id, paymentId: payment.paymentId },
  });
  expect(started.ok()).toBe(true);
  const { id } = await started.json();
  await expect
    .poll(async () => {
      recorded = await (await request.get(`/api/investigations/${id}`)).json();
      return recorded.status;
    })
    .toBe("completed");
  expect(recorded.queries.length).toBeGreaterThanOrEqual(5);
  payment = { ...payment, status: "unreviewed", investigationId: undefined };
});

function runningThrough(toolCount: number): Investigation {
  let seen = 0;
  const last = recorded.events.findIndex(
    (event) =>
      event.activity?.kind === "tool" &&
      event.activity.status === "completed" &&
      ++seen === toolCount,
  );
  expect(last).toBeGreaterThanOrEqual(0);
  const events = recorded.events.slice(0, last + 1);
  const ids = new Set(
    events.flatMap((event) => event.activity?.evidenceIds ?? []),
  );
  return {
    ...recorded,
    status: "running",
    outcome: null,
    updatedAt: new Date(
      Date.parse(recorded.updatedAt) + toolCount * 1000,
    ).toISOString(),
    events,
    findings: [],
    checks: [],
    actions: [],
    evidence: recorded.evidence.filter((item) => ids.has(item.id)),
    queries: recorded.queries.slice(0, toolCount),
  };
}

async function mockWorkspace(page: Page, running = false) {
  let snapshot = running ? runningThrough(1) : recorded;
  const unexpected: string[] = [];
  let starts = 0;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET") {
      if (path === "/api/health")
        return route.fulfill({ json: { mode: "fixture", integrations: {} } });
      if (path === "/api/datasets")
        return route.fulfill({ json: { datasets: [dataset] } });
      if (path === `/api/datasets/${dataset.id}`)
        return route.fulfill({ json: { dataset } });
      if (path === "/api/cases")
        return route.fulfill({ json: { cases: [payment] } });
      if (path === "/api/memories")
        return route.fulfill({ json: { memories: [] } });
      if (path === `/api/investigations/${recorded.id}`)
        return route.fulfill({ json: snapshot });
    }
    if (request.method() === "POST" && path === "/api/investigations") {
      starts++;
      return route.fulfill({ status: 202, json: snapshot });
    }
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({
      status: 405,
      json: { error: "Unexpected request" },
    });
  });
  return {
    unexpected,
    starts: () => starts,
    publishTools(count: number) {
      snapshot = runningThrough(count);
    },
  };
}

async function pauseClock(page: Page) {
  const at = new Date("2026-10-27T12:00:00Z");
  await page.clock.install({ time: at });
  await page.clock.pauseAt(new Date(at.getTime() + 1000));
}

const dialog = (page: Page) => page.locator(".investigation-dialog");
const scroll = (page: Page) =>
  dialog(page).locator(".investigation-dialog-scroll");
const activity = (page: Page) =>
  dialog(page).getByRole("region", {
    name: "Investigation activity",
    exact: true,
  });
const conclusion = (page: Page) =>
  dialog(page).getByRole("region", {
    name: "Investigation conclusion",
    exact: true,
  });

async function metrics(container: Locator) {
  return container.evaluate((element) => ({
    top: element.scrollTop,
    maximum: element.scrollHeight - element.clientHeight,
    gap: element.scrollHeight - element.clientHeight - element.scrollTop,
  }));
}

async function expectAtLatest(page: Page) {
  // ResizeObserver is native; its callback may enqueue a (mocked) animation
  // frame after runFor returns. Keep advancing that frame while waiting, just
  // as a visible tab does, instead of freezing pending scroll work.
  await expect
    .poll(async () => {
      await page.clock.runFor(32);
      return (await metrics(scroll(page))).gap;
    })
    .toBeLessThan(4);
}

async function openFresh(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Start investigation", exact: true })
    .click();
  await expect(dialog(page)).toBeVisible();
  await expect(
    page.getByRole("dialog", { name: "Payment investigation", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Replay investigation", exact: true }),
  ).toHaveCount(0);
}

async function growUntilOverflow(page: Page) {
  for (let count = 0; count < 10; count++) {
    await page.clock.runFor(450);
    await page.clock.runFor(64);
    if ((await metrics(scroll(page))).maximum > 150) break;
  }
  expect((await metrics(scroll(page))).maximum).toBeGreaterThan(150);
  await expect(activity(page)).toHaveAttribute(
    "data-playback-phase",
    "process",
  );
  await expect(scroll(page)).toHaveAttribute("data-following", "true");
  await expectAtLatest(page);
}

test("English recorded activity follows the latest text, pauses for reading, and resumes at the bottom", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1100, height: 620 });
  await pauseClock(page);
  const mock = await mockWorkspace(page);
  await openFresh(page);
  await expect(dialog(page)).toContainText(
    "Investigation complete. Showing recorded steps…",
  );
  await page.clock.runFor(240);
  await page.screenshot({
    path: info.outputPath("activity-controls-desktop.png"),
  });
  await growUntilOverflow(page);
  const title = await activity(page)
    .locator(".investigation-progress-title strong")
    .boundingBox();
  const chevron = await activity(page)
    .locator(".investigation-progress-chevron")
    .boundingBox();
  expect(title).not.toBeNull();
  expect(chevron).not.toBeNull();
  expect(chevron!.x - title!.x - title!.width).toBeGreaterThanOrEqual(0);
  expect(chevron!.x - title!.x - title!.width).toBeLessThanOrEqual(12);
  expect(await page.evaluate(() => scrollY)).toBe(0);

  await scroll(page).hover();
  const following = await metrics(scroll(page));
  await page.mouse.wheel(0, -240);
  await page.clock.runFor(80);
  await expect(scroll(page)).toHaveAttribute("data-following", "false");
  await expect
    .poll(async () => (await metrics(scroll(page))).top)
    .toBeLessThan(following.top - 40);
  const readingTop = (await metrics(scroll(page))).top;
  const textBefore = await activity(page).innerText();
  await page.clock.runFor(550);
  expect((await activity(page).innerText()).length).toBeGreaterThan(
    textBefore.length,
  );
  expect((await metrics(scroll(page))).top).toBeCloseTo(readingTop, 0);
  await expect(
    dialog(page).getByRole("button", { name: "Jump to latest", exact: true }),
  ).toBeVisible();

  await scroll(page).evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await page.clock.runFor(64);
  await expect(scroll(page)).toHaveAttribute("data-following", "true");
  await page.clock.runFor(500);
  await expectAtLatest(page);
  expect(await page.evaluate(() => scrollY)).toBe(0);
  // Only application chrome and generated activity are checked here; original
  // evidence values are intentionally preserved when a source is multilingual.
  expect(await dialog(page).innerText()).not.toMatch(/[\u3400-\u9fff]/);
  await page.screenshot({
    path: info.outputPath("activity-follow-desktop.png"),
  });

  await page.clock.runFor(20000);
  await expect(
    conclusion(page).getByRole("heading", { level: 2 }),
  ).toBeInViewport();
  await scroll(page).evaluate((element) => {
    element.scrollTop = 120;
  });
  const resultTop = (await metrics(scroll(page))).top;
  await page.clock.runFor(1500);
  expect((await metrics(scroll(page))).top).toBeCloseTo(resultTop, 0);
  const table = dialog(page).locator(".detail-evidence-table");
  await expect(table).toBeVisible();
  await dialog(page)
    .getByRole("button", { name: "Collapse evidence", exact: true })
    .click();
  await expect(table).toBeHidden();
  await dialog(page)
    .getByRole("button", { name: "Expand evidence", exact: true })
    .click();
  await expect(table).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Replay investigation", exact: true }),
  ).toHaveCount(0);
  expect(mock.starts()).toBe(1);
  expect(mock.unexpected).toEqual([]);
});

test("opening evidence during playback suspends following and returning restores the reading position", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1100, height: 620 });
  await pauseClock(page);
  const mock = await mockWorkspace(page);
  await openFresh(page);
  await growUntilOverflow(page);
  await scroll(page).hover();
  await page.mouse.wheel(0, -1000);
  await page.clock.runFor(80);
  await expect(scroll(page)).toHaveAttribute("data-following", "false");
  const evidenceGroup = activity(page)
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: /^Evidence \(\d+\)$/ }) })
    .first();
  await evidenceGroup.locator("summary").click();
  const evidenceId = recorded.events.find(
    (event) =>
      event.activity?.kind === "tool" && event.activity.status === "completed",
  )!.activity!.evidenceIds![0];
  const firstEvidence = activity(page).getByRole("button", {
    name: `View evidence ${evidenceId}`,
    exact: true,
  });
  await expect(evidenceGroup).toHaveAttribute("open", "");
  await evidenceGroup.locator("summary").click();
  await expect(firstEvidence).toBeHidden();
  await evidenceGroup.locator("summary").click();
  await firstEvidence.click();
  await expect(
    dialog(page).getByRole("region", { name: "Original record", exact: true }),
  ).toBeVisible();
  const evidenceTop = (await metrics(scroll(page))).top;
  await page.clock.runFor(400);
  expect((await metrics(scroll(page))).top).toBeCloseTo(evidenceTop, 0);
  await page.keyboard.press("Escape");
  await expect(activity(page)).toBeVisible();
  await expect(firstEvidence).toBeFocused();
  const restored = (await metrics(scroll(page))).top;
  await page.clock.runFor(400);
  expect((await metrics(scroll(page))).top).toBeCloseTo(restored, 0);
  await expect(scroll(page)).toHaveAttribute("data-following", "false");
  expect(await page.evaluate(() => scrollY)).toBe(0);
  expect(mock.unexpected).toEqual([]);
});

test("desktop activity follows newly polled records inside the investigation window", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1100, height: 620 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await pauseClock(page);
  const mock = await mockWorkspace(page, true);
  await openFresh(page);
  await expect(dialog(page)).toContainText("Investigating payment…");
  const completedTools = recorded.events.filter(
    (event) =>
      event.activity?.kind === "tool" && event.activity.status === "completed",
  );
  for (let count = 2; count <= completedTools.length; count++) {
    mock.publishTools(count);
    const response = page.waitForResponse(
      (item) =>
        new URL(item.url()).pathname === `/api/investigations/${recorded.id}`,
    );
    await page.clock.runFor(1500);
    await (await response).finished();
    await expect(
      activity(page).locator(
        `[data-activity-id="${completedTools[count - 1].activity!.id}"]`,
      ),
    ).toHaveAttribute("data-status", "completed");
    await page.clock.runFor(64);
  }
  expect((await metrics(scroll(page))).maximum).toBeGreaterThan(150);
  await expect(scroll(page)).toHaveAttribute("data-following", "true");
  await expectAtLatest(page);
  await expect(dialog(page)).toHaveCSS("animation-name", "none");
  const bounds = await dialog(page).boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(1040);
  expect(bounds!.height).toBeLessThanOrEqual(620 * 0.9);
  expect(await page.evaluate(() => scrollY)).toBe(0);
  expect(await dialog(page).innerText()).not.toMatch(/[\u3400-\u9fff]/);
  await page.screenshot({
    path: info.outputPath("activity-follow-desktop-polling.png"),
  });
  expect(mock.starts()).toBe(1);
  expect(mock.unexpected).toEqual([]);
});
