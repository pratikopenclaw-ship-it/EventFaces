"use client";

import Link from "next/link";

import { useSession } from "@/components/session";
import { Alert, Badge, Card, PageHeader, formatDate } from "@/components/ui";
import type { EventListItem } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function AdminEventsPage() {
  const { user } = useSession();
  const { data, error, loading } = useApi<EventListItem[]>("/api/events");
  const managed = data?.filter((e) => e.can_manage) ?? [];

  return (
    <>
      <PageHeader
        title="Manage events"
        subtitle={user?.role === "super_admin" ? "All events (super admin)." : "Events you organize."}
        actions={
          user?.role === "super_admin" && (
            <>
              <Link href="/admin/match-quality" className="rounded-lg border border-line bg-paper px-4 py-2 text-sm font-medium hover:bg-mist">
                Match quality
              </Link>
              <Link href="/admin/events/new" className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-ink/85">
                New event
              </Link>
            </>
          )
        }
      />
      {loading && <p className="text-sm text-ink/70">Loading…</p>}
      {error && <Alert>{error.message}</Alert>}
      {!loading && managed.length === 0 && <Card className="text-center text-sm text-ink/70">No events yet.</Card>}
      <div className="overflow-hidden rounded-2xl border border-line bg-paper">
        {managed.map((event) => {
          const expired = event.access_expires_at && new Date(event.access_expires_at) < new Date();
          return (
            <Link
              key={event.id}
              href={`/admin/events/${event.id}`}
              className="flex items-center justify-between gap-4 border-b border-line px-5 py-4 last:border-0 hover:bg-mist/60"
            >
              <div>
                <p className="font-medium">{event.name}</p>
                <p className="text-sm text-ink/70">
                  {formatDate(event.date)} · {event.photo_count.toLocaleString()}{" "}
                  {event.photo_count === 1 ? "photo" : "photos"}
                </p>
              </div>
              {expired ? <Badge tone="bad">Access ended</Badge> : <Badge tone="good">Open</Badge>}
            </Link>
          );
        })}
      </div>
    </>
  );
}
