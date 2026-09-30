// Helpers for values that come from the network or the URL.

/** Own-property lookup: never returns inherited members such as Object.prototype. */
export function lookup<V>(table: Record<string, V>, key: string): V | undefined {
  return Object.hasOwn(table, key) ? table[key] : undefined;
}

/** True if `value` is one of the allowed literals (narrowing untrusted strings). */
export function oneOf<T extends string>(allowed: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value);
}

// Formats of values that come from the URL and end up in API request paths. Anything
// else is rejected before it can steer a fetch (e.g. "../../me" after decoding).
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SLUG = /^[a-z0-9-]{1,80}$/;
const TOKEN = /^[A-Za-z0-9_-]{10,200}$/;

export const isUuid = (v: unknown): v is string => typeof v === "string" && UUID.test(v);
export const isSlug = (v: unknown): v is string => typeof v === "string" && SLUG.test(v);
export const isToken = (v: unknown): v is string => typeof v === "string" && TOKEN.test(v);
