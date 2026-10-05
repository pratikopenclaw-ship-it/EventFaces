import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { captureThreeShots, fakeCamera, giveConsent, login, reset, seedEvent } from "./support";

// Canvas (body background) per theme, as computed colours.
const BG = { light: "rgb(243, 247, 246)", dark: "rgb(15, 17, 21)" } as const;

const bodyBg = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

/** Record the body background at the first animation frame, i.e. before hydration and before any client code runs. */
async function recordFirstPaint(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const probe = () => {
      if (!document.body) return requestAnimationFrame(probe);
      (window as unknown as { __firstPaint: unknown }).__firstPaint = {
        bg: getComputedStyle(document.body).backgroundColor,
        theme: document.documentElement.dataset.theme ?? null,
      };
    };
    requestAnimationFrame(probe);
  });
}

const firstPaint = (page: Page) => page.evaluate(() => (window as unknown as { __firstPaint: { bg: string; theme: string | null } }).__firstPaint);

async function chooseTheme(page: Page, label: "System" | "Light" | "Dark"): Promise<void> {
  await page.getByRole("button", { name: /^Theme: / }).click();
  await page.getByRole("menuitemradio", { name: label }).click();
  await expect(page.getByRole("button", { name: `Theme: ${label}` })).toBeVisible();
}

async function newContext(browser: Browser, colorScheme: "light" | "dark", storageState?: Awaited<ReturnType<BrowserContext["storageState"]>>) {
  return browser.newContext({ colorScheme, storageState, baseURL: test.info().project.use.baseURL });
}

test.describe("theme switcher", () => {
  test.beforeEach(async ({ request }) => {
    await reset(request);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`defaults to System and follows a ${scheme} OS`, async ({ browser }) => {
      const ctx = await newContext(browser, scheme);
      const page = await ctx.newPage();
      await recordFirstPaint(page);
      await page.goto("/");
      await expect(page.getByRole("button", { name: "Theme: System" })).toBeVisible();
      expect(await page.locator("html").getAttribute("data-theme")).toBeNull();
      expect(await bodyBg(page)).toBe(BG[scheme]);
      expect((await firstPaint(page)).bg).toBe(BG[scheme]);
      expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(scheme);
      await ctx.close();
    });
  }

  test("System mode updates live when the OS preference changes", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    expect(await bodyBg(page)).toBe(BG.light);
    await page.emulateMedia({ colorScheme: "dark" });
    await expect.poll(() => bodyBg(page)).toBe(BG.dark);
    await page.emulateMedia({ colorScheme: "light" });
    await expect.poll(() => bodyBg(page)).toBe(BG.light);
  });

  test("a guest's choice persists across reload and a new browser session, with no flash", async ({ browser }) => {
    const ctx = await newContext(browser, "light");
    const page = await ctx.newPage();
    await page.goto("/");
    await chooseTheme(page, "Dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect.poll(() => bodyBg(page)).toBe(BG.dark);
    const cookie = (await ctx.cookies()).find((c) => c.name === "ef_theme")!;
    expect(cookie).toMatchObject({ value: "dark", sameSite: "Lax", httpOnly: false, path: "/" });
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#171a21");

    // Reload: the server renders the saved theme, so the very first frame is already dark.
    await recordFirstPaint(page);
    const html = await (await page.reload())!.text();
    expect(html).toMatch(/<html[^>]*data-theme="dark"/);
    expect(await firstPaint(page)).toEqual({ bg: BG.dark, theme: "dark" });

    // New session: a fresh context from the saved cookies (like reopening the browser).
    const ctx2 = await newContext(browser, "light", await ctx.storageState());
    const page2 = await ctx2.newPage();
    await recordFirstPaint(page2);
    await page2.goto("/login");
    expect(await firstPaint(page2)).toEqual({ bg: BG.dark, theme: "dark" });
    await expect(page2.getByRole("button", { name: "Theme: Dark" })).toBeVisible();

    // Light is just as sticky; System removes the attribute again.
    await chooseTheme(page2, "Light");
    await page2.reload();
    expect(await firstPaint(page2)).toEqual({ bg: BG.light, theme: "light" });
    await chooseTheme(page2, "System");
    await page2.reload();
    expect(await firstPaint(page2)).toEqual({ bg: BG.light, theme: null });
    await ctx.close();
    await ctx2.close();
  });

  test("a signed-in choice is saved to the profile and follows the user to a second browser", async ({ browser, request }) => {
    await seedEvent(request);
    const a = await newContext(browser, "light");
    const pageA = await a.newPage();
    await login(pageA, "alice@e2e.test");
    await pageA.goto("/account");
    await pageA.getByRole("radio", { name: "Dark" }).check();
    await expect(pageA.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect.poll(async () => (await (await pageA.request.get("/api/me")).json()).theme).toBe("dark");

    const b = await newContext(browser, "light");
    const pageB = await b.newPage();
    await pageB.goto("/");
    expect(await bodyBg(pageB)).toBe(BG.light); // a guest on B: still System
    await login(pageB, "alice@e2e.test"); // login sets ef_theme from the profile
    await recordFirstPaint(pageB);
    await pageB.goto("/events");
    expect(await firstPaint(pageB)).toEqual({ bg: BG.dark, theme: "dark" });

    // B changes it back; A picks it up on its next session load.
    await chooseTheme(pageB, "Light");
    await expect.poll(async () => (await (await pageB.request.get("/api/me")).json()).theme).toBe("light");
    await pageA.goto("/events");
    await expect(pageA.locator("html")).toHaveAttribute("data-theme", "light");
    await a.close();
    await b.close();
  });

  test("the menu is keyboard accessible, labelled, announced and a 44px target", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    await page.goto("/");
    const button = page.getByRole("button", { name: "Theme: System" });
    const box = (await button.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
    await button.focus();
    expect(await button.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none"); // visible focus
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("menu", { name: "Theme" })).toBeVisible();
    await expect(page.getByRole("menuitemradio", { name: "System" })).toBeFocused();
    await expect(page.getByRole("menuitemradio", { name: "System" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByText("Photos always display on a dark background.")).toBeVisible();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menuitemradio", { name: "Dark" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: "Theme set to Dark" })).toBeAttached();
    await expect(page.getByRole("button", { name: "Theme: Dark" })).toBeFocused();
    // Reduced motion: no transition during the switch.
    expect(await page.evaluate(() => getComputedStyle(document.body).transitionDuration)).toBe("0s");
    await page.keyboard.press("Enter");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Theme: Dark" })).toBeFocused();
  });

  test("switching animates briefly, but never on first load", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "no-preference" });
    await page.goto("/");
    expect(await page.evaluate(() => document.documentElement.classList.contains("theme-switching"))).toBe(false);
    expect(await page.evaluate(() => getComputedStyle(document.body).transitionDuration)).toBe("0s");
    await page.getByRole("button", { name: "Theme: System" }).click();
    await page.getByRole("menuitemradio", { name: "Dark" }).click();
    const duration = await page.evaluate(() => getComputedStyle(document.body).transitionDuration);
    expect(duration).toMatch(/^0\.18s(, 0\.18s)*$/);
    await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains("theme-switching"))).toBe(false);
  });

  test("the gallery and photo viewer stay dark in light mode @xb", async ({ page, request }) => {
    const event = await seedEvent(request);
    await page.emulateMedia({ colorScheme: "light" });
    await fakeCamera(page);
    await login(page, "alice@e2e.test");
    await page.goto(`/events/${event.id}`);
    await chooseTheme(page, "Light");
    await giveConsent(page);
    await captureThreeShots(page);
    await expect(page.getByRole("heading", { name: /^You.re in \d+ photos?$/ })).toBeVisible({ timeout: 60_000 });
    expect(await bodyBg(page)).toBe(BG.light);
    const gallery = page.locator(".theme-dark").first();
    expect(await gallery.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(BG.dark);
    expect(await gallery.evaluate((el) => getComputedStyle(el).colorScheme)).toBe("dark");
    await page.getByRole("button", { name: "Open photo" }).first().click();
    const viewer = page.getByRole("dialog");
    await expect(viewer).toBeVisible();
    // Computed colour formats vary (rgba, oklab): paint it and measure.
    const lum = await viewer.evaluate((el) => {
      const c = document.createElement("canvas").getContext("2d")!;
      c.fillStyle = getComputedStyle(el).backgroundColor;
      c.fillRect(0, 0, 1, 1);
      const [r, g, b] = c.getImageData(0, 0, 1, 1).data;
      return (r + g + b) / 3;
    });
    expect(lum).toBeLessThan(40);
  });

  test("per-event accents stay readable in both themes", async ({ page, request }) => {
    const event = await seedEvent(request);
    await login(page, "org@e2e.test");
    const csrf = (await (await page.request.get("/api/auth/csrf")).json()).csrf_token;
    // Pure yellow: unreadable as text on white, and needs dark text on top.
    const r = await page.request.patch(`/api/events/${event.id}`, { data: { accent_color: "#FFFF00" }, headers: { "X-CSRF-Token": csrf } });
    expect(r.status()).toBe(200);
    await page.goto(`/admin/events/${event.id}`);
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      const save = page.getByRole("button", { name: "Save changes" });
      await expect(save).toBeVisible();
      const ratio = await save.evaluate((el) => {
        const rgb = (css: string) => {
          const c = document.createElement("canvas").getContext("2d")!;
          c.fillStyle = css;
          c.fillRect(0, 0, 1, 1);
          return [...c.getImageData(0, 0, 1, 1).data.slice(0, 3)].map((v) => {
            const s = v / 255;
            return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
          });
        };
        const lum = (css: string) => {
          const [r, g, b] = rgb(css);
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const s = getComputedStyle(el);
        const [a, b] = [lum(s.color), lum(s.backgroundColor)];
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      });
      expect(ratio, scheme).toBeGreaterThanOrEqual(4.5);
    }
  });
});

test.describe("theme security", () => {
  test("a tampered theme cookie is ignored and can't inject markup", async ({ browser }) => {
    const ctx = await newContext(browser, "light");
    await ctx.addCookies([{ name: "ef_theme", value: 'dark"%20onload="alert(1)', url: test.info().project.use.baseURL! }]);
    const page = await ctx.newPage();
    const html = await (await page.goto("/"))!.text();
    expect(html).not.toContain("onload=");
    expect(await page.locator("html").getAttribute("data-theme")).toBeNull();
    await expect(page.getByRole("button", { name: "Theme: System" })).toBeVisible();
    await ctx.close();
  });

  test("the API accepts only the three theme values", async ({ page, request }) => {
    await reset(request);
    await seedEvent(request);
    await login(page, "alice@e2e.test");
    const csrf = (await (await page.request.get("/api/auth/csrf")).json()).csrf_token;
    for (const bad of ["purple", "", "DARK", '"><script>', null]) {
      const r = await page.request.patch("/api/me/preferences", { data: { theme: bad }, headers: { "X-CSRF-Token": csrf } });
      expect(r.status(), String(bad)).toBe(422);
    }
    expect((await page.request.patch("/api/me/preferences", { data: { theme: "dark" }, headers: { "X-CSRF-Token": csrf } })).status()).toBe(200);
  });

  test("CSP still blocks an inline script without the nonce", async ({ page }) => {
    // Inject a nonce-less inline script into the real HTML response.
    await page.route("**/", async (route) => {
      const response = await route.fetch();
      const body = (await response.text()).replace("</head>", "<script>window.__injected = true</script></head>");
      await route.fulfill({ response, body });
    });
    const violations: string[] = [];
    await page.exposeFunction("__reportViolation", (d: string) => violations.push(d));
    await page.addInitScript(() =>
      document.addEventListener("securitypolicyviolation", (e) =>
        (window as unknown as { __reportViolation: (d: string) => void }).__reportViolation(e.effectiveDirective),
      ),
    );
    const response = await page.goto("/");
    const csp = response!.headers()["content-security-policy"];
    expect(csp).toMatch(/script-src [^;]*'nonce-[A-Za-z0-9+/=]+'/);
    expect(csp.split(";").find((d) => d.trim().startsWith("script-src"))).not.toContain("'unsafe-inline'");
    await expect(page.getByRole("button", { name: /^Theme: / })).toBeVisible(); // the app's own (nonced) scripts run
    expect(await page.evaluate(() => (window as unknown as { __injected?: boolean }).__injected)).toBeUndefined();
    await expect.poll(() => violations).toContain("script-src-elem");
  });
});
