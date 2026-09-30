import { describe, expect, it } from "vitest";

import { joinNext } from "./links";

describe("joinNext (UX-003)", () => {
  it.each([
    ["/join/demo-party-2u6m7p", "/join/demo-party-2u6m7p"],
    ["/join/demo-party-2u6m7p?code=URPHP25E", "/join/demo-party-2u6m7p?code=URPHP25E"],
    [["/join/a-b-c"], "/join/a-b-c"],
  ])("keeps join destinations: %s", (input, out) => expect(joinNext(input)).toBe(out));

  it.each([
    undefined,
    "",
    "/events",
    "https://evil.example/join/x",
    "//evil.example/join/x",
    "/join/../admin",
    "/join/x?code=A&next=//evil",
    "javascript:alert(1)",
    "/join/UPPER",
    "/join/x?code=A?b",
    "/join/x?code=A#frag",
  ])("drops anything else: %s", (input) => expect(joinNext(input)).toBeNull());
});
