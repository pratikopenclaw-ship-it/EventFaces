import type { NextConfig } from "next";

// The browser only talks to Next.js; /api/* is proxied to FastAPI so auth cookies
// stay first-party (SameSite) and the API is never exposed cross-origin.
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
// Browsers PUT guest uploads straight to object storage, so CSP must allow that origin.
const storageOrigin = process.env.STORAGE_PUBLIC_ORIGIN ?? "http://localhost:8333";
const isProd = process.env.NODE_ENV === "production";

const csp = [
  "default-src 'self'",
  // Next.js injects inline bootstrap scripts; dev mode also needs eval for HMR.
  // 'wasm-unsafe-eval' lets MediaPipe (self-hosted) compile its WebAssembly.
  `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${storageOrigin}${isProd ? "" : " ws:"}`,
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone", // slim production image (see Dockerfile "prod" stage)
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
          { key: "Content-Security-Policy", value: csp },
          ...(isProd ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;
