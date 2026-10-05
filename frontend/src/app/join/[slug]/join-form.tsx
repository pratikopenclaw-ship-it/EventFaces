"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { EventCover } from "@/components/event-cover";
import { VerifyBanner } from "@/components/verify-banner";
import { Alert, Button, Field, Input, formatDate } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventPublic, JoinPreview } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export function JoinForm({
  slug,
  initialCode,
}: {
  slug: string;
  initialCode: string;
}) {
  const { data: preview, error: previewError } = useApi<JoinPreview>(
    `/api/join/${slug}`,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const event = await post<EventPublic>("/api/join", {
        slug,
        code: new FormData(e.currentTarget).get("code"),
      });
      router.push(`/events/${event.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not join");
      setBusy(false);
    }
  }

  if (previewError) {
    return (
      <AuthCard title="Join event">
        <VerifyBanner />
        <Alert>
          {previewError.status === 404
            ? "This event link isn't valid."
            : previewError.message}
        </Alert>
      </AuthCard>
    );
  }

  return (
    <>
      {preview && (
        <div className="mx-auto max-w-md">
          {/* Seeded by the slug: before joining there is no event id (and no logo). */}
          <EventCover
            event={{
              id: preview.slug,
              name: preview.name,
              accent_color: preview.accent_color,
            }}
            level={2}
            subtitle={preview.date ? formatDate(preview.date) : undefined}
          />
        </div>
      )}
      <AuthCard title={preview ? "Join this event" : "Join event"}>
        {preview?.join_mode === "invite" ? (
          <Alert kind="info">
            This event is invite-only. Use the personal link from your
            invitation email.
          </Alert>
        ) : (
          <form method="post" onSubmit={onSubmit} className="space-y-4">
            {error && <Alert>{error}</Alert>}
            <Field
              label="Access code"
              hint="8 characters, from the organizer or the QR code."
            >
              <Input
                name="code"
                defaultValue={initialCode}
                autoComplete="off"
                autoCapitalize="characters"
                className="font-mono tracking-widest uppercase"
                required
              />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Joining…" : "Join event"}
            </Button>
          </form>
        )}
      </AuthCard>
    </>
  );
}
