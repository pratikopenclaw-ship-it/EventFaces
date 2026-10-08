"use client";

import { useState } from "react";

import { UndoIcon } from "@/components/empty-icons";
import { Alert, Button, Card, EmptyState } from "@/components/ui";
import { post } from "@/lib/api";
import type { RemovalRequestItem } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export function RemovalRequests({ eventId }: { eventId: string }) {
  const list = useApi<RemovalRequestItem[]>(`/api/events/${eventId}/removal-requests`);
  const [selected, setSelected] = useState<Record<string, Set<string>>>({});
  const [error, setError] = useState<string | null>(null);

  function toggle(reqId: string, photoId: string, all: string[]) {
    setSelected((prev) => {
      const current = new Set(prev[reqId] ?? all);
      if (current.has(photoId)) current.delete(photoId);
      else current.add(photoId);
      return { ...prev, [reqId]: current };
    });
  }

  async function resolve(req: RemovalRequestItem, action: "remove" | "decline") {
    const ids = [...(selected[req.id] ?? new Set(req.matched_photo_ids))];
    if (action === "remove" && !confirm(`Remove ${ids.length} photo(s) from the event?`)) return;
    setError(null);
    try {
      await post(`/api/events/${eventId}/removal-requests/${req.id}/resolve`, { action, photo_ids: action === "remove" ? ids : null });
      await list.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  const items = list.data ?? [];
  return (
    <section>
      <h2 className="mb-1 font-medium">
        Removal requests <span className="text-muted">({items.length})</span>
      </h2>
      <p className="mb-3 text-xs text-muted">
        From people who appear in photos (they may not be attendees). Photos were matched with a reference selfie
        that was deleted right after matching. Check that each photo really shows them before removing it.
      </p>
      {error && <Alert>{error}</Alert>}
      {items.length === 0 ? (
        <Card>
          <EmptyState icon={<UndoIcon className="size-6" />} title="No open removal requests" />
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((req) => {
            const chosen = selected[req.id] ?? new Set(req.matched_photo_ids);
            return (
              <li key={req.id} className="rounded-xl border border-line bg-paper p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{req.email}</span>
                  <span className="text-xs text-muted">{new Date(req.created_at).toLocaleString()}</span>
                </div>
                {req.message && <p className="mt-1 text-sm text-muted">“{req.message}”</p>}
                {req.matched_photo_ids.length === 0 ? (
                  <p className="mt-3 text-sm text-muted">No reference photo, or no matches. Find the photos manually in the Photos tab.</p>
                ) : (
                  <ul className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5">
                    {req.matched_photo_ids.map((pid) => (
                      <li key={pid} className="relative">
                        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                        <img src={`/api/events/${eventId}/photos/${pid}/thumb`} alt="" className="aspect-square w-full rounded-lg bg-mist object-cover" />
                        <input
                          type="checkbox"
                          aria-label="Include photo"
                          checked={chosen.has(pid)}
                          onChange={() => toggle(req.id, pid, req.matched_photo_ids)}
                          className="absolute left-1.5 top-1.5 size-4 accent-accent"
                        />
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-3 flex gap-2">
                  <Button variant="danger" disabled={chosen.size === 0} onClick={() => void resolve(req, "remove")}>
                    Remove {chosen.size} photo{chosen.size === 1 ? "" : "s"}
                  </Button>
                  <Button variant="secondary" onClick={() => void resolve(req, "decline")}>
                    Decline
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
