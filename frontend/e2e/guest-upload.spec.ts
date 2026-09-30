import { expect, test } from "@playwright/test";

import { API, login, reset, seedEvent } from "./support";

test("guest upload waits for moderation, then publishes", async ({ page, browser, request }) => {
  await reset(request);
  const event = await seedEvent(request, { guest_uploads: true, moderation: "manual", synced: false });
  const photo = await (await request.get(`${API}/__e2e/guest-photo.jpg`)).body();

  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await expect(page.getByRole("heading", { name: "Add your photos" })).toBeVisible();
  await page.locator('input[type="file"][multiple], input[type="file"]').last().setInputFiles({ name: "party.jpg", mimeType: "image/jpeg", buffer: photo });
  await expect(page.getByText("Awaiting approval")).toBeVisible({ timeout: 60_000 });

  const org = await (await browser.newContext()).newPage();
  await login(org, "org@e2e.test");
  await org.goto(`/admin/events/${event.id}`);
  await org.getByRole("tab", { name: "Moderation" }).click();
  await org.getByRole("button", { name: "Approve" }).first().click();
  await expect(org.getByText("Nothing to review.")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Published")).toBeVisible();
});
