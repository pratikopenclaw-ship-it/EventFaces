"use client";

import { useState } from "react";

import type { EventVideo } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const PROVIDER_LABEL: Record<EventVideo["provider"], string> = {
  youtube: "YouTube",
  vimeo: "Vimeo",
  instagram: "Instagram",
  drive: "Google Drive",
};

/** A dedicated section, not mixed into the photo grid. Each video is a title card: the
 * iframe (and that provider's cookies/scripts) mounts only once a guest clicks Play. */
export function VideoSection({ eventId }: { eventId: string }) {
  const { data: videos } = useApi<EventVideo[]>(`/api/events/${eventId}/videos`);
  if (!videos || videos.length === 0) return null;

  return (
    <section>
      <h2 className="font-display text-xl tracking-tight text-ink">Videos</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {videos.map((v) => (
          <VideoCard key={v.id} video={v} />
        ))}
      </div>
    </section>
  );
}

function VideoCard({ video }: { video: EventVideo }) {
  const [playing, setPlaying] = useState(false);

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-paper">
      {playing ? (
        <div className="aspect-video bg-black">
          <iframe
            src={video.embed_url}
            title={video.title}
            className="h-full w-full"
            allow="accelerometer; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setPlaying(true)}
          className="flex aspect-video w-full flex-col items-center justify-center gap-2 bg-mist text-ink transition hover:bg-mist/80"
        >
          <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <circle cx="12" cy="12" r="11" className="fill-accent" />
            <path d="M10 8.5v7l6-3.5-6-3.5z" className="fill-on-accent" />
          </svg>
          <span className="sr-only">Play video</span>
        </button>
      )}
      <div className="p-4">
        <p className="font-medium">{video.title}</p>
        <p className="mt-0.5 text-xs text-muted">{PROVIDER_LABEL[video.provider]}</p>
      </div>
    </div>
  );
}
