"use client";

import { useRef, useState } from "react";

import { Alert, Button } from "@/components/ui";
import { RawBody, api, del } from "@/lib/api";
import type { EventAdmin } from "@/lib/types";

const TYPES = ["image/png", "image/jpeg", "image/heic"];
const MAX_BYTES = 1024 * 1024;

/** Organizer logo: uploaded on its own (not part of the settings form), re-encoded server-side. */
export function LogoField({ event, onChange }: { event: EventAdmin; onChange: (e: EventAdmin) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0); // bust the browser cache after a change

  async function upload(file: File) {
    setError(null);
    if (!TYPES.includes(file.type)) return setError("Use a PNG, JPEG or HEIC image.");
    if (file.size > MAX_BYTES) return setError("The logo can be at most 1 MB.");
    setBusy(true);
    try {
      onChange(await api<EventAdmin>("PUT", `/api/events/${event.id}/logo`, new RawBody(file, file.type)));
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove() {
    setBusy(true);
    try {
      onChange(await del<EventAdmin>(`/api/events/${event.id}/logo`));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3">
      <h2 className="font-medium">Event logo</h2>
      <p className="text-sm text-muted">Shown on the event page and in the app. PNG with transparency works best; up to 1 MB.</p>
      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap items-center gap-4">
        {event.has_logo && (
          // eslint-disable-next-line @next/next/no-img-element -- authenticated API image
          <img src={`/api/events/${event.id}/logo?v=${version}`} alt="Current logo" className="h-16 w-auto rounded-lg border border-line bg-mist p-1" />
        )}
        <label className="cursor-pointer rounded-lg border border-line bg-paper px-4 py-2 text-sm font-medium text-ink hover:bg-mist has-focus-visible:outline-2 has-focus-visible:outline-accent">
          {event.has_logo ? "Replace logo" : "Upload logo"}
          <input
            ref={input}
            type="file"
            accept={TYPES.join(",")}
            className="sr-only"
            disabled={busy}
            onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])}
          />
        </label>
        {event.has_logo && (
          <Button type="button" variant="ghost" disabled={busy} onClick={() => void remove()}>
            Remove logo
          </Button>
        )}
      </div>
    </section>
  );
}
