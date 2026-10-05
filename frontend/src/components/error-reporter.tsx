"use client";

// Uncaught browser errors (including React's uncaught render and hydration errors, which
// Next passes to `reportError`) go to the same-origin tunnel. The tunnel redacts again on
// the server; here we only cap how much one page can send.
// Listeners are installed when this module loads, before hydration, so hydration errors count.
const MAX_PER_PAGE = 5;

function install(): void {
  const w = window as Window & { __efErrorReporter?: true };
  if (w.__efErrorReporter) return;
  w.__efErrorReporter = true;
  const seen = new Set<string>();
  const send = (error: unknown) => {
    const e = error instanceof Error ? error : new Error(typeof error === "string" ? error : "Non-error rejection");
    const stack = e.stack ?? "";
    // Browser extensions inject scripts into every page: not our errors.
    if (/\b(?:chrome|moz|safari(?:-web)?)-extension:\/\//.test(stack)) return;
    const key = `${e.name}:${e.message}`;
    if (seen.has(key) || seen.size >= MAX_PER_PAGE) return;
    seen.add(key);
    void fetch("/monitoring", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: e.name, message: e.message, stack, path: window.location.pathname }),
      keepalive: true,
      credentials: "omit",
    }).catch(() => {});
  };
  window.addEventListener("error", (event) => send(event.error ?? event.message));
  window.addEventListener("unhandledrejection", (event) => send(event.reason));
}

if (typeof window !== "undefined") install();

export function ErrorReporter() {
  return null;
}
