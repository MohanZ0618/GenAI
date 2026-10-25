import { test, expect } from "@playwright/test";

test("dataset version shows the complete ID and copies it on click", async ({
  page,
  context,
  request,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const dataset = (await (await request.get("/api/datasets")).json())
    .datasets[0];
  await page.goto("/");
  await page.getByLabel("Active dataset").selectOption(dataset.id);
  const card = page.getByRole("button", {
    name: "Copy dataset version ID",
    exact: true,
  });
  await expect(card.locator("code")).toHaveText(dataset.version);
  await expect(card).toContainText("Click to copy");
  await card.click();
  await expect(card).toContainText("Copied!");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    dataset.version,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await card
      .locator("code")
      .evaluate((el) => el.scrollWidth <= el.clientWidth),
  ).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
