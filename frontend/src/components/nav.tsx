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
              <Link href="/events" className="rounded-lg px-3 py-2 text-ink/70 hover:bg-mist hover:text-ink">
                My events
              </Link>
              {isAdmin && (
                <Link href="/admin/events" className="rounded-lg px-3 py-2 text-ink/70 hover:bg-mist hover:text-ink">
                  Manage
                </Link>
              )}
              <Link href="/account" className="hidden rounded-lg px-3 py-2 text-ink/50 hover:bg-mist hover:text-ink sm:inline">
                {user.email}
              </Link>
              <Button variant="ghost" onClick={() => void logout()}>
                Log out
              </Button>
            </>
          ) : (
            <>
              <Link href="/login" className="rounded-lg px-3 py-2 text-ink/70 hover:bg-mist hover:text-ink">
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
