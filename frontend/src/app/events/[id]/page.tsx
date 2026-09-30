"use client";

import { notFound, useParams } from "next/navigation";

import { Alert, PageHeader, formatDate } from "@/components/ui";
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

  if (loading) return <p className="text-sm text-ink/70">Loading…</p>;
  if (error || !event) {
    return <Alert>{error?.status === 403 ? "You don't have access to this event." : error?.message}</Alert>;
  }

  return (
    <>
      <PageHeader title={event.name} subtitle={event.date ? formatDate(event.date) : undefined} />
      {event.description && <p className="-mt-4 mb-8 max-w-2xl whitespace-pre-line text-ink/70">{event.description}</p>}
      <div className="space-y-10">
        <FindPhotos event={event} />
        {/* Uploading doesn't need face-search consent: that consent covers the user's own selfie. */}
        {event.guest_upload_enabled && <GuestUpload event={event} />}
      </div>
    </>
  );
}
