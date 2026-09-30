"use client";

import Link from "next/link";

import { useSession } from "@/components/session";
import { Button } from "@/components/ui";

export function Nav() {
  const { user, logout } = useSession();
  const isAdmin = user?.role === "super_admin" || user?.role === "organizer";

  return (
    <header className="border-b border-line bg-paper/80 backdrop-blur">
      <nav className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
        <Link href="/" className="font-display text-xl tracking-tight text-ink">
          Event<span className="text-accent">Faces</span>
        </Link>
        <div className="flex items-center gap-1 text-sm">
          {user ? (
            <>
              <Link href="/events" className="whitespace-nowrap rounded-lg px-2.5 py-2 text-ink/70 hover:bg-mist hover:text-ink sm:px-3">
                My events
              </Link>
              {isAdmin && (
                <Link href="/admin/events" className="whitespace-nowrap rounded-lg px-2.5 py-2 text-ink/70 hover:bg-mist hover:text-ink sm:px-3">
                  Manage
                </Link>
              )}
              <Link href="/account" className="whitespace-nowrap rounded-lg px-2.5 py-2 text-ink/70 hover:bg-mist hover:text-ink sm:px-3">
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
              <Link href="/login" className="whitespace-nowrap rounded-lg px-2.5 py-2 text-ink/70 hover:bg-mist hover:text-ink sm:px-3">
                Log in
              </Link>
              <Link href="/signup" className="rounded-lg bg-ink px-3 py-2 font-medium text-paper hover:bg-ink/85">
                Sign up
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
