import { describe, expect, it } from "vitest";

import { appIdFrom, buildAasa } from "./aasa";

describe("apple-app-site-association", () => {
  it("needs a real team and bundle id", () => {
    expect(appIdFrom("ABCDE12345", "app.eventfaces.ios")).toBe("ABCDE12345.app.eventfaces.ios");
    for (const [team, bundle] of [
      [undefined, "app.eventfaces.ios"],
      ["ABCDE12345", undefined],
      ["short", "app.eventfaces.ios"],
      ["abcde12345", "app.eventfaces.ios"],
      ["ABCDE12345", "bad bundle/../x"],
    ]) {
      expect(appIdFrom(team, bundle)).toBeNull();
    }
  });

  it("opens only the app's flows, never admin or API paths, and checks exclusions first", () => {
    const comps = buildAasa("ABCDE12345.app.eventfaces.ios").applinks.details[0].components;
    const paths = comps.map((c) => c["/"]);
    expect(paths).toEqual(["/admin/*", "/api/*", "/join/*", "/invite/*", "/m/signin", "/events/*"]);
    expect(comps.slice(0, 2).every((c) => "exclude" in c && c.exclude)).toBe(true);
    expect(comps.find((c) => c["/"] === "/m/signin")).toMatchObject({ "?": { t: "?*" } });
  });
});
