import { NextResponse, type NextRequest } from "next/server";

// Optimistic check only: redirect visitors with no session cookies to /login.
// Real authorization happens in the API on every request.
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has("ef_access") || request.cookies.has("ef_refresh");
  if (hasSession) return NextResponse.next();

  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/events/:path*", "/admin/:path*", "/join/:path*", "/account"],
};
