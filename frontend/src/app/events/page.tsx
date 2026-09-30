"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { VerifyBanner } from "@/components/verify-banner";
import { Alert, Badge, Button, Card, Field, Input, PageHeader, formatDate } from "@/components/ui";
import { parseJoinLink } from "@/lib/links";
import type { EventListItem } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function MyEventsPage() {
  const { data: events, error, loading } = useApi<EventListItem[]>("/api/events");
  const [joinError, setJoinError] = useState<string | null>(null);
  const router = useRouter();

  function onJoin(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const parsed = parseJoinLink(String(new FormData(e.currentTarget).get("link") ?? ""));
    if (!parsed) {
      setJoinError("Paste the event link you received (it contains /join/…).");
      return;
    }
    const qs = parsed.code ? `?code=${encodeURIComponent(parsed.code)}` : "";
    router.push(`/join/${parsed.slug}${qs}`);
  }

  const attending = events?.filter((e) => e.my_role === "attendee") ?? [];

  return (
    <>
      <VerifyBanner />
      <PageHeader title="My events" subtitle="Events you've joined." />
      <div className="grid gap-8 md:grid-cols-[1fr_320px]">
        <div className="space-y-3">
          {loading && <p className="text-sm text-ink/70">Loading…</p>}
          {error && error.status !== 403 && <Alert>{error.message}</Alert>}
          {!loading && attending.length === 0 && (
            <Card className="text-center text-sm text-ink/70">
              You haven&apos;t joined any events yet. Use the link or QR code from the organizer.
            </Card>
          )}
          {attending.map((event) => (
            <Link
              key={event.id}
              href={`/events/${event.id}`}
              className="block rounded-2xl border border-line bg-paper p-5 transition hover:border-ink/30"
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="font-medium">{event.name}</h2>
                  <p className="text-sm text-ink/70">{formatDate(event.date)}</p>
                </div>
                {event.access_expires_at && <Badge>Access until {formatDate(event.access_expires_at)}</Badge>}
                {event.search_state === "queued" && <Badge tone="warn">Search queued</Badge>}
                {event.search_state === "done" && <Badge tone="good">Photos ready</Badge>}
              </div>
            </Link>
          ))}
        </div>
        <Card>
          <h2 className="mb-3 font-medium">Join an event</h2>
          <form method="post" onSubmit={onJoin} className="space-y-3">
            {joinError && <Alert>{joinError}</Alert>}
            <Field label="Event link" hint="Paste the link from the organizer.">
              <Input name="link" placeholder="https://…/join/summer-party-x7k2" required />
            </Field>
            <Button type="submit" className="w-full">
              Continue
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
