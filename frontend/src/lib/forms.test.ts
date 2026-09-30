import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? tsxFiles(path) : path.endsWith(".tsx") ? [path] : [];
  });
}

describe("forms", () => {
  // Without method="post", a submit before hydration (slow network, JS error) falls back to a
  // native GET and puts passwords/emails in the URL, browser history and server logs.
  it("every <form> declares method=\"post\"", () => {
    const offenders = tsxFiles(join(__dirname, "..")).flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(/<form\b[^>]*>/g)]
        .filter((m) => !/\bmethod="post"/.test(m[0]))
        .map((m) => `${file}: ${m[0]}`),
    );
    expect(offenders).toEqual([]);
  });
});
