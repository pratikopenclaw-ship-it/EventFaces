"use client";

import { useState, type FormEvent } from "react";

import { Alert, Button, Field, Input, Select, Textarea, Toggle } from "@/components/ui";
import { SURFACES, readableAccent } from "@/lib/accent";
import type { EventAdmin, EventInput } from "@/lib/types";
import { useApi } from "@/lib/use-api";

/** ISO timestamp → value for <input type="datetime-local"> in the browser's timezone. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function initialInput(event?: EventAdmin): EventInput {
  return {
    name: event?.name ?? "",
    date: event?.date ?? null,
    description: event?.description ?? "",
    join_mode: event?.join_mode ?? "code",
    access_expires_at: event?.access_expires_at ?? null,
    guest_upload_enabled: event?.guest_upload_enabled ?? false,
    moderation_mode: event?.moderation_mode ?? "manual",
    auto_publish_faceless_photos: event?.auto_publish_faceless_photos ?? true,
    allow_selfie_file_upload: event?.allow_selfie_file_upload ?? false,
    delete_photos_on_expiry: event?.delete_photos_on_expiry ?? false,
    drive_folder: event?.drive_folder_id ?? null,
    accent_color: event?.accent_color ?? null,
  };
}

export function EventForm({
  initial,
  submitLabel,
  onSubmit,
}: {
  initial: EventInput;
  submitLabel: string;
  onSubmit: (input: EventInput) => Promise<void>;
}) {
  const [v, setV] = useState<EventInput>(initial);
  const serviceAccount = useApi<{ email: string | null }>("/api/drive/service-account");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof EventInput>(key: K, value: EventInput[K]) => {
    setSaved(false);
    setV((prev) => ({ ...prev, [key]: value }));
  };

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(v);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form method="post" onSubmit={submit} className="space-y-8">
      {error && <Alert>{error}</Alert>}
      {saved && <Alert kind="success">Saved.</Alert>}

      <section className="grid gap-4 md:grid-cols-2">
        <Field label="Event name">
          <Input value={v.name} onChange={(e) => set("name", e.target.value)} required maxLength={200} />
        </Field>
        <Field label="Date">
          <Input type="date" value={v.date ?? ""} onChange={(e) => set("date", e.target.value || null)} />
        </Field>
        <div className="md:col-span-2">
          <Field label="Description">
            <Textarea value={v.description} onChange={(e) => set("description", e.target.value)} maxLength={5000} />
          </Field>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <Field label="How attendees join">
          <Select value={v.join_mode} onChange={(e) => set("join_mode", e.target.value as EventInput["join_mode"])}>
            <option value="code">Access code / QR link</option>
            <option value="invite">Invite only (CSV of emails)</option>
          </Select>
        </Field>
        <Field
          label="Access ends"
          hint="After this, attendees lose access and face data is deleted by the retention job."
        >
          <Input
            type="datetime-local"
            value={toLocalInput(v.access_expires_at)}
            onChange={(e) => set("access_expires_at", e.target.value ? new Date(e.target.value).toISOString() : null)}
          />
        </Field>
        <div className="md:col-span-2">
          <Field
            label="Google Drive folder"
            hint={
              serviceAccount.data?.email ? (
                <>
                  Folder URL or ID. Share the folder (Viewer access) with{" "}
                  <span className="break-all font-mono">{serviceAccount.data.email}</span>.
                </>
              ) : (
                "Folder URL or ID. Drive import also needs a service account configured on the server (see README)."
              )
            }
          >
            <Input
              value={v.drive_folder ?? ""}
              onChange={(e) => set("drive_folder", e.target.value || null)}
              placeholder="https://drive.google.com/drive/folders/…"
            />
          </Field>
        </div>
      </section>

      <AccentField value={v.accent_color} onChange={(c) => set("accent_color", c)} />

      <section className="space-y-4">
        <Toggle
          label="Allow selfie file upload"
          hint="By default attendees must take a live selfie with their camera."
          checked={v.allow_selfie_file_upload}
          onChange={(x) => set("allow_selfie_file_upload", x)}
        />
        <Toggle
          label="Guest uploads"
          hint="Approved attendees can add their own photos to this event."
          checked={v.guest_upload_enabled}
          onChange={(x) => set("guest_upload_enabled", x)}
        />
        {v.guest_upload_enabled && (
          <div className="pl-7">
            <Field label="Guest photo moderation">
              <Select
                value={v.moderation_mode}
                onChange={(e) => set("moderation_mode", e.target.value as EventInput["moderation_mode"])}
              >
                <option value="manual">Organizer approves each photo</option>
                <option value="auto">Publish automatically</option>
              </Select>
            </Field>
          </div>
        )}
        <Toggle
          label="Publish photos with no face detected"
          hint="Covers photos from Drive sync and guest uploads alike. Turn off to hold them for your review in the moderation queue instead of publishing automatically."
          checked={v.auto_publish_faceless_photos}
          onChange={(x) => set("auto_publish_faceless_photos", x)}
        />
        <Toggle
          label="Delete photos when access ends"
          hint="Face data is always deleted at expiry; this also removes the photos themselves."
          checked={v.delete_photos_on_expiry}
          onChange={(x) => set("delete_photos_on_expiry", x)}
        />
      </section>

      <Button type="submit" disabled={busy}>
        {busy ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}

const DEFAULT_ACCENT = "#0f766e";

/** Brand colour picker with a preview of the readable variant used in each theme. */
function AccentField({ value, onChange }: { value: string | null; onChange: (c: string | null) => void }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Accent colour" hint="Buttons and links on this event's pages. Adjusted automatically so text stays readable in light and dark mode.">
          <span className="flex items-center gap-3">
            <input
              type="color"
              value={value ?? DEFAULT_ACCENT}
              onChange={(e) => onChange(e.target.value.toLowerCase())}
              className="h-11 w-16 cursor-pointer rounded-lg border border-line bg-paper p-1"
            />
            <span className="font-mono text-sm text-muted">{value ?? "Default"}</span>
          </span>
        </Field>
        {value && (
          <Button type="button" variant="ghost" onClick={() => onChange(null)}>
            Use default
          </Button>
        )}
      </div>
      {value && (
        <div className="flex flex-wrap gap-3" aria-label="Accent preview">
          {(["light", "dark"] as const).map((theme) => {
            const { accent, onAccent } = readableAccent(value, theme);
            return (
              <div
                key={theme}
                className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm"
                style={{ background: SURFACES[theme][0], color: theme === "light" ? "#10231f" : "#f4f5f7" }}
              >
                <span>{theme === "light" ? "Light" : "Dark"}:</span>
                <span style={{ color: accent }} className="font-medium">
                  Link
                </span>
                <span style={{ background: accent, color: onAccent }} className="rounded-md px-2 py-0.5 font-medium">
                  Button
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
