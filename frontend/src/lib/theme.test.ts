import { describe, expect, it } from "vitest";

import { AA, SURFACES, accentStyle, readableAccent } from "./accent";
import { contrast, parseHex } from "./contrast";
import { parseThemePref, themeAttribute, themeColorMetas, themeCookie } from "./theme";

describe("theme preference", () => {
  it("accepts only system, light and dark", () => {
    expect(parseThemePref("light")).toBe("light");
    expect(parseThemePref("dark")).toBe("dark");
    expect(parseThemePref("system")).toBe("system");
    for (const bad of [undefined, null, "", "Dark", "purple", 'dark"><script>', "dark; Path=/"]) {
      expect(parseThemePref(bad)).toBe("system");
    }
  });

  it("renders data-theme only for an explicit choice", () => {
    expect(themeAttribute("system")).toBeUndefined();
    expect(themeAttribute("dark")).toBe("dark");
  });

  it("gives System one theme-color per OS scheme", () => {
    expect(themeColorMetas("system").map((m) => m.media)).toEqual(["(prefers-color-scheme: light)", "(prefers-color-scheme: dark)"]);
    expect(themeColorMetas("dark")).toEqual([{ color: "#171a21" }]);
  });

  it("writes a first-party, Lax, script-readable cookie", () => {
    const c = themeCookie("dark", true);
    expect(c).toMatch(/^ef_theme=dark; Path=\/; Max-Age=\d+; SameSite=Lax; Secure$/);
    expect(c).not.toMatch(/HttpOnly|Domain/i);
    expect(themeCookie("light", false)).not.toContain("Secure");
  });
});

describe("per-event accent", () => {
  const samples = ["#0b6e64", "#ffff00", "#ffffff", "#000000", "#808080", "#ff00ff", "#00ffff", "#1e3a8a", "#f97316", "#7dd3fc", "#b91c1c", "#22c55e"];

  it.each(samples)("%s is readable in both themes", (hex) => {
    for (const theme of ["light", "dark"] as const) {
      const { accent, onAccent } = readableAccent(hex, theme);
      for (const surface of SURFACES[theme]) expect(contrast(accent, surface)).toBeGreaterThanOrEqual(AA);
      expect(contrast(onAccent, accent)).toBeGreaterThanOrEqual(AA);
    }
  });

  it("leaves an already readable colour alone", () => {
    expect(readableAccent("#0b6e64", "light").accent).toBe("#0b6e64");
  });

  it("keeps the hue (only lightness moves)", () => {
    const [r, g, b] = parseHex(readableAccent("#f97316", "light").accent);
    expect(r).toBeGreaterThan(g);
    expect(g).toBeGreaterThan(b);
  });

  it("ignores anything that isn't #rrggbb (it ends up in a style attribute)", () => {
    for (const bad of [null, undefined, "", "red", "#fff", "url(x)", "#123456;color:red", "expression(1)"]) {
      expect(accentStyle(bad)).toBeUndefined();
    }
    expect(Object.keys(accentStyle("#123456")!)).toEqual([
      "--ev-accent-light",
      "--ev-on-accent-light",
      "--ev-accent-dark",
      "--ev-on-accent-dark",
    ]);
  });
});
