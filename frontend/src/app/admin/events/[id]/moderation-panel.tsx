"use client";

import { useState } from "react";

import { Alert, Badge, Button, Card } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventAdmin, ModerationItem, PhotoReport, ReportReason } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { RemovalRequests } from "./removal-requests";

const REASON_LABEL: Record<ReportReason, string> = {
  its_me_remove: "Person in photo asks for removal",
  privacy: "Privacy",
  inappropriate: "Inappropriate",
  other: "Other",
};

function Thumb({ eventId, photoId }: { eventId: string; photoId: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- authenticated API image
    <img
      src={`/api/events/${eventId}/photos/${photoId}/preview`}
      alt=""
      loading="lazy"
      className="aspect-[4/3] w-full rounded-lg bg-mist object-cover"
    />
  );
}

export function ModerationPanel({ event }: { event: EventAdmin }) {
  const queue = useApi<ModerationItem[]>(`/api/events/${event.id}/moderation`);
  const reports = useApi<PhotoReport[]>(`/api/events/${event.id}/reports`);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function act(key: string, path: string, body: unknown, reload: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await post(path, body);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  const items = queue.data ?? [];
  const open = reports.data ?? [];

  return (
    <div className="space-y-8">
      {error && <Alert>{error}</Alert>}

      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-medium">
            Awaiting approval <span className="text-muted">({items.length})</span>
          </h2>
          <span className="text-xs text-muted">
            {event.guest_upload_enabled
              ? event.moderation_mode === "manual"
                ? "Guest uploads need your approval before anyone can find them."
                : "Guest uploads publish automatically."
              : "Guest uploads are off."}
          </span>
        </div>
        {items.length === 0 ? (
          <Card className="text-center text-sm text-muted">Nothing to review.</Card>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <li key={item.id} className="rounded-xl border border-line bg-paper p-3">
                {item.index_status === "indexed" ? (
                  <Thumb eventId={event.id} photoId={item.id} />
                ) : (
                  <div className="flex aspect-[4/3] items-center justify-center rounded-lg bg-mist text-xs text-muted">
                    Processing…
                  </div>
                )}
                <p className="mt-2 truncate text-xs text-muted">
                  {item.uploader_email} · {item.face_count} {item.face_count === 1 ? "face" : "faces"}
                </p>
                <div className="mt-2 flex gap-2">
                  <Button
                    className="flex-1"
                    disabled={busy === item.id}
                    onClick={() => void act(item.id, `/api/events/${event.id}/photos/${item.id}/moderate`, { action: "approve" }, queue.reload)}
                  >
                    Approve
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={busy === item.id}
                    onClick={() => void act(item.id, `/api/events/${event.id}/photos/${item.id}/moderate`, { action: "reject" }, queue.reload)}
                  >
                    Reject
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <RemovalRequests eventId={event.id} />

      <section>
        <h2 className="mb-3 font-medium">
          Reports <span className="text-muted">({open.length})</span>
        </h2>
        {open.length === 0 ? (
          <Card className="text-center text-sm text-muted">No open reports.</Card>
        ) : (
          <ul className="space-y-3">
            {open.map((r) => (
              <li key={r.id} className="grid gap-4 rounded-xl border border-line bg-paper p-3 sm:grid-cols-[180px_1fr]">
                <Thumb eventId={event.id} photoId={r.photo_id} />
                <div className="flex flex-col">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={r.reason === "its_me_remove" ? "warn" : "bad"}>{REASON_LABEL[r.reason]}</Badge>
                    <span className="text-xs text-muted">
                      {r.reporter_email} · {new Date(r.created_at).toLocaleString()}
                    </span>
                  </div>
                  {r.details && <p className="mt-2 text-sm text-muted">“{r.details}”</p>}
                  <div className="mt-auto flex gap-2 pt-3">
                    <Button
                      variant="danger"
                      disabled={busy === r.id}
                      onClick={() => {
                        if (confirm("Remove this photo from the event? Its face data and files are deleted.")) {
                          void act(r.id, `/api/events/${event.id}/reports/${r.id}/resolve`, { action: "remove_photo" }, reports.reload);
                        }
                      }}
                    >
                      Remove photo
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={busy === r.id}
                      onClick={() => void act(r.id, `/api/events/${event.id}/reports/${r.id}/resolve`, { action: "dismiss" }, reports.reload)}
                    >
                      Dismiss
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
