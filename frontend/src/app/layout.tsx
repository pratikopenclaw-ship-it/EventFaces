import type { Metadata, Viewport } from "next";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";
import Link from "next/link";
import { connection } from "next/server";

import { Nav } from "@/components/nav";
import { SessionProvider } from "@/components/session";
import { ThemeProvider } from "@/components/theme";
import {
  THEME_COOKIE,
  parseThemePref,
  themeAttribute,
  themeColorMetas,
  type ThemePref,
} from "@/lib/theme";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "EventFaces",
  description: "Find your photos from an event with a selfie.",
};

async function themePref(): Promise<ThemePref> {
  return parseThemePref((await cookies()).get(THEME_COOKIE)?.value);
}

// Browser chrome and native controls follow the saved theme from the first byte.
export async function generateViewport(): Promise<Viewport> {
  const pref = await themePref();
  return {
    themeColor: themeColorMetas(pref),
    colorScheme: pref === "system" ? "light dark" : pref,
  };
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Nonce-based CSP requires per-request (dynamic) rendering: a prerendered page can't
  // carry a per-request nonce.
  await connection();
  // Rendered from the cookie (no inline script): "system" leaves data-theme off and the
  // CSS media query decides, so the first paint is right in every mode.
  const pref = await themePref();
  return (
    <html
      lang="en"
      data-theme={themeAttribute(pref)}
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col font-sans">
        <SessionProvider>
          <ThemeProvider initial={pref}>
            <Nav />
            <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10">
              {children}
            </main>
            <footer className="border-t border-line">
              <div className="mx-auto flex max-w-5xl flex-wrap gap-x-6 gap-y-2 px-4 py-6 text-xs text-muted">
                <Link href="/privacy" className="hover:text-ink">
                  Privacy
                </Link>
                <Link href="/terms" className="hover:text-ink">
                  Terms
                </Link>
                <Link href="/removal-request" className="hover:text-ink">
                  In a photo? Request removal
                </Link>
              </div>
            </footer>
          </ThemeProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
