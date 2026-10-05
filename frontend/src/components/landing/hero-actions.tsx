"use client";

import Link from "next/link";

import { useSession } from "@/components/session";

const primary = "rounded-lg bg-accent px-5 py-3 font-medium text-on-accent hover:bg-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const secondary = "rounded-lg border border-line bg-paper px-5 py-3 font-medium text-ink hover:bg-mist focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

export function HeroActions() {
  const { user } = useSession();
  return (
    <div className="mt-8 flex flex-wrap gap-3">
      {user ? (
        <Link href="/events" className={primary}>
          Go to my events
        </Link>
      ) : (
        <Link href="/signup" className={primary}>
          Find my photos
        </Link>
      )}
      <a href="#pricing" className={secondary}>
        I&apos;m organizing an event
      </a>
    </div>
  );
}
