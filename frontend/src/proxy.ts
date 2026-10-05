import { NextResponse, type NextRequest } from "next/server";

import { buildCsp, newNonce } from "@/lib/csp";

const PROTECTED = ["/events", "/admin", "/join", "/account", "/checkout"];
const STORAGE_ORIGIN = process.env.STORAGE_PUBLIC_ORIGIN ?? "http://localhost:8333";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // An app sign-in link opened in a browser: drop the token from the URL (and so from the
  // page, history and any later Referer) before rendering. The app intercepts these links
  // before any request is made, so this only affects browsers.
  if (pathname === "/m/signin" && search) {
    return NextResponse.redirect(new URL("/m/signin", request.url), 303);
  }

  // Optimistic check only: redirect visitors with no session cookies to /login.
  // Real authorization happens in the API on every request.
  const needsSession = PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const hasSession = request.cookies.has("ef_access") || request.cookies.has("ef_refresh");
  if (needsSession && !hasSession) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname + search);
    return NextResponse.redirect(login);
  }

  // Fresh nonce per request; Next.js reads it from the request CSP and tags its scripts.
  const nonce = newNonce();
  const csp = buildCsp(nonce, { dev: process.env.NODE_ENV === "development", storageOrigin: STORAGE_ORIGIN });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Every page (not the API proxy or static assets), so every HTML response gets a nonce CSP.
      source: "/((?!api|_next/static|_next/image|favicon.ico|mediapipe).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
