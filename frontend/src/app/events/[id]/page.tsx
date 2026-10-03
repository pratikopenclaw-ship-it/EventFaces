"use client";

import { notFound, useParams } from "next/navigation";

import { Alert, PageHeader, formatDate } from "@/components/ui";
import { accentStyle } from "@/lib/accent";
import { isUuid } from "@/lib/safe";
import type { EventPublic } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { FindPhotos } from "./find-photos";
import { GuestUpload } from "./guest-upload";

export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const valid = isUuid(id);
  const { data: event, error, loading } = useApi<EventPublic>(valid ? `/api/events/${id}` : null);
  if (!valid) notFound();

  if (loading) return <p className="text-sm text-muted">Loading…</p>;
  if (error || !event) {
    return <Alert>{error?.status === 403 ? "You don't have access to this event." : error?.message}</Alert>;
  }

  return (
    <div className={event.accent_color ? "event-accent" : undefined} style={accentStyle(event.accent_color)}>
      {event.has_logo && (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated API image
        <img src={`/api/events/${event.id}/logo`} alt={`${event.name} logo`} className="mb-4 h-14 w-auto" />
      )}
      <PageHeader title={event.name} subtitle={event.date ? formatDate(event.date) : undefined} />
      {event.description && <p className="-mt-4 mb-8 max-w-2xl whitespace-pre-line text-muted">{event.description}</p>}
      <div className="space-y-10">
        <FindPhotos event={event} />
        {/* Uploading doesn't need face-search consent: that consent covers the user's own selfie. */}
        {event.guest_upload_enabled && <GuestUpload event={event} />}
      </div>
    </div>
  );
}
