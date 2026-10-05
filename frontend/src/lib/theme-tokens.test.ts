import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { SURFACES } from "./accent";
import { contrast, mix } from "./contrast";
import { THEME_COLOR } from "./theme";

// design/tokens.json is the single source for web and iOS: the stylesheet must match it,
// and every text/background pair must reach 4.5:1 in both themes.
const tokens = JSON.parse(readFileSync(join(__dirname, "../../../design/tokens.json"), "utf8")) as Record<
  "light" | "dark",
  Record<string, string>
>;
const css = readFileSync(join(__dirname, "../app/globals.css"), "utf8");

// web name -> token name
const WEB: Record<string, string> = {
  ink: "text",
  paper: "surface",
  canvas: "bg",
  mist: "surface-2",
  line: "border",
  muted: "text-muted",
  accent: "accent",
  "accent-hover": "accent-hover",
  "on-accent": "on-accent",
  "accent-soft": "accent-soft",
  highlight: "highlight",
  alarm: "danger",
  leaf: "success",
  good: "success-text",
  bad: "danger-text",
  warn: "warning-text",
  "warn-tint": "warning-tint",
};

function cssTokens(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/--color-([a-z-]+):\s*(#[0-9a-f]{6})/g)].map((m) => [m[1], m[2]]));
}

const lightCss = cssTokens(/@theme\s*\{([^}]*)\}/.exec(css)![1]);
const darkBlocks = [
  /:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}/.exec(css)![1],
  /:root\[data-theme="dark"\],\s*\.theme-dark\s*\{([^}]*)\}/.exec(css)![1],
].map(cssTokens);

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? tsxFiles(path) : path.endsWith(".tsx") ? [path] : [];
  });
}

type Pair = [fg: string, bg: string];
const BACKGROUNDS = ["bg", "surface", "surface-2", "accent-soft"];
const PAIRS: Pair[] = [
  ...BACKGROUNDS.flatMap((bg): Pair[] => [
    ["text", bg],
    ["text-muted", bg],
    ["accent", bg],
    ["success", bg],
    ["danger", bg],
  ]),
  ["on-accent", "accent"], // primary buttons
  ["on-accent", "accent-hover"], // ... while hovered
  ["surface", "danger"], // danger buttons
  ["warning-text", "warning-tint"],
];

function failures(t: Record<string, string>): string[] {
  const out: string[] = [];
  const check = (name: string, fg: string, bg: string) => {
    const ratio = contrast(fg.toLowerCase(), bg.toLowerCase());
    if (ratio < 4.5) out.push(`${name}: ${ratio.toFixed(2)}`);
  };
  for (const [fg, bg] of PAIRS) check(`${fg} on ${bg}`, t[fg], t[bg]);
  // Tinted badges/alerts: the colour at 5-10 % over the surface.
  check("success-text on success/10", t["success-text"], mix(t.success.toLowerCase(), t.surface.toLowerCase(), 0.1));
  check("danger-text on danger/10", t["danger-text"], mix(t.danger.toLowerCase(), t.surface.toLowerCase(), 0.1));
  check("danger on danger/5", t.danger, mix(t.danger.toLowerCase(), t.surface.toLowerCase(), 0.05));
  check("success on success/5", t.success, mix(t.success.toLowerCase(), t.surface.toLowerCase(), 0.05));
  return out;
}

describe("design tokens", () => {
  it.each(["light", "dark"] as const)("the stylesheet's %s set equals design/tokens.json", (theme) => {
    const expected = Object.fromEntries(Object.entries(WEB).map(([web, tok]) => [web, tokens[theme][tok].toLowerCase()]));
    const actual = theme === "light" ? lightCss : darkBlocks[0];
    expect(actual).toEqual(expected);
  });

  it("repeats the identical dark set for the media query, data-theme and .theme-dark", () => {
    expect(darkBlocks[1]).toEqual(darkBlocks[0]);
  });

  it.each(["light", "dark"] as const)("every text/background pair is at least 4.5:1 in %s", (theme) => {
    expect(failures(tokens[theme])).toEqual([]);
  });

  it("highlight is decorative only: below 3:1 in light mode, so no component uses it as text or a status cue", () => {
    expect(contrast(tokens.light.highlight.toLowerCase(), tokens.light.bg.toLowerCase())).toBeLessThan(3);
    const offenders = tsxFiles(join(__dirname, "..")).filter((f) => /\b(text|border|ring|outline)-highlight\b/.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("keeps the accent surfaces and browser-chrome colours in sync with the tokens", () => {
    const lc = (t: Record<string, string>, k: string) => t[k].toLowerCase();
    expect(SURFACES.light).toEqual([lc(tokens.light, "surface"), lc(tokens.light, "bg"), lc(tokens.light, "surface-2")]);
    expect(SURFACES.dark).toEqual([lc(tokens.dark, "surface"), lc(tokens.dark, "bg"), lc(tokens.dark, "surface-2")]);
    expect(THEME_COLOR).toEqual({ light: lc(tokens.light, "surface"), dark: lc(tokens.dark, "surface") });
  });

  it("per-event accent fallbacks equal the default accents", () => {
    expect(css).toContain(`var(--ev-accent-light, ${tokens.light.accent.toLowerCase()})`);
    expect(css).toContain(`var(--ev-accent-dark, ${tokens.dark.accent.toLowerCase()})`);
    expect(css).toContain(`var(--ev-on-accent-light, ${tokens.light["on-accent"].toLowerCase()})`);
    expect(css).toContain(`var(--ev-on-accent-dark, ${tokens.dark["on-accent"].toLowerCase()})`);
  });

  it("disables the switch transition for reduced motion", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: no-preference\)\s*\{\s*html\.theme-switching/);
  });
});

describe("light island (.theme-light, printed material)", () => {
  it("repeats the light tokens exactly", () => {
    const island = cssTokens(/\n\.theme-light\s*\{([^}]*)\}/.exec(css)![1]);
    expect(island).toEqual(lightCss);
  });
});
