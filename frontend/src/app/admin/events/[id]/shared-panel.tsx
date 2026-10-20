"use client";

import { useState } from "react";

import { CameraIcon } from "@/components/empty-icons";
import { Alert, Badge, Button, Card, EmptyState } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventAdmin, PhotoPage, ShareResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type Filter = "all" | "shared" | "not_shared";

const FILTERS: { key: Filter; label: string; qs: string }[] = [
  { key: "all", label: "All", qs: "" },
  { key: "not_shared", label: "Not shared", qs: "&shared=false" },
  { key: "shared", label: "Shared", qs: "&shared=true" },
];
const PAGE = 200;

/** Published photos with no detected face, which organizers can show to every member
 * (venue, food, decor) without a selfie match. Sharing is always an explicit choice. */
export function SharedPanel({ event }: { event: EventAdmin }) {
  const [filter, setFilter] = useState<Filter>("all");
  const qs = FILTERS.find((f) => f.key === filter)!.qs;
  const list = useApi<PhotoPage>(`/api/events/${event.id}/photos?faceless=true&limit=${PAGE}${qs}`);
  const unshared = useApi<PhotoPage>(`/api/events/${event.id}/photos?faceless=true&shared=false&limit=1`);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const items = list.data?.items ?? [];
  const toShare = unshared.data?.total ?? 0;

  async function run(path: string, body: unknown, message: (r: ShareResult) => string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await post<ShareResult>(path, body);
      setNotice(message(result));
      setSelected(new Set());
      await Promise.all([list.reload(), unshared.reload()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  function share(shared: boolean) {
    void run(
      `/api/events/${event.id}/photos/share`,
      { photo_ids: [...selected], shared },
      (r) =>
        `${r.changed} ${r.changed === 1 ? "photo" : "photos"} ${shared ? "shared" : "unshared"}` +
        (r.skipped ? ` · ${r.skipped} skipped (a face was found or it isn't published)` : "."),
    );
  }

  function shareAll() {
    const ok = confirm(
      `Share ${toShare} ${toShare === 1 ? "photo" : "photos"} with every attendee?\n\n` +
        "No face was detected in them, but detection can miss people seen from behind, in profile or far away. " +
        "Only continue if nobody is recognizable.",
    );
    if (!ok) return;
    void run(`/api/events/${event.id}/photos/share-faceless`, { confirm_no_people: true }, (r) => `${r.changed} ${r.changed === 1 ? "photo" : "photos"} shared.`);
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-4">
      <Alert kind="info">
        Photos where no face was detected (food, venue, decor) can be shown to every attendee, without a selfie match.
        Check each one: detection can miss people seen from behind or far away. Photos with a face are never shared,
        and a photo is unshared automatically if a face is found later.
      </Alert>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Filter" className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              aria-pressed={filter === f.key}
              onClick={() => {
                setFilter(f.key);
                setSelected(new Set());
              }}
              className={`rounded-full px-3 py-1 text-sm ${filter === f.key ? "bg-accent text-on-accent" : "text-muted hover:text-ink"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {selected.size > 0 && (
            <>
              <Button disabled={busy} onClick={() => share(true)}>
                Share selected ({selected.size})
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => share(false)}>
                Unshare selected
              </Button>
            </>
          )}
          {selected.size === 0 && toShare > 0 && (
            <Button variant="secondary" disabled={busy} onClick={shareAll}>
              Share all not yet shared ({toShare})
            </Button>
          )}
        </div>
      </div>

      {list.error && <Alert>{list.error.message}</Alert>}
      {!list.loading && items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CameraIcon className="size-6" />}
            title={filter === "shared" ? "Nothing shared yet" : "No photos without faces"}
            description="Published photos where no face was detected show up here."
          />
        </Card>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((p) => (
            <li key={p.id} className="overflow-hidden rounded-xl border border-line bg-paper">
              <label className="relative block cursor-pointer">
                {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                <img
                  src={`/api/events/${event.id}/photos/${p.id}/thumb`}
                  alt=""
                  loading="lazy"
                  className="aspect-[4/3] w-full bg-mist object-cover"
                />
                <span className="absolute left-2 top-2 flex size-7 items-center justify-center rounded-full bg-paper/90 shadow">
                  <input
                    type="checkbox"
                    aria-label="Select photo"
                    checked={selected.has(p.id)}
                    onChange={() => toggle(p.id)}
                    className="size-4 accent-accent"
                  />
                </span>
              </label>
              <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs">
                <span className="truncate text-muted">{p.original_filename}</span>
                {p.shared_at ? <Badge tone="good">Shared</Badge> : <Badge>Private</Badge>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {list.data && list.data.total > items.length && (
        <p className="text-xs text-muted">
          Showing the newest {items.length} of {list.data.total}. &ldquo;Share all&rdquo; covers every one of them.
        </p>
      )}
    </div>
  );
}
