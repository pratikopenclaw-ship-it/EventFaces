import { expect, test } from "@playwright/test";

import { lastMail, linkIn, reset, seedEvent } from "./support";

test("sign up, verify email, join by code", async ({ page, request }) => {
  await reset(request);
  const event = await seedEvent(request, { synced: false });

  await page.goto("/signup");
  await page.getByLabel("Email").fill("carol@example.com");
  await page.getByRole("textbox", { name: /^Password/ }).fill("carol-password-1");
  const confirm = page.getByLabel("Confirm password");
  if (await confirm.count()) await confirm.fill("carol-password-1");
  await page.getByRole("checkbox", { name: /I accept the Terms of Use/ }).check();
  await page.getByRole("button", { name: /sign up|create account/i }).click();
  const mail = await lastMail(request, "carol@example.com");
  await page.goto(linkIn(mail));
  await expect(page.getByRole("heading", { name: "Email verified" })).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Email").fill("carol@example.com");
  await page.getByLabel("Password").fill("carol-password-1");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/events/);

  await page.goto(`/join/${event.slug}`);
  await page.getByLabel("Access code").fill("WRONGCOD");
  await page.getByRole("button", { name: "Join event" }).click();
  await expect(page.getByRole("alert").or(page.getByText(/invalid|wrong|incorrect/i)).first()).toBeVisible();
  await page.getByLabel("Access code").fill(event.code);
  await page.getByRole("button", { name: "Join event" }).click();
  await expect(page.getByRole("heading", { name: event.name })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Before we look for you" })).toBeVisible();
});
