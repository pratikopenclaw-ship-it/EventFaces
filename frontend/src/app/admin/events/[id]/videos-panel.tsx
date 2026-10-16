"use client";

import { useState } from "react";

import { CameraIcon } from "@/components/empty-icons";
import { Alert, Button, Card, EmptyState, Field, Input } from "@/components/ui";
import { del, post } from "@/lib/api";
import type { EventVideo } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const PROVIDER_LABEL: Record<EventVideo["provider"], string> = {
  youtube: "YouTube",
  vimeo: "Vimeo",
  instagram: "Instagram",
  drive: "Google Drive",
};

export function VideosPanel({ eventId }: { eventId: string }) {
  const list = useApi<EventVideo[]>(`/api/events/${eventId}/videos`);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      await post<EventVideo>(`/api/events/${eventId}/videos`, { title, url });
      setTitle("");
      setUrl("");
      await list.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add that video link");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await del(`/api/events/${eventId}/videos/${id}`);
      await list.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove that video");
    }
  }

  const videos = list.data ?? [];

  return (
    <div className="space-y-6">
      {error && <Alert>{error}</Alert>}
      <Card>
        <h2 className="font-medium">Add a video link</h2>
        <p className="mt-1 text-sm text-muted">
          A YouTube, Vimeo, Instagram or Google Drive link. Guests see a title card on a dedicated Videos tab and load
          the player only when they choose to play it.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
          <Field label="Title">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ceremony highlights" />
          </Field>
          <Field label="Video URL">
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://youtu.be/…" />
          </Field>
          <Button disabled={busy || !title.trim() || !url.trim()} onClick={() => void add()}>
            {busy ? "Adding…" : "Add video"}
          </Button>
        </div>
      </Card>

      <div className="overflow-x-auto rounded-2xl border border-line bg-paper">
        <div className="border-b border-line px-5 py-3 text-sm font-medium">Videos</div>
        <table className="w-full text-left text-sm">
          <tbody>
            {videos.length === 0 && (
              <tr>
                <td className="px-5 py-6">
                  <EmptyState compact icon={<CameraIcon className="size-4" />} title="No videos yet" />
                </td>
              </tr>
            )}
            {videos.map((v) => (
              <tr key={v.id} className="border-b border-line last:border-0">
                <td className="px-5 py-3">{v.title}</td>
                <td className="px-5 py-3 text-muted">{PROVIDER_LABEL[v.provider]}</td>
                <td className="px-5 py-3 text-right">
                  <Button variant="ghost" onClick={() => void remove(v.id)}>
                    Remove
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
