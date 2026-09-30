import type { NextConfig } from "next";

// The browser only talks to Next.js; /api/* is proxied to FastAPI so auth cookies
// stay first-party (SameSite) and the API is never exposed cross-origin.
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  output: "standalone", // slim production image (see Dockerfile "prod" stage)
  poweredByHeader: false,
  // Dev server only: lets the containerised Playwright run (Linux Firefox, see README
  // "Tests") load the app as http://web:3000 on the compose network. No effect on builds.
  allowedDevOrigins: ["web"],
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
          // The Content-Security-Policy (with a per-request nonce) is set in src/proxy.ts.
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
          ...(isProd ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;
