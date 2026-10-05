import { expect, test } from "@playwright/test";

import { API, reset } from "./support";

// Browser errors reach GlitchTip (here: the e2e API's fake envelope endpoint) through the
// same-origin /monitoring tunnel, with tokens, query strings and emails removed.
type Received = { auth: string; event: { release: string; tags: Record<string, string>; request?: { url: string }; exception: { values: { type: string; value: string }[] } } };

async function received(request: import("@playwright/test").APIRequestContext): Promise<Received[]> {
  return (await request.get(`${API}/__e2e/glitchtip/events`)).json();
}

test("an uncaught browser error is reported without secrets @xb", async ({ page, request }) => {
  await reset(request);
  await page.goto("/invite/INVITESECRET123?next=/events#frag");
  // Thrown until one arrives: an error before the reporter's script has loaded is not seen.
  await expect
    .poll(async () => {
      await page.evaluate(() => {
        setTimeout(() => {
          throw new TypeError("boom for alice@example.com token=QUERYSECRET at /removal/RMSECRET");
        }, 0);
      });
      return (await received(request)).length;
    })
    .toBeGreaterThan(0);
  const [report] = await received(request);
  const json = JSON.stringify(report);
  for (const secret of ["INVITESECRET123", "QUERYSECRET", "RMSECRET", "alice@example.com", "frag", "ef_"]) {
    expect(json).not.toContain(secret);
  }
  expect(report.auth).toContain("sentry_key=e2e");
  expect(report.event.release).toBe("e2e");
  expect(report.event.tags.component).toBe("web-browser");
  expect(report.event.request?.url).toBe("/invite/[redacted]");
  expect(report.event.exception.values[0]).toMatchObject({ type: "TypeError", value: "boom for [email] token=[redacted] at /removal/[redacted]" });
});

test("unhandled rejections are reported once per message", async ({ page, request }) => {
  await reset(request);
  await page.goto("/");
  await expect
    .poll(async () => {
      await page.evaluate(() => {
        for (let i = 0; i < 3; i++) void Promise.reject(new Error("same failure"));
      });
      return (await received(request)).length;
    })
    .toBe(1);
  await page.waitForTimeout(500);
  expect((await received(request)).length).toBe(1);
});

test("the tunnel refuses requests that do not come from our pages", async ({ request }) => {
  const r = await request.post("/monitoring", { data: { message: "spoofed" } });
  expect(r.status()).toBe(403);
  const cross = await request.post("/monitoring", { data: { message: "spoofed" }, headers: { "Sec-Fetch-Site": "cross-site" } });
  expect(cross.status()).toBe(403);
});
