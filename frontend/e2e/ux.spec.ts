import { expect, test, type Page } from "@playwright/test";

import { lastMail, linkIn, login, reset, seedEvent } from "./support";

async function noSidewaysScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "page scrolls sideways").toBeLessThanOrEqual(1);
}

// UX-001, UX-004, UX-006: phone layouts.
test("@xb admin tabs fit the screen, every tab is reachable, and no 'No date' noise", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false });
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  await expect(page.getByRole("heading", { name: event.name })).toBeVisible();
  await noSidewaysScroll(page);
  for (const tab of ["Settings", "Access", "Members", "Photos", "Moderation", "Match quality"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
    await noSidewaysScroll(page);
  }
  await expect(page.getByText("No date")).toHaveCount(0);
  await expect(page.getByText("(Phase 2)")).toHaveCount(0); // UX-005
});

test("@xb account is reachable from the header on every screen size, with log out", async ({ page, request }) => {
  await reset(request);
  await seedEvent(request, { synced: false });
  await login(page, "alice@e2e.test");
  await page.goto("/events");
  await noSidewaysScroll(page);
  await expect(page.getByRole("link", { name: "Find my photos" }).or(page.getByText("Find my photos →")).first()).toBeVisible(); // UX-010
  await page.getByRole("navigation").getByRole("link", { name: /Account|alice@e2e\.test/ }).click();
  await expect(page.getByRole("heading", { name: "Your account" })).toBeVisible();
  await page.getByRole("main").getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("navigation").getByRole("link", { name: "Log in" })).toBeVisible();
});

// UX-003: scanning the QR code as a new person must end at the event, not at an empty "My events".
test("QR join link survives sign-up and email verification", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false });
  await page.goto(`/join/${event.slug}?code=${event.code}`);
  await expect(page.getByRole("heading", { name: "Log in to join the event" })).toBeVisible();
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page.getByRole("heading", { name: "Create an account to join the event" })).toBeVisible();
  await page.getByLabel("Email").fill("qr-newcomer@example.com");
  await page.getByRole("textbox", { name: /^Password/ }).fill("qr-newcomer-pass-1");
  await page.getByLabel("Confirm password").fill("qr-newcomer-pass-1");
  await page.getByRole("checkbox", { name: /I accept the Terms of Use/ }).check();
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByText("it will bring you back to the event")).toBeVisible();

  await page.goto(linkIn(await lastMail(request, "qr-newcomer@example.com")));
  await page.getByRole("link", { name: "Continue to the event →" }).click();
  await expect(page.getByRole("heading", { name: "Log in to join the event" })).toBeVisible();
  await page.getByLabel("Email").fill("qr-newcomer@example.com");
  await page.getByLabel("Password").fill("qr-newcomer-pass-1");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(new RegExp(`/join/${event.slug}`));
  await expect(page.getByLabel("Access code")).toHaveValue(event.code); // code carried all the way
  await page.getByRole("button", { name: "Join event" }).click();
  await expect(page.getByRole("heading", { name: event.name })).toBeVisible();
});
