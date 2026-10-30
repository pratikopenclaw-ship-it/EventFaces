import { expect, test } from "@playwright/test";

import { API, captureThreeShots, fakeCamera, giveConsent, lastMail, login, reset, seedEvent } from "./support";

// New-photo alerts: a search subscribes; new photos with faces show a banner on the event
// page and (after the quiet window) an email whose link stops alerts without logging in.

const BANNER = "New photos were added since your last scan";
const EVENT_TOGGLE = /Tell me when new photos are added/;

test("after a search, new photos show a banner and an email that can stop the alerts", async ({ page, browser, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(BANNER)).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: EVENT_TOGGLE })).toBeChecked();

  // The organizer adds a photo with faces.
  expect((await request.post(`${API}/__e2e/event/${event.id}/new-drive-photo`, { timeout: 120_000 })).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText(BANNER)).toBeVisible();
  await page.getByRole("button", { name: "Scan again" }).click();
  await expect(page.getByText(BANNER)).toHaveCount(0);

  // One beat of the alert task: the email names the event and carries the unsubscribe link.
  const sent = await (await request.post(`${API}/__e2e/run-photo-alerts`)).json();
  expect(sent.sent).toBe(1);
  const mail = await lastMail(request, "alice@e2e.test");
  expect(mail.subject).toBe(`New photos from ${event.name}`);
  const link = mail.body.match(/https?:\/\/\S+\/unsubscribe\?token=\S+/)?.[0];
  expect(link).toBeTruthy();
  const path = new URL(link!).pathname + new URL(link!).search;

  // The link works logged out, and opening it changes nothing until a button is pressed.
  const stranger = await (await browser.newContext()).newPage();
  await stranger.goto(path);
  await expect(stranger.getByRole("button", { name: "Stop alerts for this event" })).toBeVisible();
  await expect(stranger.getByRole("button", { name: "Stop all new-photo alerts" })).toBeVisible();
  await page.goto(`/events/${event.id}`);
  await expect(page.getByRole("checkbox", { name: EVENT_TOGGLE })).toBeChecked();

  await stranger.getByRole("button", { name: "Stop alerts for this event" }).click();
  await expect(stranger.getByText("You won't get new-photo alerts for this event any more.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("checkbox", { name: EVENT_TOGGLE })).not.toBeChecked();

  // ...and the attendee can turn them back on.
  await page.getByRole("checkbox", { name: EVENT_TOGGLE }).check();
  await page.reload();
  await expect(page.getByRole("checkbox", { name: EVENT_TOGGLE })).toBeChecked();
});

test("someone who never searched sees no alert toggle", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await login(page, "bob@e2e.test");
  await page.goto(`/events/${event.id}`);
  await expect(page.getByRole("heading", { name: event.name })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: EVENT_TOGGLE })).toHaveCount(0);
  await expect(page.getByText(BANNER)).toHaveCount(0);
});

test("the account-wide alert setting persists", async ({ page, request }) => {
  await reset(request);
  await login(page, "alice@e2e.test");
  await page.goto("/account");
  const toggle = page.getByRole("checkbox", { name: /new photos are added to events I searched/ });
  await expect(toggle).toBeChecked();
  await toggle.uncheck();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(toggle).not.toBeChecked();
});

test("the organizer setting persists", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false });
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  const toggle = page.getByRole("checkbox", { name: /Tell attendees about new photos/ });
  await expect(toggle).toBeChecked();
  await toggle.uncheck();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(toggle).not.toBeChecked();
});

test("an unknown unsubscribe link answers the same as a real one", async ({ page, request }) => {
  await reset(request);
  await page.goto("/unsubscribe?token=not-a-real-token");
  await page.getByRole("button", { name: "Stop all new-photo alerts" }).click();
  await expect(page.getByText("You won't get any new-photo alerts any more.")).toBeVisible();
});
