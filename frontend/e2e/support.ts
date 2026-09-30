import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = "http://127.0.0.1:8000";
export const PASSWORD = "e2e-password-123";
export const FOLDER = "1E2EFolderAAAAAAAAAA";

export interface SeededEvent {
  id: string;
  slug: string;
  code: string;
  name: string;
}

export async function reset(request: APIRequestContext): Promise<void> {
  expect((await request.post(`${API}/__e2e/reset`)).ok()).toBeTruthy();
}

export async function seedEvent(
  request: APIRequestContext,
  opts: { join_mode?: "code" | "invite"; guest_uploads?: boolean; moderation?: "manual" | "auto"; synced?: boolean } = {},
): Promise<SeededEvent> {
  const params = new URLSearchParams(Object.entries(opts).map(([k, v]) => [k, String(v)]));
  const r = await request.post(`${API}/__e2e/event?${params}`, { timeout: 120_000 });
  expect(r.ok()).toBeTruthy();
  return r.json();
}

export async function lastMail(request: APIRequestContext, to: string): Promise<{ subject: string; body: string }> {
  let body: { subject: string; body: string } | null = null;
  await expect
    .poll(async () => {
      const r = await request.get(`${API}/__e2e/mail?to=${encodeURIComponent(to)}`);
      if (r.ok()) body = await r.json();
      return r.ok();
    })
    .toBeTruthy();
  return body!;
}

export function linkIn(mail: { body: string }): string {
  const m = mail.body.match(/https?:\/\/\S+/);
  if (!m) throw new Error(`no link in mail: ${mail.body}`);
  return new URL(m[0]).pathname + new URL(m[0]).search;
}

/** Log in through the API (cookies land in the page's context). */
export async function login(page: Page, email: string): Promise<void> {
  const csrf = await (await page.request.get("/api/auth/csrf")).json();
  const r = await page.request.post("/api/auth/login", {
    data: { email, password: PASSWORD },
    headers: { "X-CSRF-Token": csrf.csrf_token },
  });
  expect(r.status()).toBe(200);
}

/**
 * Fake camera for every browser: getUserMedia returns a canvas stream showing a JPEG
 * that follows the capture step on screen (data-shot=front|left|right). Frames come
 * from the e2e server (alice's selfies) via a same-origin route, so the canvas isn't
 * tainted. `override` lets a test show a different frame for one step.
 */
export async function fakeCamera(page: Page, override: Partial<Record<"front" | "left" | "right", string>> = {}): Promise<void> {
  await page.route("**/__fakecam/*.jpg", async (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop()!.replace(".jpg", "");
    const r = await page.request.get(`${API}/__e2e/selfie/${name}.jpg`);
    await route.fulfill({ status: 200, contentType: "image/jpeg", body: await r.body() });
  });
  await page.addInitScript((override) => {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext("2d")!;
    const images: Record<string, HTMLImageElement> = {};
    let current = "front";
    const image = (name: string) => {
      if (!images[name]) {
        images[name] = new Image();
        images[name].src = `/__fakecam/${name}.jpg`;
      }
      return images[name];
    };
    const draw = () => {
      const img = image((override as Record<string, string>)[current] ?? current);
      if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, 640, 480);
      else {
        ctx.fillStyle = "#333";
        ctx.fillRect(0, 0, 640, 480);
      }
    };
    setInterval(draw, 33);
    new MutationObserver(() => {
      const el = document.querySelector("[data-shot]");
      const shot = el?.getAttribute("data-shot");
      if (shot && shot !== "done") current = shot;
    }).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-shot"] });
    const devices = navigator.mediaDevices ?? ({} as MediaDevices);
    Object.defineProperty(navigator, "mediaDevices", { value: devices, configurable: true });
    devices.getUserMedia = async () => {
      draw();
      return canvas.captureStream(30);
    };
  }, override);
}

/** Drive the guided capture: auto-capture when guidance passes, manual shutter otherwise. */
export async function captureThreeShots(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Start camera" }).click();
  for (const shot of ["front", "left", "right"]) {
    const step = page.locator(`[data-shot="${shot}"]`);
    await expect(step).toBeVisible({ timeout: 30_000 });
    const manual = page.getByRole("button", { name: "Take this photo now" });
    await expect
      .poll(
        async () => {
          if (!(await step.isVisible())) return "moved on";
          if (await manual.isVisible()) await manual.click().catch(() => undefined);
          return "waiting";
        },
        { timeout: 45_000, intervals: [500] },
      )
      .toBe("moved on");
  }
}

export async function giveConsent(page: Page): Promise<void> {
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Continue to selfie" }).click();
}
