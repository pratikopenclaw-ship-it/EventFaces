import { expect, test, type Page } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

// Visual regression for the main screens in both themes. Runs on desktop Chromium and
// the Pixel 7 project (@visual). Baselines live next to this file; after an intended
// visual change: npx playwright test e2e/visual.spec.ts --update-snapshots
// Live and per-run content (camera feed, dates, codes, the per-event cover pattern) is masked.

const SCHEMES = ["light", "dark"] as const;
// A fixed event name (the default seed adds a random suffix), so names are compared, not masked.
const VISUAL_EVENT = "Summer Party";

async function snap(page: Page, name: string, eventName?: string): Promise<void> {
  // The app is in System mode here, so the emulated scheme picks the theme with no reload.
  for (const scheme of SCHEMES) {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined))));
    await expect(page).toHaveScreenshot(`${name}-${scheme}.png`, {
      fullPage: true,
      animations: "disabled",
      // Seeded event names carry a random suffix; the Next dev-tools badge only exists in dev.
      mask: [page.locator("video, canvas, time, [data-volatile], nextjs-portal"), ...(eventName ? [page.getByText(eventName), page.locator(`input[value="${eventName}"]`)] : [])],
      maxDiffPixelRatio: 0.001, // tight enough that one missing word fails
    });
  }
}

test.describe("visual @visual", () => {
  test.beforeEach(async ({ request }) => {
    await reset(request);
  });

  test("landing", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("main h1").first()).toBeVisible();
    await snap(page, "landing");
  });

  test("settings", async ({ page, request }) => {
    await seedEvent(request, { name: VISUAL_EVENT });
    await login(page, "alice@e2e.test");
    await page.goto("/account");
    await expect(page.getByRole("radio", { name: "System" })).toBeChecked();
    await snap(page, "settings");
  });

  test("organizer dashboard", async ({ page, request }) => {
    const event = await seedEvent(request, { name: VISUAL_EVENT });
    await login(page, "org@e2e.test");
    await page.goto("/admin/events");
    await expect(page.getByRole("link", { name: event.name }).first()).toBeVisible();
    await snap(page, "organizer-events");
    await page.goto(`/admin/events/${event.id}`);
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
    await snap(page, "organizer-event");
  });

  test("selfie capture, results gallery and viewer", async ({ page, request }) => {
    const event = await seedEvent(request, { name: VISUAL_EVENT });
    await fakeCamera(page);
    await login(page, "alice@e2e.test");
    await page.goto(`/events/${event.id}`);
    await giveConsent(page);
    await expect(page.getByRole("button", { name: "Start camera" })).toBeVisible();
    await snap(page, "capture");
    await captureThreeShots(page);
    await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.locator("main img").first()).toBeVisible();
    await page.waitForFunction(() => [...document.querySelectorAll("main img")].every((i) => (i as HTMLImageElement).complete));
    await snap(page, "results");
    await page.getByRole("button", { name: "Open photo" }).first().click();
    await expect(page.getByRole("dialog").locator("img").first()).toBeVisible();
    await page.waitForFunction(() => (document.querySelector('[role="dialog"] img') as HTMLImageElement | null)?.complete === true);
    await snap(page, "viewer");
  });
});
