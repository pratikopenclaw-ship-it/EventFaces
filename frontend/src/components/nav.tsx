"use client";

import Link from "next/link";

import { useBranding } from "@/components/branding";
import { useSession } from "@/components/session";
import { ThemeMenu } from "@/components/theme";
import { Button } from "@/components/ui";

export function Nav() {
  const { user, logout } = useSession();
  const branding = useBranding();
  const isAdmin = user?.role === "super_admin" || user?.role === "organizer";

  return (
    // relative z-30: backdrop-blur makes the header a stacking context, so without its own
    // level the theme menu (z-40 inside it) would open underneath positioned page content.
    <header className="relative z-30 border-b border-line bg-paper/80 backdrop-blur print:hidden">
      <nav className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
        {branding ? (
          <Link href={`/events/${branding.eventId}`} className="flex items-center">
            {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image, not optimizable */}
            <img
              src={`/api/events/${branding.eventId}/logo`}
              alt="Event logo"
              className="h-9 max-w-40 object-contain"
            />
          </Link>
        ) : (
          <Link href="/" className="font-display text-xl tracking-tight text-ink">
            Event<span className="text-accent">Faces</span>
          </Link>
        )}
        <div className="flex items-center gap-0 text-sm sm:gap-1">
          {user ? (
            <>
              <Link href="/events" className="whitespace-nowrap rounded-lg px-2 py-2 text-muted hover:bg-mist hover:text-ink sm:px-3">
                My events
              </Link>
              {isAdmin && (
                <Link href="/admin/events" className="whitespace-nowrap rounded-lg px-2 py-2 text-muted hover:bg-mist hover:text-ink sm:px-3">
                  Manage
                </Link>
              )}
              <Link href="/account" className="whitespace-nowrap rounded-lg px-2 py-2 text-muted hover:bg-mist hover:text-ink sm:px-3">
                <span className="sm:hidden">Account</span>
                <span className="hidden sm:inline">{user.email}</span>
              </Link>
              {/* On phones there's no room for four items: Log out lives on the Account page. */}
              <span className="hidden sm:inline">
                <Button variant="ghost" onClick={() => void logout()}>
                  Log out
                </Button>
              </span>
            </>
          ) : (
            <>
              {/* Smallest phones: no room; the landing page's own section nav links to pricing. */}
              <Link href="/pricing" className="hidden whitespace-nowrap rounded-lg px-2 py-2 text-muted hover:bg-mist hover:text-ink min-[370px]:block sm:px-3">
                Pricing
              </Link>
              <Link href="/login" className="whitespace-nowrap rounded-lg px-2 py-2 text-muted hover:bg-mist hover:text-ink sm:px-3">
                Log in
              </Link>
              <Link href="/signup" className="rounded-lg bg-accent px-3 py-2 font-medium text-on-accent hover:bg-accent-hover">
                Sign up
              </Link>
            </>
          )}
          <ThemeMenu />
        </div>
      </nav>
    </header>
  );
}
