import { expect, test, type Page } from "@playwright/test";

import { API, lastMail, login, reset, seedEvent } from "./support";

// Legal documents on the web: reachable everywhere, versioned, accepted provably.

/** Show the English text whatever the browser's language (waits for the document first). */
async function inEnglish(page: Page): Promise<void> {
  await expect(page.locator("article h1")).toBeVisible();
  if ((await page.locator("article").getAttribute("lang")) !== "en") {
    await page.getByRole("button", { name: "English translation" }).click();
    await expect(page.locator("article[lang=en]")).toBeVisible();
  }
}

test("@xb every legal document is linked from the footer, in German and English", async ({ page }) => {
  for (const [link, title] of [
    ["Privacy", "Privacy Notice"],
    ["Terms", "Terms of Use"],
    ["Organizer terms", "Organizer Terms"],
    ["Imprint", "Legal notice (Impressum)"],
  ] as const) {
    await page.goto("/");
    await page.getByRole("contentinfo").getByRole("link", { name: link, exact: true }).click();
    await inEnglish(page);
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await expect(page.locator("article header p").first()).toContainText("The German version is binding.");
    await page.getByRole("button", { name: "Deutsche Fassung (verbindlich)" }).click();
    await expect(page.locator("article[lang=de] h2").first()).toBeVisible();
  }
});

test("the privacy notice has a cookie section listing every cookie", async ({ page }) => {
  await page.goto("/privacy");
  await inEnglish(page);
  const cookies = page.locator("section", { has: page.getByRole("heading", { name: /Cookies and storage on your device/ }) });
  for (const name of ["ef_access", "ef_refresh", "ef_csrf", "ef_theme"]) await expect(cookies).toContainText(name);
  await expect(cookies).toContainText("no cookie banner");
});

test("sign-up needs the terms ticked", async ({ page, request }) => {
  await reset(request);
  await page.goto("/signup");
  await page.getByLabel("Email").fill("terms-check@example.com");
  await page.getByRole("textbox", { name: /^Password/ }).fill("terms-check-pass-1");
  await page.getByLabel("Confirm password").fill("terms-check-pass-1");
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toHaveCount(0); // blocked
  const box = page.getByRole("checkbox", { name: /I accept the Terms of Use and confirm that I am at least 16/ });
  await box.check();
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  await lastMail(request, "terms-check@example.com");
});

test("@xb updated terms are shown and accepted before going on", async ({ page, request }) => {
  await reset(request);
  await seedEvent(request);
  expect((await request.post(`${API}/__e2e/legal/reset?email=alice@e2e.test`)).ok()).toBeTruthy();
  await login(page, "alice@e2e.test");
  await page.goto("/events");
  await expect(page).toHaveURL(/\/legal\/accept\?doc=terms/);
  await expect(page.getByRole("heading", { name: "Updated terms" })).toBeVisible();
  const accept = page.getByRole("button", { name: "Accept and continue" });
  await expect(accept).toBeDisabled();
  await page.getByRole("checkbox", { name: /I accept the Terms of Use/ }).check();
  await accept.click();
  await expect(page).toHaveURL(/\/events$/);
  await expect(page.getByRole("heading", { name: /events/i }).first()).toBeVisible();
});

test("organizers accept the organizer terms and the data processing agreement", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  expect((await request.post(`${API}/__e2e/legal/reset?email=org@e2e.test`)).ok()).toBeTruthy();
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  // Terms of Use first (any verified use), then the Organizer Terms for managing.
  await expect(page).toHaveURL(/\/legal\/accept\?doc=terms/);
  await page.getByRole("checkbox", { name: /I accept the Terms of Use/ }).check();
  await page.getByRole("button", { name: "Accept and continue" }).click();
  await expect(page).toHaveURL(/\/legal\/accept\?doc=organizer-terms/);
  await expect(page.getByRole("heading", { name: /Auftragsverarbeitungsvertrag|Data processing agreement/ }).first()).toBeVisible();
  await page.getByRole("checkbox", { name: /Organizer Terms and the data processing agreement/ }).check();
  await page.getByRole("button", { name: "Accept and continue" }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/events/${event.id}`));
});
