import { expect, test } from "@playwright/test";

import { lastMail, reset } from "./support";

test("the section nav jumps to each section and marks where you are @xb", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "On this page" });
  for (const [label, heading] of [
    ["Privacy", "Faces are biometric data. We treat them that way."],
    ["FAQ", "Questions people ask"],
    ["Contact", "Talk to us"],
  ] as const) {
    await nav.getByRole("link", { name: label }).click();
    await expect(page.getByRole("heading", { name: heading })).toBeInViewport();
    await expect(nav.getByRole("link", { name: label })).toHaveAttribute("aria-current", "true");
  }
  await expect(nav).toBeInViewport(); // sticky
});

test("FAQ answers open and close", async ({ page }) => {
  await page.goto("/#faq");
  const question = page.getByText("What happens to my selfie?");
  const answer = page.getByText(/used for one search and discarded/);
  await expect(answer).toBeHidden();
  await question.click();
  await expect(answer).toBeVisible();
  await question.click();
  await expect(answer).toBeHidden();
});

test("a contact message reaches the operator by email", async ({ page, request }) => {
  await reset(request);
  await page.goto("/#contact");
  await page.getByLabel("Your name").fill("Dana Organizer");
  await page.getByLabel("Email").fill("dana@example.com");
  await page.getByLabel("What is it about?").selectOption("organizer");
  await page.getByLabel("Message").fill("We run ten weddings a year. Can we try it?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Thanks, your message is on its way.")).toBeVisible();
  const mail = await lastMail(request, "hello@eventfaces.example");
  expect(mail.subject).toContain("Organizing an event");
  expect(mail.body).toContain("We run ten weddings a year.");
});

test("choosing a plan on the landing page leads to the checkout", async ({ page, request }) => {
  await reset(request);
  await page.goto("/#pricing");
  await page.getByRole("radio", { name: "Monthly" }).click();
  await page.getByRole("link", { name: "Subscribe" }).click();
  await expect(page).toHaveURL(/\/login\?next=%2Fcheckout%3Fplan%3Dpro/);
});
