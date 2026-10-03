// Theme preference: "system" (follow the OS), "light" or "dark".
//
// How it is applied (no inline script, CSP untouched):
// - The ef_theme cookie holds the preference. The root layout reads it on the server and
//   renders <html data-theme="light|dark"> for an explicit choice, or no attribute for
//   "system", where globals.css falls back to @media (prefers-color-scheme: dark).
//   So the first paint is already right, and System follows OS changes live with no JS.
// - Signed-in users: the profile is the source of truth; the API sets ef_theme on login,
//   refresh and PATCH /api/me/preferences.

export const THEMES = ["system", "light", "dark"] as const;
export type ThemePref = (typeof THEMES)[number];

export const THEME_COOKIE = "ef_theme";

/** Browser-chrome colour per resolved theme (matches --color-paper, the header background). */
export const THEME_COLOR = { light: "#ffffff", dark: "#171a21" } as const;

/** Anything other than the three allowed values (missing, tampered) means "system". */
export function parseThemePref(value: string | null | undefined): ThemePref {
  return (THEMES as readonly string[]).includes(value ?? "") ? (value as ThemePref) : "system";
}

/** The `data-theme` attribute value: undefined for system (CSS media query decides). */
export function themeAttribute(pref: ThemePref): "light" | "dark" | undefined {
  return pref === "system" ? undefined : pref;
}

/** theme-color metas for a preference ("system" gets one per OS scheme). */
export function themeColorMetas(pref: ThemePref): { color: string; media?: string }[] {
  if (pref !== "system") return [{ color: THEME_COLOR[pref] }];
  return [
    { media: "(prefers-color-scheme: light)", color: THEME_COLOR.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLOR.dark },
  ];
}

export function themeCookie(pref: ThemePref, secure: boolean): string {
  return `${THEME_COOKIE}=${pref}; Path=/; Max-Age=${365 * 86400}; SameSite=Lax${secure ? "; Secure" : ""}`;
}
