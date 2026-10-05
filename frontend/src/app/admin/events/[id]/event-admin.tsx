"use client";

import Link from "next/link";
import { useState } from "react";

import { EventForm, initialInput } from "@/components/event-form";
import { LogoField } from "@/components/logo-field";
import { Alert, Card, PageHeader, formatDate } from "@/components/ui";
import { accentStyle } from "@/lib/accent";
import { patch } from "@/lib/api";
import type { EventAdmin, EventInput, EventUsage } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { AccessPanel } from "./access-panel";
import { MatchQualityPanel } from "./match-quality-panel";
import { MembersPanel } from "./members-panel";
import { ModerationPanel } from "./moderation-panel";
import { PhotosPanel } from "./photos-panel";

export type Tab = "settings" | "access" | "members" | "photos" | "moderation" | "quality";

const LABELS: Record<Tab, string> = {
  settings: "Settings",
  access: "Access",
  members: "Members",
  photos: "Photos",
  moderation: "Moderation",
  quality: "Match quality",
};

export function EventAdminView({ id, initialTab }: { id: string; initialTab: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const { data: event, error, loading, setData } = useApi<EventAdmin>(`/api/events/${id}/admin`);

  if (loading) return <p className="text-sm text-muted">Loading…</p>;
  if (error || !event) {
    return <Alert>{error?.status === 403 ? "You don't manage this event." : error?.message}</Alert>;
  }

  async function save(input: EventInput) {
    setData(await patch<EventAdmin>(`/api/events/${id}`, input));
  }

  return (
    <div className={event.accent_color ? "event-accent" : undefined} style={accentStyle(event.accent_color)}>
      <PageHeader title={event.name} subtitle={event.date ? formatDate(event.date) : undefined} />
      <PlanUsage eventId={event.id} />
      <div role="tablist" className="-mx-4 mb-6 flex gap-1 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
        {(Object.keys(LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium transition ${
              tab === t ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {LABELS[t]}
          </button>
        ))}
      </div>
      {tab === "settings" && (
        <div className="space-y-6">
          <Card>
            <EventForm key={event.id} initial={initialInput(event)} submitLabel="Save changes" onSubmit={save} />
          </Card>
          <Card>
            <LogoField event={event} onChange={setData} />
          </Card>
        </div>
      )}
      {tab === "access" && <AccessPanel event={event} onChange={setData} />}
      {tab === "members" && <MembersPanel eventId={event.id} />}
      {tab === "photos" && <PhotosPanel event={event} onEditSettings={() => setTab("settings")} />}
      {tab === "moderation" && <ModerationPanel event={event} />}
      {tab === "quality" && <MatchQualityPanel eventId={event.id} />}
    </div>
  );
}

/** Paid events: the plan and how much of it is used. Admin-made events have no limits. */
function PlanUsage({ eventId }: { eventId: string }) {
  const { data } = useApi<EventUsage>(`/api/events/${eventId}/usage`);
  if (!data?.plan || data.max_attendees === null || data.max_photos === null) return null;
  const near = data.attendees >= data.max_attendees * 0.9 || data.photos >= data.max_photos * 0.9;
  return (
    <p className="-mt-6 mb-6 text-sm text-muted">
      {data.plan_name} plan · {data.attendees.toLocaleString()} / {data.max_attendees.toLocaleString()} attendees ·{" "}
      {data.photos.toLocaleString()} / {data.max_photos.toLocaleString()} photos
      {near && (
        <>
          {" "}· <Link href="/pricing" className="font-medium text-ink underline">Need more? See plans</Link>
        </>
      )}
    </p>
  );
}
