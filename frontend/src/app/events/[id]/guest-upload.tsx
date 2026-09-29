"use client";

import { useEffect, useState } from "react";

import { Alert, Badge, Card } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventPublic, MyUpload, UploadStart } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const MAX_BYTES = 25 * 1024 * 1024;
const ACCEPT = "image/jpeg,image/png,image/heic,image/heif,.heic,.heif";

interface Pending {
  key: string;
  name: string;
  progress: number; // 0–100
  error: string | null;
}

function contentTypeOf(file: File): string | null {
  if (["image/jpeg", "image/png", "image/heic", "image/heif"].includes(file.type)) return file.type;
  if (!file.type && /\.hei[cf]$/i.test(file.name)) return "image/heic"; // some browsers leave HEIC untyped
  return null;
}

/** PUT straight to object storage via the presigned URL, reporting progress. */
function putWithProgress(url: string, file: File, contentType: string, onProgress: (pct: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType); // must match the signed type
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(file);
  });
}

const STATUS_LABEL: Record<string, { text: string; tone: "neutral" | "good" | "warn" | "bad" }> = {
  processing: { text: "Processing", tone: "warn" },
  pending_review: { text: "Awaiting approval", tone: "warn" },
  published: { text: "Published", tone: "good" },
  rejected: { text: "Not accepted", tone: "bad" },
};

export function GuestUpload({ event }: { event: EventPublic }) {
  const mine = useApi<MyUpload[]>(`/api/events/${event.id}/my-uploads`);
  const [pending, setPending] = useState<Pending[]>([]);
  const reloadMine = mine.reload;
  const processing = (mine.data ?? []).some((u) => u.status === "processing");

  // Refresh statuses while the server is still processing uploads.
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => void reloadMine(), 3000);
    return () => clearInterval(t);
  }, [processing, reloadMine]);

  function update(key: string, patch: Partial<Pending>) {
    setPending((list) => list.map((p) => (p.key === key ? { ...p, ...patch } : p)));
  }

  async function uploadOne(file: File, key: string) {
    const contentType = contentTypeOf(file);
    if (!contentType) return update(key, { error: "Only JPEG, PNG and HEIC photos are allowed" });
    if (file.size > MAX_BYTES) return update(key, { error: "Photos must be under 25 MB" });
    try {
      const start = await post<UploadStart>(`/api/events/${event.id}/uploads`, {
        filename: file.name,
        content_type: contentType,
        size: file.size,
      });
      await putWithProgress(start.upload_url, file, contentType, (progress) => update(key, { progress }));
      await post(`/api/events/${event.id}/uploads/${start.photo_id}/complete`);
      setPending((list) => list.filter((p) => p.key !== key));
    } catch (e) {
      update(key, { error: e instanceof Error ? e.message : "Upload failed" });
    }
  }

  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    const batch = Array.from(files).map((file) => ({ file, key: `${file.name}-${file.size}-${crypto.randomUUID()}` }));
    setPending((list) => [...list, ...batch.map(({ file, key }) => ({ key, name: file.name, progress: 0, error: null }))]);
    // A few at a time: fast on good connections without flooding mobile uplinks.
    const queue = [...batch];
    await Promise.all(
      Array.from({ length: 3 }, async () => {
        for (let item = queue.shift(); item; item = queue.shift()) await uploadOne(item.file, item.key);
      }),
    );
    void reloadMine();
  }

  const uploads = mine.data ?? [];

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl">Add your photos</h2>
          <p className="mt-1 max-w-lg text-sm text-ink/60">
            Share photos you took at the event. Location and camera data are removed. Other attendees see a photo only if
            they appear in it, and organizers may review uploads first.
          </p>
        </div>
        <label className="cursor-pointer rounded-lg bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-ink/85">
          Choose photos
          <input
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            onChange={(e) => {
              void onFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {pending.length > 0 && (
        <ul className="mt-5 space-y-2">
          {pending.map((p) => (
            <li key={p.key} className="text-sm">
              <div className="flex justify-between gap-4">
                <span className="truncate">{p.name}</span>
                <span className={p.error ? "text-alarm" : "text-ink/50"}>{p.error ?? `${p.progress}%`}</span>
              </div>
              {!p.error && (
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-mist">
                  <div className="h-full bg-accent transition-all" style={{ width: `${p.progress}%` }} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {mine.error && (
        <div className="mt-4">
          <Alert>{mine.error.message}</Alert>
        </div>
      )}

      {uploads.length > 0 && (
        <div className="mt-6 border-t border-line pt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink/50">Your uploads</p>
          <ul className="divide-y divide-line text-sm">
            {uploads.map((u) => {
              const label = STATUS_LABEL[u.status] ?? { text: u.status, tone: "neutral" as const };
              return (
                <li key={u.id} className="flex items-center justify-between gap-4 py-2">
                  <span className="truncate text-ink/70" title={u.error ?? undefined}>
                    {u.original_filename}
                  </span>
                  <Badge tone={label.tone}>{label.text}</Badge>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}
