"use client";

import { notFound, useParams } from "next/navigation";

import { useSetEventBranding } from "@/components/branding";
import { EventCover } from "@/components/event-cover";
import { Alert, formatDate } from "@/components/ui";
import { accentStyle } from "@/lib/accent";
import { isUuid } from "@/lib/safe";
import type { EventPublic } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { FindPhotos } from "./find-photos";
import { GuestUpload } from "./guest-upload";
import { SharedPhotos } from "./shared-photos";
import { VideoSection } from "./video-section";

export default function EventPage() {
  const { id } = useParams<{ id: string }>();
  const valid = isUuid(id);
  const { data: event, error, loading } = useApi<EventPublic>(valid ? `/api/events/${id}` : null);
  useSetEventBranding(event ? { id: event.id, has_logo: event.has_logo } : null);
  if (!valid) notFound();

  if (loading) return <p className="text-sm text-muted">Loading…</p>;
  if (error || !event) {
    return <Alert>{error?.status === 403 ? "You don't have access to this event." : error?.message}</Alert>;
  }

  return (
    <div className={event.accent_color ? "event-accent" : undefined} style={accentStyle(event.accent_color)}>
      <EventCover event={event} subtitle={event.date ? formatDate(event.date) : undefined} />
      {event.description && <p className="-mt-2 mb-8 max-w-2xl whitespace-pre-line text-muted">{event.description}</p>}
      <div className="space-y-10">
        <FindPhotos event={event} />
        <SharedPhotos eventId={event.id} />
        {/* Uploading doesn't need face-search consent: that consent covers the user's own selfie. */}
        {event.guest_upload_enabled && <GuestUpload event={event} />}
        <VideoSection eventId={event.id} />
      </div>
    </div>
  );
}
