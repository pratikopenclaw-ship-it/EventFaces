import { expect, test, type Page } from "@playwright/test";

import { API, login, reset, seedEvent } from "./support";

// Photos with no detected face: the organizer setting that auto-publishes them (or holds
// them for review), and sharing them with every member under "Event photos".

async function uploadFaceless(page: Page, eventId: string, request: Page["request"]): Promise<void> {
  const blank = await (await request.get(`${API}/__e2e/selfie/blank.jpg`)).body();
  await page.goto(`/events/${eventId}`);
  await expect(page.getByRole("heading", { name: "Add your photos" })).toBeVisible();
  await page.locator('input[type="file"][multiple], input[type="file"]').last().setInputFiles({ name: "venue.jpg", mimeType: "image/jpeg", buffer: blank });
}

test("with auto-publish off, a photo with no face waits for review", async ({ page, browser, request }) => {
  await reset(request);
  const event = await seedEvent(request, { guest_uploads: true, moderation: "auto", synced: false });

  const org = await (await browser.newContext()).newPage();
  await login(org, "org@e2e.test");
  await org.goto(`/admin/events/${event.id}`);
  const toggle = org.getByRole("checkbox", { name: /Publish photos with no face detected/ });
  await expect(toggle).toBeChecked(); // default keeps the old behaviour
  await toggle.uncheck();
  await org.getByRole("button", { name: "Save changes" }).click();
  await expect(org.getByText("Saved.")).toBeVisible();

  await login(page, "alice@e2e.test");
  await uploadFaceless(page, event.id, page.request);
  await expect(page.getByText("Awaiting approval")).toBeVisible({ timeout: 60_000 });

  await org.reload();
  await org.getByRole("tab", { name: "Moderation" }).click();
  await expect(org.getByRole("button", { name: "Approve" }).first()).toBeVisible();
});

test("a photo with no face publishes at once and the organizer can share it with everyone", async ({ page, browser, request }) => {
  await reset(request);
  // Synced group photos (with faces) must never show up as shareable.
  const event = await seedEvent(request, { guest_uploads: true, moderation: "auto", synced: true });

  await login(page, "alice@e2e.test");
  await uploadFaceless(page, event.id, page.request);
  await expect(page.getByText("Published")).toBeVisible({ timeout: 60_000 });

  // Bob matched nothing: no event photos yet.
  const bob = await (await browser.newContext()).newPage();
  await login(bob, "bob@e2e.test");
  await bob.goto(`/events/${event.id}`);
  await expect(bob.getByRole("heading", { name: event.name })).toBeVisible();
  await expect(bob.getByRole("heading", { name: "Event photos" })).toHaveCount(0);

  const org = await (await browser.newContext()).newPage();
  await login(org, "org@e2e.test");
  await org.goto(`/admin/events/${event.id}`);
  await org.getByRole("tab", { name: "Shared photos" }).click();
  await expect(org.getByRole("checkbox", { name: "Select photo" })).toHaveCount(1);
  await expect(org.getByText("venue.jpg")).toBeVisible();
  await expect(org.getByText("Private")).toBeVisible();
  org.once("dialog", (d) => d.accept());
  await org.getByRole("button", { name: /Share all not yet shared \(1\)/ }).click();
  await expect(org.getByText("1 photo shared.")).toBeVisible();
  await expect(org.getByText("Shared", { exact: true }).last()).toBeVisible();

  await bob.reload();
  await expect(bob.getByRole("heading", { name: "Event photos" })).toBeVisible();
  await expect(bob.getByText("Venue, food & more")).toBeVisible();

  // Unsharing takes it away again.
  await org.getByRole("checkbox", { name: "Select photo" }).check();
  await org.getByRole("button", { name: "Unshare selected" }).click();
  await expect(org.getByText("1 photo unshared.")).toBeVisible();
  await bob.reload();
  await expect(bob.getByRole("heading", { name: event.name })).toBeVisible();
  await expect(bob.getByRole("heading", { name: "Event photos" })).toHaveCount(0);
});
