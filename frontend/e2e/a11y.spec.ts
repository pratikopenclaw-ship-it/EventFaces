import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { API, captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

async function audit(page: Page, name: string): Promise<void> {
  // Let CSS transitions settle: axe otherwise samples e.g. a button fading in from
  // its disabled 50% opacity and reports a contrast that no user ever sees for long.
  await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined))));
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    serious.map(
      (v) =>
        `${name}: ${v.id} (${v.impact}) ` +
        v.nodes
          .slice(0, 3)
          .map((n) => `${n.target.join(" ")} ${n.html.slice(0, 160)} [${(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 200)}]`)
          .join(" | "),
    ),
  ).toEqual([]);
}

test("axe: public and auth pages", async ({ page, request }) => {
  await reset(request);
  // (Not "networkidle": the dev server's HMR socket never goes idle.)
  for (const path of ["/", "/login", "/signup", "/forgot-password", "/privacy", "/removal-request"]) {
    await page.goto(path);
    await expect(page.locator("main h1, main h2").first()).toBeVisible();
    await audit(page, path);
  }
});

test("axe: attendee flow (events, consent, capture, results)", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto("/events");
  await audit(page, "/events");
  await page.goto(`/events/${event.id}`);
  await expect(page.getByRole("heading", { name: "Before we look for you" })).toBeVisible();
  await audit(page, "consent");
  await giveConsent(page);
  await expect(page.getByRole("button", { name: "Start camera" })).toBeVisible();
  await audit(page, "capture requirements");
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: "We found you" })).toBeVisible({ timeout: 60_000 });
  await audit(page, "results");
  await page.getByRole("button", { name: "Open photo" }).first().click();
  await audit(page, "lightbox");
});

test("axe: organizer admin tabs", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { guest_uploads: true });
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  for (const tab of ["Settings", "Access", "Members", "Photos", "Moderation", "Match quality"]) {
    await page.getByRole("tab", { name: tab }).click();
    await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("Loading…")).toHaveCount(0);
    await audit(page, `admin/${tab}`);
  }
});

test("axe: screens changed in the delta pass (join context, queued search, paused camera)", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await page.goto(`/join/${event.slug}?code=${event.code}`);
  await expect(page.getByRole("heading", { name: "Log in to join the event" })).toBeVisible();
  await audit(page, "login (join context)");
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page.getByRole("heading", { name: "Create an account to join the event" })).toBeVisible();
  await audit(page, "signup (join context)");

  // Queued search card.
  await fakeCamera(page);
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  expect((await request.post(`${API}/__e2e/face-slots/hold`)).ok()).toBeTruthy();
  await captureThreeShots(page);
  await expect(page.getByRole("heading", { name: "You're in the queue" })).toBeVisible({ timeout: 60_000 });
  await audit(page, "queued search");
  await page.goto("/events");
  await expect(page.getByText("Search queued")).toBeVisible();
  await audit(page, "my events (queued badge)");
  expect((await request.post(`${API}/__e2e/face-slots/release`)).ok()).toBeTruthy();
});

test("axe: paused camera after repeated rejections", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await fakeCamera(page, { front: "blurry" });
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  await giveConsent(page);
  await captureThreeShots(page);
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible({ timeout: 90_000 });
  await audit(page, "paused camera");
});
