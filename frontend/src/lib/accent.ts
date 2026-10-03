// Per-event organizer accent colours, made readable in both themes.
//
// The accent is used as text (links, "Faces" in the logo), as a fill behind on-accent
// text (buttons, the capture ring) and for focus rings. For each theme we nudge the
// organizer's colour toward black (light theme) or white (dark theme) until it reaches
// 4.5:1 against every surface it sits on, then pick the on-accent text colour with the
// better contrast. The hue is kept; only lightness moves.

import type { CSSProperties } from "react";

import { contrast, mix } from "./contrast";

export const AA = 4.5;

/** Surfaces the accent is drawn on (keep in sync with globals.css). */
export const SURFACES = {
  light: ["#ffffff", "#f3f7f6", "#e7efed"],
  dark: ["#171a21", "#0f1115", "#1e222b"],
} as const;

const ON_ACCENT = ["#ffffff", "#06201c"] as const;

export interface AccentPair {
  accent: string;
  onAccent: string;
}

export function readableAccent(hex: string, theme: "light" | "dark"): AccentPair {
  const surfaces = SURFACES[theme];
  const target = theme === "light" ? "#000000" : "#ffffff";
  let accent = hex.toLowerCase();
  for (let step = 1; step <= 50 && Math.min(...surfaces.map((s) => contrast(accent, s))) < AA; step++) {
    accent = mix(target, hex, step / 50);
  }
  const onAccent = [...ON_ACCENT].sort((a, b) => contrast(b, accent) - contrast(a, accent))[0];
  return { accent, onAccent };
}

/** CSS custom properties for an `.event-accent` wrapper; undefined = the app's default accent. */
export function accentStyle(hex: string | null | undefined): CSSProperties | undefined {
  if (!hex || !/^#[0-9a-fA-F]{6}$/.test(hex)) return undefined;
  const light = readableAccent(hex, "light");
  const dark = readableAccent(hex, "dark");
  return {
    "--ev-accent-light": light.accent,
    "--ev-on-accent-light": light.onAccent,
    "--ev-accent-dark": dark.accent,
    "--ev-on-accent-dark": dark.onAccent,
  } as CSSProperties;
}
