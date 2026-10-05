import { expect, test } from "@playwright/test";

import { fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

test("a too-dark selfie is rejected with the lighting reason and only that shot is retaken", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page, { front: "dark" });
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await page.getByRole("button", { name: "Start camera" }).click();

  // The dark front shot needs the manual shutter (guidance won't auto-fire, ~12 s); left and
  // right then fire on their own, possibly too fast to observe on a fast machine. So drive
  // the capture until the server's verdict arrives instead of waiting to see each step.
  const verdict = page.getByText("It's too dark. Move to a brighter place or face a window.");
  const manual = page.getByRole("button", { name: "Take this photo now" });
  await expect
    .poll(
      async () => {
        if (await verdict.isVisible()) return "rejected";
        if (await manual.isVisible()) await manual.click().catch(() => undefined);
        return "capturing";
      },
      { timeout: 150_000, intervals: [500] },
    )
    .toBe("rejected");

  await expect(page.locator('[data-shot="front"]')).toBeVisible(); // retake the front photo only
});
