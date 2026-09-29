"use client";

import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input, Textarea } from "@/components/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/** Accepts an event slug or any EventFaces link that contains one (/join/<slug>, ?event=<slug>). */
function slugFrom(value: string): string {
  const v = value.trim();
  try {
    const url = new URL(v);
    return url.searchParams.get("event") ?? url.pathname.match(/\/join\/([^/]+)/)?.[1] ?? "";
  } catch {
    return v;
  }
}

export function RemovalRequestForm({ initialEvent }: { initialEvent: string }) {
  const known = useApi<{ event_name: string }>(initialEvent ? `/api/removal-requests/event/${initialEvent}` : null);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await post("/api/removal-requests", {
        event: initialEvent || slugFrom(String(form.get("event") ?? "")),
        email: form.get("email"),
        message: form.get("message"),
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the request");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthCard title="Check your inbox">
        <p className="text-sm text-ink/70">
          If that event exists, we&apos;ve emailed you a link. Open it within 48 hours to finish your request.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Remove photos of me"
      subtitle={
        known.data
          ? `Event: ${known.data.event_name}`
          : "For anyone who appears in an event's photos, whether you attended or not."
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        {!initialEvent && (
          <Field label="Event link" hint="The join link or removal link shared by the organizer.">
            <Input name="event" required placeholder="https://…/join/summer-party-x7k2" />
          </Field>
        )}
        <Field label="Your email" hint="We only use it to confirm the request and tell you the outcome.">
          <Input name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Message to the organizers (optional)">
          <Textarea name="message" maxLength={2000} />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Sending…" : "Continue"}
        </Button>
        <p className="text-xs text-ink/50">
          Next, you can add a reference photo of yourself so organizers can find the right pictures. It&apos;s
          compared once and deleted immediately.
        </p>
      </form>
    </AuthCard>
  );
}
