const SENTINEL = "https://sentinel.invalid";

/**
 * Only allow same-origin redirects (prevents open redirects via ?next=).
 *
 * String checks like "starts with / but not //" are not enough: browsers treat "\" as "/"
 * and strip tabs/newlines, so "/\evil.com" and "/\t/evil.com" become "//evil.com". We
 * resolve the value exactly as a browser would and rebuild it from the parsed parts.
 */
export function safeNext(next: string | string[] | undefined, fallback = "/events"): string {
  const value = Array.isArray(next) ? next[0] : next;
  if (!value || !value.startsWith("/")) return fallback;
  let url: URL;
  try {
    url = new URL(value, SENTINEL);
  } catch {
    return fallback;
  }
  if (url.origin !== SENTINEL) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Accepts a full join link (…/join/<slug>?code=…) or a bare slug. */
export function parseJoinLink(value: string): { slug: string; code: string } | null {
  const trimmed = value.trim();
  try {
    const url = new URL(trimmed);
    const slug = url.pathname.match(/\/join\/([^/]+)/)?.[1];
    return slug && /^[a-z0-9-]+$/.test(slug) ? { slug, code: url.searchParams.get("code") ?? "" } : null;
  } catch {
    return /^[a-z0-9-]+$/.test(trimmed) ? { slug: trimmed, code: "" } : null;
  }
}

/** Event slug from a slug or any EventFaces link (/join/<slug>, ?event=<slug>). */
export function slugFrom(value: string): string {
  const v = value.trim();
  let slug = v;
  try {
    const url = new URL(v);
    slug = url.searchParams.get("event") ?? url.pathname.match(/\/join\/([^/]+)/)?.[1] ?? "";
  } catch {
    // not a URL: treat as a slug
  }
  return /^[a-z0-9-]{1,80}$/.test(slug) ? slug : "";
}
