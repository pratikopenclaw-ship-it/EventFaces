"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventAdmin } from "@/lib/types";

import { InvitesPanel } from "./invites-panel";

export function AccessPanel({ event, onChange }: { event: EventAdmin; onChange: (e: EventAdmin) => void }) {
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const link = `${origin}/join/${event.slug}?code=${event.access_code}`;
  const removalLink = `${origin}/removal-request?event=${event.slug}`;

  async function copy(label: string, text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(null), 1500);
  }

  async function rotate() {
    if (!confirm("Generate a new code? The old code and join link stop working immediately.")) return;
    try {
      onChange(await post<EventAdmin>(`/api/events/${event.id}/access-code/rotate`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rotate failed");
    }
  }

  const removalCard = (
    <Card className="md:col-span-2">
      <p className="font-medium">Removal-request link</p>
      <p className="mt-1 text-sm text-muted">
        Put this in your photo notice or privacy statement. Anyone who appears in the photos, including non-attendees,
        can ask for removal. Requests show up in the Moderation tab.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="break-all rounded-lg bg-mist px-3 py-2 font-mono text-xs">{removalLink}</span>
        <Button variant="secondary" onClick={() => void copy("removal", removalLink)}>
          {copied === "removal" ? "Copied" : "Copy"}
        </Button>
      </div>
    </Card>
  );

  if (event.join_mode === "invite") {
    return (
      <div className="grid gap-4">
        <InvitesPanel eventId={event.id} />
        {removalCard}
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {error && <Alert>{error}</Alert>}
      <Card>
        <p className="text-sm text-muted">Access code</p>
        <p className="my-3 font-mono text-4xl tracking-[0.2em]">{event.access_code}</p>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => void copy("code", event.access_code)}>
            {copied === "code" ? "Copied" : "Copy code"}
          </Button>
          <Button variant="ghost" onClick={() => void rotate()}>
            Rotate code
          </Button>
        </div>
      </Card>
      <Card>
        <p className="text-sm text-muted">Join link (includes the code)</p>
        <p className="my-3 break-all rounded-lg bg-mist px-3 py-2 font-mono text-sm">{link}</p>
        <Button variant="secondary" onClick={() => void copy("link", link)}>
          {copied === "link" ? "Copied" : "Copy link"}
        </Button>
      </Card>
      <Card className="flex flex-col items-center gap-4 md:col-span-2 md:flex-row md:items-center">
        {/* The ?v= busts the cache after the code is rotated. */}
        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
        <img
          src={`/api/events/${event.id}/qr?v=${event.access_code}`}
          alt="QR code for the join link"
          className="size-44 rounded-lg border border-line bg-white"
        />
        <div className="text-center md:text-left">
          <p className="font-medium">QR code</p>
          <p className="mt-1 max-w-sm text-sm text-muted">
            Print it on signs or slides. Scanning it opens the join page with the code filled in. Rotating the code
            invalidates printed QR codes.
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-2 md:justify-start">
            <Link
              href={`/admin/events/${event.id}/poster`}
              className="inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover"
            >
              Print poster or table cards
            </Link>
            <a
              href={`/api/events/${event.id}/qr?format=png&v=${event.access_code}`}
              className="inline-flex rounded-lg border border-line px-4 py-2 text-sm font-medium hover:bg-mist"
            >
              Download PNG
            </a>
          </div>
        </div>
      </Card>
      {removalCard}
    </div>
  );
}
