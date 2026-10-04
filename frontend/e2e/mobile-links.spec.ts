import { expect, test } from "@playwright/test";

import { API, login, reset, seedEvent } from "./support";

// Web side of the iOS app (Phase 0): Universal Links file, the sign-in link landing page,
// and organizer logos.

test("AASA is served as JSON with no redirect (e2e web has test app ids)", async ({ request }) => {
  const r = await request.get("/.well-known/apple-app-site-association", { maxRedirects: 0 });
  expect(r.status()).toBe(200);
  expect(r.headers()["content-type"]).toContain("application/json");
  const body = await r.json();
  expect(body.applinks.details[0].appIDs).toEqual(["TEST000000.app.eventfaces.test"]);
  expect(body.applinks.details[0].components[0]).toMatchObject({ "/": "/admin/*", exclude: true });
});

test("a sign-in link opened in a browser explains itself and never spends the token", async ({ page, request }) => {
  await reset(request);
  // Ask the app API for a code, then open the emailed link in the browser.
  const r = await request.post(`${API}/api/mobile/auth/code/request`, { data: { email: "phone-user@example.com" }, headers: { "X-App-Version": "1.0.0" } });
  expect(r.status()).toBe(202);
  const mail = await (await request.get(`${API}/__e2e/mail?to=phone-user@example.com`)).json();
  const link = new URL(mail.body.match(/https?:\/\/\S+\/m\/signin\?t=\S+/)[0]);
  await page.goto(link.pathname + link.search);
  await expect(page.getByRole("heading", { name: "Open this link in the app" })).toBeVisible();
  // The token is dropped from the URL before the page renders.
  expect(new URL(page.url()).search).toBe("");
  expect(await page.content()).not.toContain(link.searchParams.get("t")!);
  // Still usable by the app afterwards.
  const key = await page.evaluate(async () => {
    const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign"]);
    const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    return btoa(String.fromCharCode(...raw));
  });
  const signIn = await request.post(`${API}/api/mobile/auth/magic`, {
    data: { token: link.searchParams.get("t"), accept_terms: true, device: { name: "Phone", public_key: key } },  // as the app sends it
    headers: { "X-App-Version": "1.0.0" },
  });
  expect(signIn.status()).toBe(200);
});

test("organizer uploads a logo; attendees see it on the event page", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request);
  await login(page, "org@e2e.test");
  await page.goto(`/admin/events/${event.id}`);
  await page.getByLabel("Upload logo").setInputFiles({
    name: "logo.png",
    mimeType: "image/png",
    // 1×1 transparent PNG
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64"),
  });
  await expect(page.getByRole("img", { name: "Current logo" })).toBeVisible();
  await page.context().clearCookies();
  await login(page, "alice@e2e.test");
  await page.goto(`/events/${event.id}`);
  const logo = page.getByRole("img", { name: `${event.name} logo` });
  await expect(logo).toBeVisible();
  expect(await logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
});
