"use client";

import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { useSession } from "@/components/session";
import { patch } from "@/lib/api";
import { THEMES, themeAttribute, themeColorMetas, themeCookie, type ThemePref } from "@/lib/theme";

const LABELS: Record<ThemePref, string> = { system: "System", light: "Light", dark: "Dark" };
export const PHOTOS_NOTE = "Photos always display on a dark background.";

interface ThemeCtx {
  pref: ThemePref;
  setPref: (pref: ThemePref) => void;
  /** Last change, for the screen-reader announcement. */
  announcement: string;
}

const ThemeContext = createContext<ThemeCtx | null>(null);

function applyToDocument(pref: ThemePref, animate: boolean): void {
  const root = document.documentElement;
  if (animate) root.classList.add("theme-switching");
  const attr = themeAttribute(pref);
  if (attr) root.dataset.theme = attr;
  else delete root.dataset.theme;
  for (const m of document.head.querySelectorAll('meta[name="theme-color"]')) m.remove();
  for (const { color, media } of themeColorMetas(pref)) {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    meta.content = color;
    if (media) meta.media = media;
    document.head.appendChild(meta);
  }
  document.cookie = themeCookie(pref, location.protocol === "https:");
  if (animate) window.setTimeout(() => root.classList.remove("theme-switching"), 250);
}

/** `initial` comes from the ef_theme cookie on the server, so the first render matches the page. */
export function ThemeProvider({ initial, children }: { initial: ThemePref; children: ReactNode }) {
  const { user } = useSession();
  const [pref, setState] = useState<ThemePref>(initial);
  const [announcement, setAnnouncement] = useState("");

  // Signed in: the profile wins (it is what other devices see). Login already set the
  // cookie; this covers a change made on another device while this one stayed signed in.
  const profileTheme = user?.theme;
  useEffect(() => {
    if (profileTheme && profileTheme !== pref) {
      applyToDocument(profileTheme, true);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing from the session
      setState(profileTheme);
    }
    // Only when the profile value changes; local changes update the profile themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileTheme]);

  const setPref = useCallback(
    (next: ThemePref) => {
      applyToDocument(next, true);
      setState(next);
      setAnnouncement(`Theme set to ${LABELS[next]}`);
      if (user) {
        // The cookie already holds the choice; a failed save only loses cross-device sync.
        patch("/api/me/preferences", { theme: next }).catch((e) => console.error(e));
      }
    },
    [user],
  );

  return (
    <ThemeContext.Provider value={{ pref, setPref, announcement }}>
      {children}
      <span role="status" aria-live="polite" className="sr-only">
        {announcement}
      </span>
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}

export function ThemeIcon({ pref, className = "size-5" }: { pref: ThemePref; className?: string }) {
  const common = { className, fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, viewBox: "0 0 24 24", "aria-hidden": true };
  if (pref === "light") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    );
  }
  if (pref === "dark") {
    return (
      <svg {...common}>
        <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

/** Header button (sun / moon / monitor) with a three-option menu. */
export function ThemeMenu() {
  const { pref, setPref } = useTheme();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const wrapper = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    items.current[THEMES.indexOf(pref)]?.focus();
    function onDown(e: PointerEvent) {
      if (!wrapper.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
    // Focus the checked item only when the menu opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function close(refocus: boolean) {
    setOpen(false);
    if (refocus) button.current?.focus();
  }

  function onMenuKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = items.current.findIndex((el) => el === document.activeElement);
    const focus = (n: number) => items.current[(n + THEMES.length) % THEMES.length]?.focus();
    if (e.key === "ArrowDown") focus(i + 1);
    else if (e.key === "ArrowUp") focus(i - 1);
    else if (e.key === "Home") focus(0);
    else if (e.key === "End") focus(THEMES.length - 1);
    else if (e.key === "Escape") close(true);
    else if (e.key === "Tab") close(false);
    else return;
    if (e.key !== "Tab") e.preventDefault();
  }

  return (
    <div ref={wrapper} className="relative">
      <button
        ref={button}
        type="button"
        aria-label={`Theme: ${LABELS[pref]}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className="flex size-11 items-center justify-center rounded-lg text-muted hover:bg-mist hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <ThemeIcon pref={pref} />
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Theme"
          onKeyDown={onMenuKey}
          className="absolute right-0 z-40 mt-1 w-60 rounded-xl border border-line bg-paper p-1 shadow-lg"
        >
          {THEMES.map((t, i) => (
            <button
              key={t}
              ref={(el) => {
                items.current[i] = el;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={pref === t}
              tabIndex={-1}
              onClick={() => {
                setPref(t);
                close(true);
              }}
              className="flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm text-ink hover:bg-mist focus-visible:bg-mist focus-visible:outline-2 focus-visible:outline-accent aria-checked:font-medium"
            >
              <ThemeIcon pref={t} className="size-4" />
              <span className="flex-1">{LABELS[t]}</span>
              {pref === t && <span aria-hidden="true">✓</span>}
            </button>
          ))}
          <p className="border-t border-line px-3 py-2 text-xs text-muted">{PHOTOS_NOTE}</p>
        </div>
      )}
    </div>
  );
}

/** The same choice as a radio group, for the Account (settings) page. */
export function ThemeOptions() {
  const { pref, setPref } = useTheme();
  const noteId = useId();
  return (
    <fieldset aria-describedby={noteId}>
      <legend className="text-sm font-medium text-ink">Theme</legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {THEMES.map((t) => (
          <label
            key={t}
            className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-line px-3 text-sm text-ink has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-accent"
          >
            <input type="radio" name="theme" value={t} checked={pref === t} onChange={() => setPref(t)} className="size-4 accent-accent" />
            <ThemeIcon pref={t} className="size-4" />
            {LABELS[t]}
            {t === "system" && <span className="text-xs text-muted">(default)</span>}
          </label>
        ))}
      </div>
      <p id={noteId} className="mt-2 text-xs text-muted">
        {PHOTOS_NOTE}
      </p>
    </fieldset>
  );
}
