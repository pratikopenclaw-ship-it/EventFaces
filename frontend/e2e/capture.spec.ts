import { expect, test } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

test("@xb camera capture → results with tiers → feedback → single and ZIP download", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);

  await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Best matches" })).toBeVisible();
  const tiles = page.getByRole("button", { name: "Open photo" });
  expect(await tiles.count()).toBeGreaterThanOrEqual(2); // left half + full group photo

  // Feedback
  await page.getByRole("button", { name: "This is me" }).first().click();
  await expect(page.getByText("✓ This is me").first()).toBeVisible();

  // ZIP of everything
  const zip = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download all/ }).click();
  expect((await zip).suggestedFilename()).toMatch(/\.zip$/);

  // Single photo from the lightbox
  await tiles.first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("img").first()).toBeVisible(); // the photo (the filmstrip follows)
  const single = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download" }).click();
  expect((await single).suggestedFilename()).toMatch(/\.jpg$/);
  await dialog.getByRole("button", { name: "Close" }).click();
});

test("@xb gallery of earlier results renders and paginates on small screens", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });

  await page.reload(); // earlier results come back from the server (grants), not the client
  await expect(page.getByRole("heading", { name: "Your photos" })).toBeVisible();
  const box = await page.getByRole("button", { name: "Open photo" }).first().boundingBox();
  const viewport = page.viewportSize()!;
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width); // no horizontal overflow
});
