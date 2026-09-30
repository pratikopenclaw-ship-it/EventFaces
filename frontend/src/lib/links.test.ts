import { describe, expect, it } from "vitest";

import { parseJoinLink, safeNext, slugFrom } from "./links";

/** Where a browser would actually navigate for `location.href = next` on our origin. */
const resolve = (next: string) => new URL(next, "https://eventfaces.example").origin;

describe("safeNext (post-login redirect)", () => {
  it.each(["/events", "/join/party-x7k2?code=ABCD2345", "/invite/tok_123", "/admin/events/1?tab=photos#top"])(
    "keeps same-origin path %s",
    (next) => expect(safeNext(next)).toBe(next),
  );

  it.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil.example", // browsers treat "\" like "/": becomes //evil.example
    "/\t/evil.example", // tabs/newlines are stripped by the URL parser
    "/\n/evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "",
  ])("never redirects off-site for %j", (next) => {
    const result = safeNext(next);
    expect(resolve(result)).toBe("https://eventfaces.example");
  });

  it("uses the fallback for missing or array values", () => {
    expect(safeNext(undefined)).toBe("/events");
    expect(resolve(safeNext(["//evil.example", "/events"]))).toBe("https://eventfaces.example");
  });
});

describe("parseJoinLink / slugFrom", () => {
  it("extracts slug and code from join links", () => {
    expect(parseJoinLink("https://x.example/join/party-x7k2?code=ABCD2345")).toEqual({ slug: "party-x7k2", code: "ABCD2345" });
    expect(parseJoinLink("  party-x7k2 ")).toEqual({ slug: "party-x7k2", code: "" });
  });
  it.each(["https://x.example/join/%2E%2E%2Fadmin", "https://x.example/other", "../../etc", "<script>", ""])(
    "rejects %j",
    (v) => expect(parseJoinLink(v)).toBeNull(),
  );
  it("slugFrom only returns safe slugs", () => {
    expect(slugFrom("https://x.example/removal-request?event=party-x7k2")).toBe("party-x7k2");
    expect(slugFrom("https://x.example/join/party-x7k2?code=A")).toBe("party-x7k2");
    expect(slugFrom("../../admin")).toBe("");
    expect(slugFrom("a".repeat(200))).toBe("");
  });
});
