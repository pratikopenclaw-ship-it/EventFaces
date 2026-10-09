"use client";

import Link from "next/link";

import { CalendarIcon } from "@/components/empty-icons";
import { EventCard } from "@/components/event-cover";
import { useSession } from "@/components/session";
import { Alert, Badge, Card, EmptyState, PageHeader, formatDate } from "@/components/ui";
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
              <Link href="/admin/events/new" className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover">
                New event
              </Link>
            </>
          )
        }
      />
      {loading && <p className="text-sm text-muted">Loading…</p>}
      {error && <Alert>{error.message}</Alert>}
      {!loading && managed.length === 0 && (
        <Card>
          <EmptyState icon={<CalendarIcon className="size-6" />} title="No events yet" />
        </Card>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {managed.map((event) => {
          const expired = event.access_expires_at && new Date(event.access_expires_at) < new Date();
          return (
            <EventCard
              key={event.id}
              event={event}
              href={`/admin/events/${event.id}`}
              meta={`${event.date ? `${formatDate(event.date)} · ` : ""}${event.photo_count.toLocaleString()} ${event.photo_count === 1 ? "photo" : "photos"}`}
              badges={expired ? <Badge tone="bad">Access ended</Badge> : <Badge tone="good">Open</Badge>}
            />
          );
        })}
      </div>
    </>
  );
}
