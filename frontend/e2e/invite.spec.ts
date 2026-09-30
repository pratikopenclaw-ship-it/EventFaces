import { expect, test } from "@playwright/test";

import { lastMail, linkIn, login, reset, seedEvent } from "./support";

test("organizer invites by email; invitee registers from the magic link and lands in the event", async ({ page, browser, request }) => {
  await reset(request);
  const event = await seedEvent(request, { join_mode: "invite", synced: false });

  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  await page.getByRole("tab", { name: "Access" }).click();
  await page.getByLabel("Email addresses").fill("dave@example.com");
  await page.getByRole("button", { name: "Send invites" }).click();
  await expect(page.getByText("Sent 1 invite.")).toBeVisible();
  await expect(page.getByRole("cell", { name: "dave@example.com", exact: true })).toBeVisible();

  const link = linkIn(await lastMail(request, "dave@example.com"));
  expect(link).toMatch(/^\/invite\//);
  const guest = await (await browser.newContext()).newPage();
  await guest.goto(link);
  await guest.getByRole("textbox", { name: /^Password/ }).fill("dave-password-1");
  await guest.getByLabel("Confirm password").fill("dave-password-1");
  await guest.getByRole("button", { name: "Create account and join" }).click();
  await expect(guest.getByRole("heading", { name: event.name })).toBeVisible();

  // Reopened after use, the link can't register another account: it only offers the
  // invited address a log-in (accept is idempotent for that user, 410 for anyone else).
  const again = await (await browser.newContext()).newPage();
  await again.goto(link);
  await expect(again.getByText("dave@example.com")).toBeVisible();
  await expect(again.getByRole("main").getByRole("link", { name: "Log in" })).toBeVisible();
  await expect(again.getByRole("button", { name: "Create account and join" })).toHaveCount(0);
});
