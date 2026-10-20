"use client";

import type { MatchedPhoto, SharedPhoto } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PhotoGallery } from "./photo-gallery";

/** Photos the organizers shared with everyone: venue, food, decor. They have no faces,
 * so no selfie (and no face-search consent) is needed to see them. */
export function SharedPhotos({ eventId }: { eventId: string }) {
  const { data } = useApi<SharedPhoto[]>(`/api/events/${eventId}/shared-photos`);
  if (!data || data.length === 0) return null;
  const photos: MatchedPhoto[] = data.map((p) => ({ ...p, similarity: null, tier: null, verdict: null, shortlisted: false }));

  return (
    <section>
      <h2 className="font-display text-xl tracking-tight text-ink">Event photos</h2>
      <p className="mt-1 text-sm text-muted">Shared with everyone by the organizers.</p>
      <div className="mt-4">
        <PhotoGallery eventId={eventId} photos={photos} heading="Venue, food & more" shortlist={false} onVerdict={() => {}} />
      </div>
    </section>
  );
}
