import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/monitoring/route";
import {
  allowReport,
  buildEnvelope,
  buildEvent,
  cleanPath,
  parseBrowserReport,
  parseDsn,
  parseStack,
  redact,
  sendReport,
} from "@/lib/error-report";

const SECRETS = ["INVTOKEN", "RMTOKEN", "DLTOKEN", "JOINSLUG", "QUERYSECRET", "alice@example.com", "eyJhbGciOi", "pw123", "FRAGMENT"];

describe("redact", () => {
  it("removes tokens, capabilities, query strings, emails and bearer tokens", () => {
    const text = [
      "GET https://x.example/invite/INVTOKEN failed",
      "/removal/RMTOKEN",
      "fetch /api/downloads/DLTOKEN",
      "at /join/JOINSLUG",
      "https://x.example/reset-password?token=QUERYSECRET#FRAGMENT",
      "user alice@example.com",
      "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.x.y",
      "password=pw123",
    ].join("\n");
    const clean = redact(text);
    for (const s of SECRETS) expect(clean).not.toContain(s);
    expect(clean).toContain("/invite/[redacted]");
    expect(clean).toContain("https://x.example/reset-password");
  });

  it("keeps the non-secret API routes readable", () => {
    expect(redact("/api/invites/accept")).toBe("/api/invites/accept");
    expect(redact("/api/removal-requests/event/abc")).toBe("/api/removal-requests/event/abc");
    expect(redact("TypeError: x is undefined")).toBe("TypeError: x is undefined");
  });

  it("cleans page paths", () => {
    expect(cleanPath("/invite/INVTOKEN?next=/events#top")).toBe("/invite/[redacted]");
    expect(cleanPath("/events/123?photo=4")).toBe("/events/123");
  });
});

describe("parseStack", () => {
  it("reads Chrome and Firefox/Safari stacks, oldest call first, without query strings", () => {
    const chrome = "Error: boom\n    at inner (http://localhost:3000/_next/static/chunks/app.js?v=QUERYSECRET:10:5)\n    at outer (http://localhost:3000/_next/static/chunks/main.js:20:7)";
    const frames = parseStack(chrome);
    expect(frames.map((f) => f.function)).toEqual(["outer", "inner"]);
    expect(frames[1]).toMatchObject({ lineno: 10, colno: 5, filename: "http://localhost:3000/_next/static/chunks/app.js" });
    // Firefox/Safari frames are "function@url:line:col".
    const origin = "http://localhost:3000";
    const firefox = [`inner@${origin}/join/JOINSLUG/a.js:1:2`, `outer@${origin}/b.js:3:4`].join("\n");
    expect(parseStack("Error\n    at http://x/anon.js:7:8")[0]).toMatchObject({ function: undefined, filename: "http://x/anon.js", lineno: 7 });
    const ff = parseStack(firefox);
    expect(ff.map((f) => f.function)).toEqual(["outer", "inner"]);
    expect(JSON.stringify(ff)).not.toContain("JOINSLUG");
  });

  it("caps the number of frames", () => {
    const long = Array.from({ length: 200 }, (_, i) => `    at f${i} (http://x/a.js:${i + 1}:1)`).join("\n");
    expect(parseStack(long).length).toBeLessThanOrEqual(50);
  });
});

describe("parseDsn", () => {
  it("builds the envelope endpoint", () => {
    expect(parseDsn("https://abc@errors.example.com/3")).toEqual({ endpoint: "https://errors.example.com/api/3/envelope/", key: "abc" });
    expect(parseDsn("http://k@api:8000/__e2e/glitchtip/1")).toEqual({ endpoint: "http://api:8000/__e2e/glitchtip/api/1/envelope/", key: "k" });
  });

  it("refuses anything else", () => {
    for (const bad of [undefined, "", "not a url", "https://errors.example.com/3", "https://k@errors.example.com/x", "ftp://k@h/1"]) {
      expect(parseDsn(bad)).toBeNull();
    }
  });
});

describe("parseBrowserReport", () => {
  it("keeps only known string fields within limits", () => {
    const r = parseBrowserReport({ type: "TypeError", message: "m".repeat(5_000), stack: 1, path: "/x", cookie: "ef_access=jwt", user: "alice@example.com" });
    expect(r).toEqual({ component: "web-browser", type: "TypeError", message: "m".repeat(500), stack: "", path: "/x" });
  });

  it("rejects empty or non-object bodies", () => {
    for (const bad of [null, "x", 1, [], {}, { type: "Error" }]) expect(parseBrowserReport(bad)).toBeNull();
  });
});

describe("buildEvent and envelope", () => {
  it("contains only redacted fields", () => {
    const event = buildEvent(
      { component: "web-browser", type: "Error", message: "failed /invite/INVTOKEN for alice@example.com", stack: "at f (http://x/removal/RMTOKEN:1:2)", path: "/join/JOINSLUG?code=QUERYSECRET" },
      { release: "v1.2.3", environment: "production", eventId: "a".repeat(32), now: new Date(0) },
    );
    const envelope = buildEnvelope(event);
    for (const s of SECRETS) expect(envelope).not.toContain(s);
    expect(Object.keys(event).sort()).toEqual(["environment", "event_id", "exception", "level", "logger", "platform", "release", "request", "tags", "timestamp"]);
    expect(event.request).toEqual({ url: "/join/[redacted]" });
    const [header, item, payload] = envelope.trim().split("\n");
    expect(JSON.parse(header).event_id).toBe("a".repeat(32));
    expect(JSON.parse(item).length).toBe(new TextEncoder().encode(payload).length);
  });
});

describe("sendReport and the /monitoring tunnel", () => {
  afterEach(() => vi.unstubAllGlobals());

  function request(body: unknown, headers: Record<string, string> = { "sec-fetch-site": "same-origin" }) {
    return new Request("http://localhost:3000/monitoring", { method: "POST", headers: { "content-type": "application/json", ...headers }, body: typeof body === "string" ? body : JSON.stringify(body) });
  }

  it("is off without a DSN", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(await sendReport({ component: "web-server", type: "Error", message: "x" }, {})).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends a redacted envelope to the DSN endpoint only", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const ok = await sendReport(
      { component: "web-server", type: "Error", message: "boom token=QUERYSECRET", path: "/invite/INVTOKEN" },
      { SENTRY_DSN: "https://pub@errors.example.com/7", APP_VERSION: "v9", ENVIRONMENT: "production" },
    );
    expect(ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://errors.example.com/api/7/envelope/");
    expect(String((init.headers as Record<string, string>)["X-Sentry-Auth"])).toContain("sentry_key=pub");
    for (const s of SECRETS) expect(String(init.body)).not.toContain(s);
    expect(String(init.body)).toContain('"release":"v9"');
  });

  it("refuses cross-site, oversized and malformed posts", async () => {
    vi.stubGlobal("fetch", vi.fn());
    expect((await POST(request({ message: "x" }, { "sec-fetch-site": "cross-site" }))).status).toBe(403);
    expect((await POST(request({ message: "x" }, {}))).status).toBe(403);
    expect((await POST(request({ message: "x" }, { origin: "http://evil.example", host: "localhost:3000" }))).status).toBe(403);
    expect((await POST(request({ message: "x" }, { "sec-fetch-site": "same-site", origin: "http://localhost:3000", host: "localhost:3000" }))).status).toBe(403);
    expect((await POST(request({ message: "x" }, { origin: "null", host: "localhost:3000" }))).status).toBe(403);
    expect((await POST(request({ message: "x" }, { origin: "http://localhost:3000", host: "localhost:3000" }))).status).toBe(204);
    expect((await POST(request({ message: "x".repeat(20_000) }))).status).toBe(413);
    expect((await POST(request("{not json"))).status).toBe(400);
    expect((await POST(request({ nothing: true }))).status).toBe(400);
    expect((await POST(request({ message: "fine" }))).status).toBe(204);
  });

  it("limits reports per minute", () => {
    const t = 10_000_000;
    let allowed = 0;
    for (let i = 0; i < 100; i++) if (allowReport(t)) allowed++;
    expect(allowed).toBe(60);
    expect(allowReport(t + 60_000)).toBe(true);
  });
});
