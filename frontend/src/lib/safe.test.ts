import { describe, expect, it } from "vitest";

import { reasonLabel } from "@/components/match-quality";
import { isRejection } from "@/app/events/[id]/find-photos";

import { isSlug, isToken, isUuid, lookup, oneOf } from "./safe";

describe("lookup / oneOf (network-derived keys)", () => {
  it("never returns inherited members", () => {
    const table: Record<string, string> = { a: "A" };
    expect(lookup(table, "a")).toBe("A");
    for (const k of ["__proto__", "constructor", "toString", "hasOwnProperty"]) expect(lookup(table, k)).toBeUndefined();
  });
  it("narrows only allowed literals", () => {
    expect(oneOf(["front", "left"] as const, "left")).toBe(true);
    expect(oneOf(["front", "left"] as const, "__proto__")).toBe(false);
    expect(oneOf(["front", "left"] as const, 3)).toBe(false);
  });
  it("reasonLabel falls back to the code for unknown/prototype keys", () => {
    expect(reasonLabel("too_blurry")).toBe("Blurry");
    expect(reasonLabel("__proto__")).toBe("__proto__");
    expect(reasonLabel("constructor")).toBe("constructor");
  });
  it("isRejection validates the 422 body before it drives state", () => {
    expect(isRejection({ detail: "x", code: "too_dark", shot: "left" })).toBe(true);
    expect(isRejection({ detail: "x", code: "too_dark", shot: "__proto__" })).toBe(false);
    expect(isRejection({ detail: "x", code: 1, shot: "left" })).toBe(false);
    expect(isRejection(null)).toBe(false);
  });
});

describe("URL param formats", () => {
  it.each([
    [isUuid, "07756566-a151-4d6d-ac4a-8a3b58f69e64", true],
    [isUuid, "../../me", false],
    [isUuid, "07756566-a151-4d6d-ac4a-8a3b58f69e64/../x", false],
    [isSlug, "summer-party-x7k2", true],
    [isSlug, "..", false],
    [isSlug, "a/b", false],
    [isToken, `test_token-${"a".repeat(32)}`, true], // synthetic: same shape as a real token
    [isToken, "../../auth/logout", false],
    [isToken, "short", false],
  ] as const)("%o(%j) = %s", (fn, v, ok) => expect(fn(v)).toBe(ok));
});
