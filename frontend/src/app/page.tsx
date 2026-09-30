"use client";

import Link from "next/link";

import { useSession } from "@/components/session";

export default function Home() {
  const { user } = useSession();

  return (
    <section className="grid gap-12 py-10 md:grid-cols-[1.2fr_1fr] md:items-center">
      <div>
        <p className="mb-4 text-sm font-medium uppercase tracking-widest text-accent">Your event, your photos</p>
        <h1 className="font-display text-5xl leading-[1.05] tracking-tight text-ink md:text-6xl">
          Skip the scroll.
          <br />
          Find every photo of you.
        </h1>
        <p className="mt-6 max-w-md text-lg text-ink/70">
          Join your event, take one selfie, and see the photos you appear in. Your selfie is deleted the moment the
          search finishes.
        </p>
        <div className="mt-8 flex gap-3">
          {user ? (
            <Link href="/events" className="rounded-lg bg-ink px-5 py-3 font-medium text-paper hover:bg-ink/85">
              Go to my events
            </Link>
          ) : (
            <>
              <Link href="/signup" className="rounded-lg bg-ink px-5 py-3 font-medium text-paper hover:bg-ink/85">
                Create account
              </Link>
              <Link href="/login" className="rounded-lg border border-line bg-paper px-5 py-3 font-medium hover:bg-mist">
                Log in
              </Link>
            </>
          )}
        </div>
      </div>
      <ol className="space-y-4">
        {[
          ["Join", "Use the access code or QR link from the organizer."],
          ["Consent & selfie", "We explain exactly what is processed before any camera use."],
          ["Download", "Grab single photos or everything as a ZIP."],
        ].map(([title, text], i) => (
          <li key={title} className="flex gap-4 rounded-2xl border border-line bg-paper p-5">
            <span className="font-display text-3xl text-accent">{i + 1}</span>
            <span>
              <span className="block font-medium">{title}</span>
              <span className="text-sm text-ink/70">{text}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
