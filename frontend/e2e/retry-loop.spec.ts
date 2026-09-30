import { expect, test } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

// QA-002: a frame the browser's live guidance accepts but the server rejects (too blurry)
// used to auto-retake and resubmit endlessly, burning the user's search budget.
test("after repeated server rejections the camera pauses for the user instead of looping", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page, { front: "blurry" });
  const searches: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/search?source=camera")) searches.push(r.url());
  });
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);

  // First rejection: automatic retake of the front photo, then a second submit.
  const reason = "The photo is blurry. Hold still and make sure the camera is in focus.";
  await expect(page.getByText(reason)).toBeVisible({ timeout: 60_000 });
  await expect.poll(() => searches.length, { timeout: 90_000 }).toBe(2);

  // Second rejection in a row: paused, with the reason and tips, and no further submits.
  const retry = page.getByRole("button", { name: "Try again" });
  await expect(retry).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Let's fix this before trying again")).toBeVisible();
  await expect(page.getByText(reason)).toBeVisible();
  await page.waitForTimeout(8_000); // long enough for several auto-capture cycles
  expect(searches).toHaveLength(2);
  await expect(page.getByRole("button", { name: "Take this photo now" })).toHaveCount(0);

  // The user decides when to try again; the camera re-arms at the rejected shot.
  await retry.click();
  await expect(page.locator('[data-shot="front"]')).toBeVisible();
  await expect(retry).toHaveCount(0);
});
