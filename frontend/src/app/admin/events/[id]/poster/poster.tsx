"use client";

import Link from "next/link";
import { useState, type CSSProperties, type ReactNode } from "react";

import { Pattern } from "@/components/event-cover";
import { Alert, Button, formatDate } from "@/components/ui";
import { accentStyle } from "@/lib/accent";
import { isUuid } from "@/lib/safe";
import type { EventAdmin } from "@/lib/types";
import { useApi } from "@/lib/use-api";

// Printable join material in the event's colours: one A4 poster, or four table cards per
// A4 sheet. Sizes are container units (cqw), so the preview is the print, scaled.
// Always light (.theme-light): it ends up on paper.

type Layout = "poster" | "cards";

const groupCode = (code: string) => code.replace(/(.{4})(?=.)/g, "$1 ");

export function Poster({ id }: { id: string }) {
  const valid = isUuid(id);
  const { data: event, error } = useApi<EventAdmin>(valid ? `/api/events/${id}/admin` : null);
  const [layout, setLayout] = useState<Layout>("poster");

  if (!valid) return <Alert>This event doesn&apos;t exist.</Alert>;
  if (error) return <Alert>{error.status === 403 ? "You don't manage this event." : error.message}</Alert>;
  if (!event) return <p className="text-sm text-muted">Loading…</p>;
  if (event.join_mode !== "code") {
    return <Alert kind="info">This event is invite-only: attendees use their personal links, so there is no QR code to print.</Alert>;
  }

  const joinUrl = `${window.location.origin}/join/${event.slug}`;
  const qr = `/api/events/${event.id}/qr?v=${event.access_code}`;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <div>
          <h1 className="font-display text-3xl tracking-tight text-ink">Print the QR code</h1>
          <p className="mt-1 text-sm text-muted">
            For the entrance or the tables. Print on A4; your browser&apos;s print dialog can also save a PDF.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="radiogroup" aria-label="Layout" className="flex rounded-full border border-line bg-paper p-1">
            {(["poster", "cards"] as const).map((l) => (
              <button
                key={l}
                type="button"
                role="radio"
                aria-checked={layout === l}
                onClick={() => setLayout(l)}
                className="rounded-full px-3 py-1.5 text-sm font-medium text-muted hover:text-ink aria-checked:bg-accent aria-checked:text-on-accent"
              >
                {l === "poster" ? "Poster" : "4 table cards"}
              </button>
            ))}
          </div>
          <Button onClick={() => window.print()}>Print</Button>
          <Link href={`/admin/events/${event.id}?tab=access`} className="rounded-lg px-3 py-2 text-sm text-muted hover:bg-mist hover:text-ink">
            Back
          </Link>
        </div>
      </div>

      <div className="theme-light flex justify-center">
        <Sheet event={event}>
          {layout === "poster" ? (
            <PosterLayout event={event} qr={qr} joinUrl={joinUrl} />
          ) : (
            <div className="grid h-full grid-cols-2 grid-rows-2">
              {[0, 1, 2, 3].map((i) => (
                <TableCard key={i} event={event} qr={qr} />
              ))}
            </div>
          )}
        </Sheet>
      </div>
    </div>
  );
}

function Sheet({ event, children }: { event: EventAdmin; children: ReactNode }) {
  return (
    <div
      data-testid="poster-sheet"
      className="event-accent aspect-[210/297] w-full max-w-[620px] overflow-hidden bg-paper text-ink shadow-xl ring-1 ring-line print:aspect-auto print:h-[297mm] print:w-[210mm] print:max-w-none print:shadow-none print:ring-0"
      style={{ ...accentStyle(event.accent_color), containerType: "inline-size" } as CSSProperties}
    >
      {children}
    </div>
  );
}

function Logo({ event, size }: { event: EventAdmin; size: string }) {
  if (!event.has_logo) return null;
  return (
    <span className="flex shrink-0 items-center justify-center rounded-[1.5cqw] bg-paper p-[0.8cqw]" style={{ width: size, height: size }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
      <img src={`/api/events/${event.id}/logo`} alt="" className="max-h-full max-w-full object-contain" />
    </span>
  );
}

function PosterLayout({ event, qr, joinUrl }: { event: EventAdmin; qr: string; joinUrl: string }) {
  return (
    <div className="flex h-full flex-col">
      <div className="relative bg-accent text-on-accent">
        <Pattern seed={event.id} rows={3} className="h-[16cqw]" />
        <div className="flex items-end gap-[3cqw] px-[7cqw] pb-[6cqw]">
          <Logo event={event} size="14cqw" />
          <div className="min-w-0">
            <p className="font-display leading-tight break-words" style={{ fontSize: "7.5cqw" }}>
              {event.name}
            </p>
            {event.date && <p style={{ fontSize: "2.6cqw" }}>{formatDate(event.date)}</p>}
          </div>
        </div>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center px-[8cqw] text-center">
        <p className="font-display leading-none tracking-tight" style={{ fontSize: "9cqw" }}>
          Find your photos
        </p>
        <p className="mt-[2cqw] text-muted" style={{ fontSize: "2.8cqw" }}>
          Scan with your phone camera, take a quick selfie, and see every photo you&apos;re in.
        </p>
        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image (QR of the join link) */}
        <img src={qr} alt={`QR code to join ${event.name}`} className="mt-[5cqw] rounded-[2cqw] ring-1 ring-line" style={{ width: "46cqw" }} />
        <ol className="mt-[5cqw] flex justify-center gap-[5cqw]" style={{ fontSize: "2.6cqw" }}>
          {["Scan the code", "Take a selfie", "Get your photos"].map((step, i) => (
            <li key={step} className="flex items-center gap-[1.4cqw]">
              <span className="flex items-center justify-center rounded-full bg-accent font-semibold text-on-accent" style={{ width: "4.6cqw", height: "4.6cqw" }}>
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </div>

      <div className="border-t border-line px-[7cqw] py-[3.5cqw] text-center text-muted" style={{ fontSize: "2.2cqw" }}>
        <p>
          No camera app? Open <span className="font-medium text-ink">{joinUrl}</span> and enter the code{" "}
          <span className="font-mono font-semibold tracking-wider text-ink">{groupCode(event.access_code)}</span>
        </p>
        <p className="mt-[1cqw]">EventFaces · Your selfie is never stored.</p>
      </div>
    </div>
  );
}

function TableCard({ event, qr }: { event: EventAdmin; qr: string }) {
  return (
    // Dashed edge: where to cut. Each card is A6.
    <div className="flex flex-col overflow-hidden border border-dashed border-line">
      <div className="bg-accent px-[3.5cqw] py-[2.5cqw] text-on-accent">
        <p className="truncate font-display leading-tight" style={{ fontSize: "3.6cqw" }}>
          {event.name}
        </p>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-[1.8cqw] p-[3cqw] text-center">
        <p className="font-display leading-none" style={{ fontSize: "5.2cqw" }}>
          Find your photos
        </p>
        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
        <img src={qr} alt={`QR code to join ${event.name}`} style={{ width: "33cqw" }} />
        <p className="text-muted" style={{ fontSize: "2cqw" }}>
          Scan, take a selfie, done. Code{" "}
          <span className="font-mono font-semibold text-ink">{groupCode(event.access_code)}</span>
        </p>
      </div>
    </div>
  );
}
