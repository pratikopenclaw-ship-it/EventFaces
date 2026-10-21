import { webcrypto } from "node:crypto";

import { expect, test, type APIRequestContext } from "@playwright/test";

import { API, PASSWORD, lastMail, login, reset } from "./support";

// The web account page lists the phones signed in to the app and can sign one out, so a
// lost phone can be cut off from a laptop (the app has the same list under Settings).

const EMAIL = "devices@example.com";

/** Sign in "as the app": an emailed code plus a device key, like the iOS sign-in. */
async function appSignIn(request: APIRequestContext, name: string): Promise<string> {
  const headers = { "X-App-Version": "99.0.0" };
  expect((await request.post(`${API}/api/mobile/auth/code/request`, { headers, data: { email: EMAIL } })).ok()).toBeTruthy();
  // The sign-up verification mail went to the same address first: wait for the code mail.
  let code: string | undefined;
  await expect
    .poll(async () => (code = (await lastMail(request, EMAIL)).subject.match(/^(\d{6}) is your EventFaces code$/)?.[1]))
    .toBeTruthy();

  const key = await webcrypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const raw = Buffer.from(await webcrypto.subtle.exportKey("raw", key.publicKey)); // 65-byte uncompressed point
  const r = await request.post(`${API}/api/mobile/auth/code/verify`, {
    headers,
    data: { email: EMAIL, code, accept_terms: true, device: { name, platform: "ios", public_key: raw.toString("base64") } },
  });
  expect(r.ok()).toBeTruthy();
  return (await r.json()).access_token;
}

test("account page lists app devices and signs one out", async ({ page, request }) => {
  await reset(request);
  // A web account with a password, then the same person signs in on a phone.
  await page.request.get("/api/auth/csrf");
  const csrf = (await page.context().cookies()).find((c) => c.name === "ef_csrf")?.value ?? "";
  const signup = await page.request.post("/api/auth/signup", {
    data: { email: EMAIL, password: PASSWORD, accept_terms: true },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(signup.ok()).toBeTruthy();
  const phoneToken = await appSignIn(request, "Test iPhone");

  await login(page, EMAIL);
  await page.goto("/account");
  const devices = page.getByRole("region", { name: "Signed-in devices" });
  await expect(devices.getByText("Test iPhone")).toBeVisible();

  await devices.getByRole("button", { name: "Sign out Test iPhone" }).click();
  await expect(devices.getByText("Test iPhone")).toBeHidden();
  await expect(devices.getByText("No phones or tablets are signed in to the app.")).toBeVisible();

  // The phone's session really ended.
  const me = await request.get(`${API}/api/me`, { headers: { Authorization: `Bearer ${phoneToken}`, "X-App-Version": "99.0.0" } });
  expect(me.status()).toBe(401);
});
