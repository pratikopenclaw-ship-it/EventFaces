import type { Metadata } from "next";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { connection } from "next/server";

import { Nav } from "@/components/nav";
import { SessionProvider } from "@/components/session";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "EventFaces",
  description: "Find your photos from an event with a selfie.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Nonce-based CSP requires per-request (dynamic) rendering: a prerendered page can't
  // carry a per-request nonce.
  await connection();
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <SessionProvider>
          <Nav />
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10">{children}</main>
          <footer className="border-t border-line">
            <div className="mx-auto flex max-w-5xl flex-wrap gap-x-6 gap-y-2 px-4 py-6 text-xs text-ink/70">
              <Link href="/privacy" className="hover:text-ink">
                Privacy
              </Link>
              <Link href="/removal-request" className="hover:text-ink">
                In a photo? Request removal
              </Link>
            </div>
          </footer>
        </SessionProvider>
      </body>
    </html>
  );
}
