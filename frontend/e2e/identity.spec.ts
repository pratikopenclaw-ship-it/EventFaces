import { expect, test } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

// Event identity, the results reveal and the printable QR material.

test("each event shows its cover on its page, in lists and on the join page @xb", async ({ page, request, browser }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false, name: "Anna & Ben's Wedding" });
  await login(page, "alice@e2e.test");

  await page.goto(`/join/${event.slug}`);
  await expect(page.getByTestId("event-cover").getByRole("heading", { name: "Anna & Ben's Wedding", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Join this event", level: 1 })).toBeVisible();

  await page.goto(`/events/${event.id}`);
  await expect(page.getByTestId("event-cover").getByRole("heading", { name: "Anna & Ben's Wedding", level: 1 })).toBeVisible();

  await page.goto("/events");
  const card = page.getByRole("link", { name: /Anna & Ben's Wedding/ });
  await expect(card).toBeVisible();
  await card.click();
  await expect(page).toHaveURL(new RegExp(`/events/${event.id}$`));

  const org = await (await browser.newContext()).newPage();
  await login(org, "org@e2e.test");
  await org.goto("/admin/events");
  await org.getByRole("link", { name: /Anna & Ben's Wedding/ }).click();
  await expect(org.getByTestId("event-cover")).toContainText("Anna & Ben's Wedding");
});

test("fresh results say how many photos you're in; the viewer has focus, a filmstrip and swipes", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);

  const headline = page.getByRole("heading", { name: /^You.re in \d+ photos?$/ });
  await expect(headline).toBeVisible({ timeout: 60_000 });
  const tiles = page.getByRole("button", { name: "Open photo" });
  const count = await tiles.count();
  expect(await headline.textContent()).toBe(count === 1 ? "You're in 1 photo" : `You're in ${count} photos`);

  await tiles.first().click();
  const viewer = page.getByRole("dialog", { name: "Photo viewer" });
  await expect(viewer).toBeFocused();
  await expect(viewer.getByText(`1 / ${count}`)).toBeVisible();
  const strip = viewer.getByRole("button", { name: /^Photo \d+$/ });
  await expect(strip).toHaveCount(count);
  await expect(strip.first()).toHaveAttribute("aria-current", "true");

  // Swipe left with the pointer: next photo. Measure the photo once it has loaded (before
  // that it is 0 px wide and the "swipe" would not move at all).
  const photo = viewer.locator("img").first();
  await expect.poll(() => photo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0), { timeout: 20_000 }).toBe(true);
  const box = (await photo.boundingBox())!;
  expect(box.width).toBeGreaterThan(100);
  await page.mouse.move(box.x + box.width * 0.75, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();
  await expect(viewer.getByText(`2 / ${count}`)).toBeVisible();
  await expect(strip.nth(1)).toHaveAttribute("aria-current", "true");

  // The filmstrip jumps back.
  await strip.first().click();
  await expect(viewer.getByText(`1 / ${count}`)).toBeVisible();
});

test("organizers print a branded QR poster or table cards", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false, name: "Anna & Ben's Wedding" });
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}?tab=access`);
  await page.getByRole("link", { name: "Print poster or table cards" }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/events/${event.id}/poster$`));

  const sheet = page.getByTestId("poster-sheet");
  await expect(sheet.getByText("Find your photos")).toBeVisible();
  await expect(sheet.getByRole("img", { name: /QR code to join/ })).toHaveCount(1);
  await page.getByRole("radio", { name: "4 table cards" }).click();
  await expect(sheet.getByRole("img", { name: /QR code to join/ })).toHaveCount(4);

  // Printed: the site's header and footer are gone, the sheet stays.
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("banner")).toBeHidden();
  await expect(sheet).toBeVisible();
});

test("a branded event replaces the EventFaces wordmark with the organizer's logo in the header", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { name: "Branded Gala" });
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  await page.getByLabel("Upload logo").setInputFiles({
    name: "logo.png",
    mimeType: "image/png",
    // 1×1 transparent PNG
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64"),
  });
  await page.context().clearCookies();

  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  const header = page.getByRole("banner");
  await expect(header.getByRole("img", { name: "Event logo" })).toBeVisible();
  await expect(header.getByText("EventFaces")).toHaveCount(0);

  // Leaving the event page restores the default header.
  await page.goto("/events");
  await expect(page.getByRole("banner").getByText("EventFaces")).toBeVisible();
});

test("link previews show the branded image and never an event name", async ({ request }) => {
  const r = await request.get("/opengraph-image");
  expect(r.status()).toBe(200);
  expect(r.headers()["content-type"]).toBe("image/png");
  const html = await (await request.get("/login")).text();
  expect(html).toMatch(/<meta property="og:image" content="[^"]*\/opengraph-image/);
});
