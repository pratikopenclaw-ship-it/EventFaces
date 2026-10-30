// Client-side API wrapper: same-origin fetch, CSRF header, one silent refresh on 401.

const CSRF_COOKIE = "ef_csrf";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body: unknown = null,
  ) {
    super(message);
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

async function csrfToken(): Promise<string> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing) return existing;
  const res = await fetch("/api/auth/csrf", { credentials: "same-origin" });
  const data = (await res.json()) as { csrf_token: string };
  return data.csrf_token;
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI validation errors
      return detail
        .map((d: { msg?: string; loc?: unknown[] }) => {
          const field = d.loc?.slice(1).join(".");
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  }
  return status === 429 ? "Too many attempts. Please wait and try again." : `Request failed (${status})`;
}

/** A raw (non-JSON) request body, e.g. the selfie image. */
export class RawBody {
  constructor(
    public data: Blob,
    public contentType: string,
    public headers: Record<string, string> = {},
  ) {}
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-CSRF-Token"] = await csrfToken();
  let payload: BodyInit | undefined;
  if (body instanceof RawBody) {
    Object.assign(headers, body.headers);
    headers["Content-Type"] = body.contentType;
    payload = body.data;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  return fetch(path, { method, headers, credentials: "same-origin", body: payload });
}

/** The API answers 403 + X-Required-Action when the current Terms of Use (or, for event
 * management, the Organizer Terms) haven't been accepted: show the acceptance page, then
 * come back here. */
function requireAcceptance(res: Response): void {
  const action = res.status === 403 ? res.headers.get("X-Required-Action") : null;
  if (!action || typeof window === "undefined" || window.location.pathname === "/legal/accept") return;
  const doc = action === "accept-organizer-terms" ? "organizer-terms" : "terms";
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/legal/accept?doc=${doc}&next=${encodeURIComponent(next)}`);
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  refreshing ??= send("POST", "/api/auth/refresh")
    .then((r) => r.ok)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res = await send(method, path, body);
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    if (await tryRefresh()) res = await send(method, path, body);
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  requireAcceptance(res);
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.status), data);
  return data as T;
}

export const get = <T>(path: string) => api<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => api<T>("POST", path, body);
export const patch = <T>(path: string, body?: unknown) => api<T>("PATCH", path, body);
export const put = <T>(path: string, body?: unknown) => api<T>("PUT", path, body);
export const del = <T>(path: string, body?: unknown) => api<T>("DELETE", path, body);

/** Start a browser download of a same-origin URL (the session cookie authorizes it). */
export function triggerDownload(url: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  // Same-origin, so honoured: download directly instead of navigating and then turning
  // the response into a download (Linux WebKit stopped after the first such navigation).
  // The file name still comes from the server's Content-Disposition.
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
