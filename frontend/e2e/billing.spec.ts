import { expect, test } from "@playwright/test";

import { login, reset } from "./support";

// Buying an event in TEST MODE: pricing → checkout → hosted test payment (declined, then
// paid) → the new event, managed by the buyer → billing and receipt.
test("buy Event S with a test card and manage the new event", async ({ page, request }) => {
  await reset(request);
  await login(page, "alice@e2e.test");

  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "Simple pricing" })).toBeVisible();
  await expect(page.getByText(/Test mode: no real payments/)).toBeVisible();
  await page.getByRole("link", { name: "Choose Event S" }).click();

  await expect(page).toHaveURL(/\/checkout\?plan=event_s/);
  await expect(page.getByText("TEST MODE")).toBeVisible();
  await page.getByLabel("Event name").fill("Alice's Garden Party");
  await page.getByRole("button", { name: "Continue to payment" }).click();

  await expect(page).toHaveURL(/\/checkout\/test\/fcs_/);
  await expect(page.getByRole("heading", { name: "Payment" })).toBeVisible();
  await page.getByLabel("Expiry").fill("12/30");
  await page.getByLabel("CVC").fill("123");

  // A real-looking card number is refused outright.
  await page.getByLabel("Card number (test cards only)").fill("5555 5555 5555 4444");
  await page.getByRole("button", { name: /^Pay / }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("test card");

  // The declining test card: the order stays payable.
  await page.getByRole("button", { name: /4000 0000 0000 0002/ }).click();
  await page.getByRole("button", { name: /^Pay / }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("declined");

  await page.getByRole("button", { name: /4242 4242 4242 4242/ }).click();
  await page.getByRole("button", { name: /^Pay / }).click();

  await expect(page).toHaveURL(/\/admin\/events\/[0-9a-f-]+/);
  await expect(page.getByRole("heading", { name: "Alice's Garden Party" })).toBeVisible();
  await expect(page.getByText(/Event S plan · 0 \/ 100 attendees · 0 \/ 500 photos/)).toBeVisible();

  await page.goto("/account/billing");
  const row = page.getByRole("row", { name: /Event S/ });
  await expect(row).toContainText("paid");
  await row.getByRole("link", { name: "Receipt" }).click();
  await expect(page.getByRole("heading", { name: "Receipt" })).toBeVisible();
  await expect(page.getByText("This receipt is not a tax invoice.")).toBeVisible();
});

test("the checkout needs a login and keeps the chosen plan", async ({ page, request }) => {
  await reset(request);
  await page.goto("/checkout?plan=event_l");
  await expect(page).toHaveURL(/\/login\?next=%2Fcheckout%3Fplan%3Devent_l/);
});
