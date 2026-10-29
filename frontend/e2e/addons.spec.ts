import { expect, test } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

// Ordering a professional edit of one's own photos in TEST MODE: results → select →
// add-on checkout (declined, then paid) → confirmation; the paid checkout stays closed.
test("@xb order a professional edit of a matched photo with a test card", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });

  // Nothing selected: no order button in the toolbar (the viewer offers it per photo).
  await expect(page.getByRole("button", { name: /^Order editing/ })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Select photo" }).first().check();
  await page.getByRole("button", { name: "Order editing (1)" }).click();

  await expect(page).toHaveURL(/\/checkout\/addon\/fcs_/);
  await expect(page.getByText("TEST MODE")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Payment" })).toBeVisible();
  await expect(page.getByText("Professional photo edit · 1 photo")).toBeVisible();
  await expect(page.getByRole("img", { name: "Photo 1 of 1" })).toBeVisible();
  const checkoutUrl = page.url();

  await page.getByLabel("Expiry").fill("12/30");
  await page.getByLabel("CVC").fill("123");
  await page.getByRole("button", { name: /4000 0000 0000 0002/ }).click();
  await page.getByRole("button", { name: /^Pay / }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("declined");

  await page.getByRole("button", { name: /4242 4242 4242 4242/ }).click();
  await page.getByRole("button", { name: /^Pay / }).click();
  await expect(page.getByRole("heading", { name: "Order paid" })).toBeVisible();
  await page.getByRole("link", { name: "Back to the event" }).click();
  await expect(page).toHaveURL(`/events/${event.id}`);

  // A paid checkout can't be paid again.
  await page.goto(checkoutUrl);
  await expect(page.getByText("This checkout is closed (paid).")).toBeVisible();
});

test("@xb the viewer orders an edit of the photo on screen", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Open photo" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Order editing" }).click();
  await expect(page).toHaveURL(/\/checkout\/addon\/fcs_/);
  await expect(page.getByText("Professional photo edit · 1 photo")).toBeVisible();
});

test("an add-on checkout that isn't yours shows not found", async ({ page, request }) => {
  await reset(request);
  await login(page, "alice@e2e.test");
  await page.goto("/checkout/addon/fcs_not-a-real-session");
  await expect(page.getByText("This checkout doesn't exist or isn't yours.")).toBeVisible();
});
