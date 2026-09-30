"use client";

import { useCallback, useEffect, useState } from "react";

import { Alert, Badge, Button, Card } from "@/components/ui";
import { del, get, post } from "@/lib/api";
import type { EventAdmin, IndexStatus, PhotoAdmin, PhotoPage, SyncStatus } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const PAGE = 60;
const POLL_MS = 2000;

const STAGE_LABEL: Record<IndexStatus, string> = {
  queued: "Queued",
  importing: "Importing",
  indexing: "Finding faces",
  indexed: "Done",
  failed: "Failed",
};

function timeAgo(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function PhotosPanel({ event, onEditSettings }: { event: EventAdmin; onEditSettings: () => void }) {
  const status = useApi<SyncStatus>(`/api/events/${event.id}/sync`);
  const [photos, setPhotos] = useState<PhotoAdmin[]>([]);
  const [total, setTotal] = useState(0);
  const [failedOnly, setFailedOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const inProgress = status.data?.in_progress ?? false;
  const reloadStatus = status.reload;

  const loadPhotos = useCallback(
    async (offset: number) => {
      const qs = new URLSearchParams({ offset: String(offset), limit: String(PAGE) });
      if (failedOnly) qs.set("index_status", "failed");
      const page = await get<PhotoPage>(`/api/events/${event.id}/photos?${qs}`);
      setPhotos((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
    },
    [event.id, failedOnly],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount / filter change
    void loadPhotos(0).catch((e: Error) => setError(e.message));
  }, [loadPhotos]);

  // Poll while a sync or the import/index pipeline is running.
  useEffect(() => {
    if (!inProgress) return;
    const timer = setInterval(() => {
      void reloadStatus();
      void loadPhotos(0);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [inProgress, reloadStatus, loadPhotos]);

  async function sync() {
    setStarting(true);
    setError(null);
    try {
      await post(`/api/events/${event.id}/sync`);
      await reloadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed to start");
    } finally {
      setStarting(false);
    }
  }

  const s = status.data;
  const run = s?.last_run;
  const pending = s ? s.pipeline.queued + s.pipeline.importing + s.pipeline.indexing : 0;
  const processed = s ? s.pipeline.indexed + s.pipeline.failed : 0;
  const progress = pending + processed > 0 ? Math.round((processed / (pending + processed)) * 100) : 0;

  return (
    <div className="space-y-6">
      {error && <Alert>{error}</Alert>}
      {status.error && <Alert>{status.error.message}</Alert>}

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0 flex-1 space-y-3">
            <h2 className="font-medium">Google Drive</h2>
            {!s ? (
              <p className="text-sm text-ink/70">Loading…</p>
            ) : !s.drive_configured ? (
              <Alert kind="info">
                Drive import isn&apos;t configured on the server. Set <code>GOOGLE_SERVICE_ACCOUNT_JSON</code> (see
                README).
              </Alert>
            ) : !s.folder_id ? (
              <p className="text-sm text-ink/70">
                No folder linked.{" "}
                <button onClick={onEditSettings} className="font-medium text-accent hover:underline">
                  Add one in Settings
                </button>
                .
              </p>
            ) : (
              <>
                <p className="text-sm text-ink/70">
                  Share the folder (Viewer access) with{" "}
                  <span className="break-all rounded bg-mist px-1.5 py-0.5 font-mono text-xs">
                    {s.service_account_email}
                  </span>
                </p>
                <p className="text-xs text-ink/70">
                  Folder <span className="font-mono">{s.folder_id}</span> · top-level JPEG, PNG and HEIC files
                </p>
              </>
            )}
          </div>
          <Button onClick={() => void sync()} disabled={!s?.drive_configured || !s?.folder_id || inProgress || starting}>
            {inProgress ? "Syncing…" : "Sync now"}
          </Button>
        </div>

        {s && (
          <div className="mt-6 grid gap-4 border-t border-line pt-5 sm:grid-cols-3">
            <Stat label="Published photos" value={s.published_photos} />
            <Stat label="Faces indexed" value={s.faces} />
            <Stat label="Failed" value={s.pipeline.failed} tone={s.pipeline.failed ? "bad" : undefined} />
          </div>
        )}

        {inProgress && s && (
          <div className="mt-5">
            <div className="mb-1.5 flex justify-between text-xs text-ink/70">
              <span>
                {s.pipeline.importing > 0 && `${s.pipeline.importing} importing · `}
                {s.pipeline.indexing > 0 && `${s.pipeline.indexing} finding faces · `}
                {s.pipeline.queued} queued
              </span>
              <span>{progress}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-mist">
              <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {run && (
          <p className="mt-4 text-xs text-ink/70">
            Last sync {timeAgo(run.created_at)}:{" "}
            {run.status === "failed" ? (
              <span className="text-alarm">{run.error}</span>
            ) : run.status === "completed" ? (
              `${run.files_listed} files found, ${run.files_new} new${run.files_retried ? `, ${run.files_retried} retried` : ""}`
            ) : (
              "listing folder…"
            )}
          </p>
        )}
      </Card>

      <div className="flex items-center justify-between">
        <h2 className="font-medium">
          Photos <span className="text-ink/70">({total})</span>
        </h2>
        <label className="flex items-center gap-2 text-sm text-ink/70">
          <input type="checkbox" className="accent-accent" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} />
          Failed only
        </label>
      </div>

      {photos.length === 0 ? (
        <Card className="text-center text-sm text-ink/70">
          {failedOnly ? "No failed photos." : "No photos yet. Link a Drive folder and press Sync."}
        </Card>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {photos.map((p) => (
            <PhotoTile
              key={p.id}
              eventId={event.id}
              photo={p}
              onDelete={async () => {
                if (!confirm("Delete this photo? Its face data and files are removed and nobody can find it anymore.")) return;
                try {
                  await del(`/api/events/${event.id}/photos/${p.id}`);
                  setPhotos((list) => list.filter((x) => x.id !== p.id));
                  setTotal((t) => t - 1);
                  void reloadStatus();
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Delete failed");
                }
              }}
            />
          ))}
        </ul>
      )}
      {photos.length < total && (
        <div className="text-center">
          <Button variant="secondary" onClick={() => void loadPhotos(photos.length)}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "bad" }) {
  return (
    <div>
      <p className={`font-display text-3xl ${tone === "bad" ? "text-alarm" : ""}`}>{value.toLocaleString()}</p>
      <p className="text-xs text-ink/70">{label}</p>
    </div>
  );
}

function PhotoTile({ eventId, photo, onDelete }: { eventId: string; photo: PhotoAdmin; onDelete: () => void }) {
  const hasThumb =
    photo.status !== "rejected" &&
    (photo.index_status === "indexing" || photo.index_status === "indexed" || photo.status === "published");
  return (
    <li className="group overflow-hidden rounded-xl border border-line bg-paper" title={photo.error ?? photo.original_filename ?? ""}>
      <div className="relative aspect-[4/3] bg-mist">
        <button
          onClick={onDelete}
          aria-label="Delete photo"
          className="absolute right-2 top-2 z-10 rounded-md bg-paper/90 px-2 py-1 text-xs font-medium text-alarm opacity-0 shadow transition group-hover:opacity-100 focus:opacity-100"
        >
          Delete
        </button>
        {hasThumb ? (
          // eslint-disable-next-line @next/next/no-img-element -- authenticated API image, not optimizable
          <img
            src={`/api/events/${eventId}/photos/${photo.id}/thumb`}
            alt={photo.original_filename ?? "Event photo"}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-ink/70">{STAGE_LABEL[photo.index_status]}</div>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 px-2.5 py-2 text-xs">
        <span className="truncate text-ink/70">{photo.original_filename}</span>
        {photo.index_status === "failed" ? (
          <Badge tone="bad">{photo.status === "rejected" ? "Rejected" : "Failed"}</Badge>
        ) : photo.index_status === "indexed" ? (
          <Badge>{photo.face_count} {photo.face_count === 1 ? "face" : "faces"}</Badge>
        ) : (
          <Badge tone="warn">{STAGE_LABEL[photo.index_status]}</Badge>
        )}
      </div>
    </li>
  );
}
