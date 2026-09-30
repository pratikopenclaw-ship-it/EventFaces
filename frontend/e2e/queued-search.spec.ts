import { expect, test } from "@playwright/test";

import { API, captureThreeShots, fakeCamera, giveConsent, lastMail, login, reset, seedEvent } from "./support";

// When every face-work slot is busy, the search is queued in memory and the user is
// told they'll be notified; the page (and an email) deliver the results later.
test("a busy server queues the search, then shows results and emails the user", async ({ page, request }) => {
  test.setTimeout(180_000);
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);

  expect((await request.post(`${API}/__e2e/face-slots/hold`)).ok()).toBeTruthy();
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: "You're in the queue" })).toBeVisible({ timeout: 60_000 });

  // "My events" shows the queued search too.
  const events = await page.context().newPage();
  await events.goto("/events");
  await expect(events.getByText("Search queued")).toBeVisible();

  // Capacity frees up: the worker runs the search; the open page picks up the results.
  expect((await request.post(`${API}/__e2e/face-slots/release`)).ok()).toBeTruthy();
  await expect(page.getByRole("heading", { name: "Your photos" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("button", { name: "Open photo" }).first()).toBeVisible();

  const mail = await lastMail(request, "alice@e2e.test");
  expect(mail.subject).toContain("ready");
  expect(mail.body).toContain(`/events/${event.id}`);

  await events.reload();
  await expect(events.getByText("Photos ready")).toBeVisible();
});
