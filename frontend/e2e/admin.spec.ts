import { expect, test } from "@playwright/test";

import { API, FOLDER, PASSWORD, reset } from "./support";

test("admin logs in, creates an event and syncs Drive (mocked Drive API)", async ({ page, request }) => {
  await reset(request);
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@e2e.test");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/events/);

  await page.goto("/admin/events/new");
  await page.getByLabel("Event name").fill("Summer Gala");
  await page.getByLabel("Google Drive folder").fill(`https://drive.google.com/drive/folders/${FOLDER}`);
  await page.getByRole("button", { name: "Create event" }).click();
  await expect(page).toHaveURL(/\/admin\/events\/[0-9a-f-]{36}\?tab=access/);
  const id = page.url().match(/events\/([0-9a-f-]{36})/)![1];

  await page.getByRole("tab", { name: "Photos" }).click();
  await page.getByRole("button", { name: "Sync now" }).click();
  await expect
    .poll(async () => (await (await page.request.get(`/api/events/${id}/sync`)).json()).published_photos, { timeout: 90_000 })
    .toBe(3);
  await page.reload();
  await page.getByRole("tab", { name: "Photos" }).click();
  await expect(page.getByText("Published photos")).toBeVisible();
  await expect(page.getByRole("img", { name: "left.jpg" })).toBeVisible();
  expect((await request.get(`${API}/api/health`)).ok()).toBeTruthy();
});
