import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { accentStyle } from "@/lib/accent";

// An event's identity: a band in its accent colour, topped by a "contact sheet" pattern
// that is different for every event (seeded by its id). The pattern fades out before the
// title area, so the title always sits on solid accent (contrast as tested in accent.ts).

interface CoverEvent {
  id: string;
  name: string;
  date?: string | null;
  has_logo?: boolean;
  accent_color?: string | null;
}

/** Small deterministic PRNG (mulberry32) seeded from a string. */
function rng(seed: string): () => number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++)
    h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return () => {
    h = (h + 0x6d2b79f5) | 0;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function coverTiles(
  seed: string,
  count: number,
): { opacity: number; found: boolean }[] {
  const next = rng(seed);
  return Array.from({ length: count }, () => {
    const r = next();
    return { opacity: 0.06 + r * 0.16, found: next() < 0.07 };
  });
}

export function Pattern({
  seed,
  rows,
  className = "",
}: {
  seed: string;
  rows: number;
  className?: string;
}) {
  // Fixed tile size: wider screens get more columns, not bigger tiles. Enough tiles for the
  // widest page; the rest wrap into rows that the strip's fixed height clips away.
  const cols = 44;
  const fade: CSSProperties = {
    maskImage: "linear-gradient(to bottom, black 35%, transparent 100%)",
    WebkitMaskImage: "linear-gradient(to bottom, black 35%, transparent 100%)",
    gridTemplateColumns: "repeat(auto-fill, minmax(22px, 1fr))",
  };
  return (
    <div
      aria-hidden="true"
      data-volatile // differs per event by design: masked in visual baselines
      className={`grid content-start gap-1.5 overflow-hidden p-3 ${className}`}
      style={fade}
    >
      {coverTiles(seed, cols * rows).map((t, i) => (
        <span
          key={i}
          className={`aspect-[4/3] rounded-[3px] bg-on-accent ${t.found ? "outline outline-2 outline-offset-1 outline-on-accent" : ""}`}
          style={{ opacity: t.found ? 0.55 : t.opacity }}
        />
      ))}
    </div>
  );
}

function Logo({ event, size }: { event: CoverEvent; size: string }) {
  if (!event.has_logo) return null;
  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-xl bg-paper p-1.5 shadow-sm ${size}`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
      <img
        src={`/api/events/${event.id}/logo`}
        alt={`${event.name} logo`}
        className="max-h-full max-w-full object-contain"
      />
    </span>
  );
}

/** Full-width header of an event page. `children`: extra lines under the title. */
export function EventCover({
  event,
  subtitle,
  children,
  level = 1,
}: {
  event: CoverEvent;
  subtitle?: ReactNode;
  children?: ReactNode;
  level?: 1 | 2; // 2 where the page already has its own h1 (the join page)
}) {
  const Heading = level === 1 ? "h1" : "h2";
  return (
    <header
      className="event-accent relative mb-8 overflow-hidden rounded-3xl bg-accent text-on-accent"
      style={accentStyle(event.accent_color)}
      data-testid="event-cover"
    >
      <Pattern seed={event.id} rows={3} className="h-24 md:h-28" />
      <div className="flex items-end gap-4 px-6 pb-6 md:px-8 md:pb-8">
        <Logo event={event} size="size-16 md:size-20" />
        <div className="min-w-0">
          <Heading className="font-display text-4xl leading-tight tracking-tight break-words md:text-5xl">
            {event.name}
          </Heading>
          {subtitle && <p className="mt-1 text-sm">{subtitle}</p>}
          {children}
        </div>
      </div>
    </header>
  );
}

/** The top of an event card in lists: pattern strip in the event's colour, logo chip. */
export function EventCoverStrip({ event }: { event: CoverEvent }) {
  return (
    <div
      className="event-accent relative h-20 overflow-hidden bg-accent"
      style={accentStyle(event.accent_color)}
    >
      <Pattern seed={event.id} rows={2} className="h-20" />
      {event.has_logo && (
        <span className="absolute bottom-2 left-4">
          <Logo event={event} size="size-11" />
        </span>
      )}
    </div>
  );
}

/** An event in a list: cover strip, then name, details and badges. */
export function EventCard({
  event,
  href,
  meta,
  badges,
  action,
}: {
  event: CoverEvent;
  href: string;
  meta?: ReactNode;
  badges?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Link
      href={href}
      className="group block overflow-hidden rounded-2xl border border-line bg-paper transition hover:-translate-y-0.5 hover:border-ink/30 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:hover:translate-y-0"
    >
      <EventCoverStrip event={event} />
      <div className="p-5">
        <h2 className="font-display text-xl leading-snug break-words text-ink">
          {event.name}
        </h2>
        {meta && <p className="mt-1 text-sm text-muted">{meta}</p>}
        {badges && <div className="mt-3 flex flex-wrap gap-1.5">{badges}</div>}
        {action && (
          <p className="mt-4 text-sm font-medium text-ink group-hover:underline">
            {action}
          </p>
        )}
      </div>
    </Link>
  );
}
