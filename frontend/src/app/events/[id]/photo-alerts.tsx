"use client";

import { useEffect, useState } from "react";

import { Button, Toggle } from "@/components/ui";
import { put } from "@/lib/api";
import type { PhotoAlertState } from "@/lib/types";
import { useApi } from "@/lib/use-api";

/** New-photo alerts for one event. A search subscribes, so both parts show only once the
 * user has searched here (`subscribed`). `newPhotos` comes from GET /api/events/{id}; pass
 * false once the user has scanned again on this page. `searches` counts this page's
 * searches, so the state is fetched again after each one. */
export function PhotoAlerts({
  eventId,
  newPhotos,
  searches,
  onScan,
}: {
  eventId: string;
  newPhotos: boolean;
  searches: number;
  onScan: () => void;
}) {
  const state = useApi<PhotoAlertState>(`/api/events/${eventId}/photo-alerts`);
  const [error, setError] = useState(false);
  const { reload } = state;

  useEffect(() => {
    if (searches > 0) void reload();
  }, [searches, reload]);

  if (!state.data?.subscribed) return null;

  async function setEnabled(enabled: boolean) {
    setError(false);
    try {
      state.setData(await put<PhotoAlertState>(`/api/events/${eventId}/photo-alerts`, { enabled }));
    } catch {
      setError(true);
    }
  }

  return (
    <div className="space-y-4">
      {newPhotos && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-accent px-5 py-4 text-on-accent">
          <p className="text-sm font-medium">New photos were added since your last scan</p>
          <Button variant="secondary" onClick={onScan}>
            Scan again
          </Button>
        </div>
      )}
      <Toggle
        label="Tell me when new photos are added to this event"
        hint="By email and in the app, at most once a day. We only keep when you last searched, nothing about your face."
        checked={state.data.enabled}
        onChange={(v) => void setEnabled(v)}
      />
      {error && <p className="text-sm text-alarm">Couldn&apos;t save, try again.</p>}
    </div>
  );
}
