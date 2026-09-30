import { expect, test } from "@playwright/test";

import { API, login, reset, seedEvent } from "./support";

test("a revoked member is blocked immediately", async ({ page, browser, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false });
  await login(page, "bob@e2e.test");
  await page.goto(`/events/${event.id}`);
  await expect(page.getByRole("heading", { name: event.name })).toBeVisible();

  const org = await (await browser.newContext()).newPage();
  await login(org, "org@e2e.test");
  await org.goto(`/admin/events/${event.id}`);
  await org.getByRole("tab", { name: "Members" }).click();
  await org.getByRole("row", { name: /bob@e2e\.test/ }).getByRole("button", { name: "Revoke" }).click();
  await expect(org.getByRole("row", { name: /bob@e2e\.test/ }).getByText("revoked")).toBeVisible();

  await page.reload();
  await expect(page.getByText("You don't have access to this event.")).toBeVisible();
});

test("an expired event is blocked for attendees", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false });
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await expect(page.getByRole("heading", { name: event.name })).toBeVisible();

  expect((await request.post(`${API}/__e2e/event/${event.id}/expire`)).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByText("You don't have access to this event.")).toBeVisible();
});
