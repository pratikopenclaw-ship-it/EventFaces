// Error reports for the self-hosted GlitchTip (Sentry envelope protocol), without a
// third-party SDK: SDKs record breadcrumbs (clicks, console, URLs) on pages that hold
// selfies. A report carries only an error type, a redacted message, a stack and the page
// path, never query strings, cookies, emails or tokens. Browsers post to the same-origin
// tunnel `/monitoring`, so the DSN stays on the server and the CSP stays `connect-src 'self'`.

export const LIMITS = { type: 100, message: 500, stack: 8_000, path: 300, frames: 50 } as const;

// Paths whose last segment is a bearer secret (emailed links) or a capability (join links).
// Mirrors backend `core/logging.py`; `/join/` is added because a join slug admits anyone.
const SECRET_PATHS = [
  /(\/api\/downloads\/)[^/?#\s"'()]+/g,
  /(\/api\/invites\/)(?!accept\b|register\b)[^/?#\s"'()]+/g,
  /(\/api\/removal-requests\/)(?!event\/)[^/?#\s"'()]+/g,
  /(\/invite\/)[^/?#\s"'()]+/g,
  /(\/removal\/)[^/?#\s"'()]+/g,
  /(\/join\/)[^/?#\s"'()]+/g,
];
const SECRET_ASSIGNMENT = /\b(token|code|password|secret|signature|key)=([^&\s"',)]+)/gi;
const EMAIL = /[^\s@"'<>(),;:]+@[^\s@"'<>(),;:]+\.[a-z]{2,}/gi;
const BEARER = /\b(Bearer)\s+[A-Za-z0-9._~+/=-]+/g;
// Query strings and fragments of URLs inside free text.
const URL_QUERY = /((?:https?:\/\/|\/)[^\s?#"'()]*)[?#][^\s"'()]*/g;

export function redact(text: string): string {
  let out = text.replace(URL_QUERY, "$1");
  for (const pattern of SECRET_PATHS) out = out.replace(pattern, "$1[redacted]");
  return out.replace(SECRET_ASSIGNMENT, "$1=[redacted]").replace(EMAIL, "[email]").replace(BEARER, "$1 [redacted]");
}

/** A page path without query or fragment, secrets redacted. */
export function cleanPath(path: string): string {
  let p = path;
  try {
    p = new URL(path, "http://x").pathname;
  } catch {
    p = path.split(/[?#]/)[0];
  }
  return redact(p).slice(0, LIMITS.path);
}

export type Frame = { function?: string; filename: string; lineno?: number; colno?: number; in_app: boolean };

const CHROME_FRAME = /^at ([^()]*) \(([^()\s]+):(\d+):(\d+)\)$/;
const CHROME_ANON_FRAME = /^at ()([^()\s]+):(\d+):(\d+)$/;
const GECKO_FRAME = /^([^@\s]*)@(\S+):(\d+):(\d+)$/;

/** Chrome ("at fn (file:1:2)") and Firefox/Safari ("fn@file:1:2") stacks; oldest call first. */
export function parseStack(stack: string): Frame[] {
  const frames: Frame[] = [];
  for (const raw of stack.split("\n").slice(0, LIMITS.frames + 1)) {
    // Bounded line and non-overlapping character classes: no catastrophic backtracking.
    const line = raw.slice(0, 500).trim();
    const m = CHROME_FRAME.exec(line) ?? CHROME_ANON_FRAME.exec(line) ?? GECKO_FRAME.exec(line);
    if (!m) continue;
    const filename = redact(m[2]);
    frames.push({
      function: m[1] ? redact(m[1]).slice(0, 200) : undefined,
      filename: filename.slice(0, 300),
      lineno: Number(m[3]),
      colno: Number(m[4]),
      in_app: !/node_modules|\bnext\/dist\b/.test(filename),
    });
  }
  return frames.slice(0, LIMITS.frames).reverse();
}

export type Dsn = { endpoint: string; key: string };

/** `https://<key>@host[/path]/<project>` → the envelope endpoint. */
export function parseDsn(dsn: string | undefined): Dsn | null {
  if (!dsn) return null;
  try {
    const u = new URL(dsn);
    const parts = u.pathname.split("/").filter(Boolean);
    const project = parts.pop();
    if (!u.username || !project || !/^\d+$/.test(project) || !/^https?:$/.test(u.protocol)) return null;
    const prefix = parts.length ? `/${parts.join("/")}` : "";
    return { endpoint: `${u.protocol}//${u.host}${prefix}/api/${project}/envelope/`, key: u.username };
  } catch {
    return null;
  }
}

export type Report = {
  component: "web-browser" | "web-server";
  type: string;
  message: string;
  stack?: string;
  path?: string;
  tags?: Record<string, string>;
};

const REPORTS_PER_MINUTE = 60; // per server process; protects the GlitchTip quota from floods
let windowStart = 0;
let used = 0;

export function allowReport(now: number = Date.now()): boolean {
  if (now < windowStart || now - windowStart >= 60_000) {
    windowStart = now;
    used = 0;
  }
  return ++used <= REPORTS_PER_MINUTE;
}

function str(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

/** Accepts only the known fields, as strings within limits (input from browsers is untrusted). */
export function parseBrowserReport(body: unknown): Report | null {
  if (typeof body !== "object" || body === null) return null;
  const b = body as Record<string, unknown>;
  const message = str(b.message, LIMITS.message);
  const type = str(b.type, LIMITS.type) || "Error";
  if (!message && !b.stack) return null;
  return { component: "web-browser", type, message, stack: str(b.stack, LIMITS.stack), path: str(b.path, 2_000) };
}

export function buildEvent(report: Report, opts: { release: string; environment: string; eventId: string; now: Date }) {
  const frames = report.stack ? parseStack(report.stack) : [];
  return {
    event_id: opts.eventId,
    timestamp: opts.now.toISOString(),
    platform: "javascript",
    level: "error",
    logger: report.component,
    release: opts.release,
    environment: opts.environment,
    tags: { component: report.component, ...(report.tags ?? {}) },
    ...(report.path ? { request: { url: cleanPath(report.path) } } : {}),
    exception: {
      values: [
        {
          type: redact(report.type).slice(0, LIMITS.type),
          value: redact(report.message).slice(0, LIMITS.message),
          ...(frames.length ? { stacktrace: { frames } } : {}),
        },
      ],
    },
  };
}

export function buildEnvelope(event: { event_id: string; timestamp: string }): string {
  const header = JSON.stringify({ event_id: event.event_id, sent_at: event.timestamp });
  const payload = JSON.stringify(event);
  const item = JSON.stringify({ type: "event", content_type: "application/json", length: new TextEncoder().encode(payload).length });
  return `${header}\n${item}\n${payload}\n`;
}

/** Server side only: sends one report to the DSN from SENTRY_DSN. Never throws. */
export async function sendReport(report: Report, env: Record<string, string | undefined> = process.env): Promise<boolean> {
  const dsn = parseDsn(env.SENTRY_DSN);
  if (!dsn) return false;
  const event = buildEvent(report, {
    release: env.APP_VERSION || "dev",
    environment: env.ENVIRONMENT || "development",
    eventId: crypto.randomUUID().replaceAll("-", ""),
    now: new Date(),
  });
  try {
    const res = await fetch(dsn.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-sentry-envelope",
        "X-Sentry-Auth": `Sentry sentry_version=7, sentry_key=${dsn.key}, sentry_client=eventfaces-web/1`,
      },
      body: buildEnvelope(event),
      signal: AbortSignal.timeout(3_000),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}
