import { expect, test } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

test("a too-dark selfie is rejected with the lighting reason and only that shot is retaken", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page, { front: "dark" });
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page); // dark front: guidance won't auto-fire, manual shutter after 12 s

  await expect(page.getByText("It's too dark. Move to a brighter place or face a window.")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('[data-shot="front"]')).toBeVisible(); // retake the front photo only
});
