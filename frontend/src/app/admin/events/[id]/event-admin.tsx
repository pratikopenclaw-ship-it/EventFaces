"use client";

import { useState } from "react";

import { EventForm, initialInput } from "@/components/event-form";
import { Alert, Card, PageHeader, formatDate } from "@/components/ui";
import { patch } from "@/lib/api";
import type { EventAdmin, EventInput } from "@/lib/types";
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

  if (loading) return <p className="text-sm text-ink/70">Loading…</p>;
  if (error || !event) {
    return <Alert>{error?.status === 403 ? "You don't manage this event." : error?.message}</Alert>;
  }

  async function save(input: EventInput) {
    setData(await patch<EventAdmin>(`/api/events/${id}`, input));
  }

  return (
    <>
      <PageHeader title={event.name} subtitle={event.date ? formatDate(event.date) : undefined} />
      <div role="tablist" className="-mx-4 mb-6 flex gap-1 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
        {(Object.keys(LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium transition ${
              tab === t ? "border-accent text-ink" : "border-transparent text-ink/70 hover:text-ink"
            }`}
          >
            {LABELS[t]}
          </button>
        ))}
      </div>
      {tab === "settings" && (
        <Card>
          <EventForm key={event.id} initial={initialInput(event)} submitLabel="Save changes" onSubmit={save} />
        </Card>
      )}
      {tab === "access" && <AccessPanel event={event} onChange={setData} />}
      {tab === "members" && <MembersPanel eventId={event.id} />}
      {tab === "photos" && <PhotosPanel event={event} onEditSettings={() => setTab("settings")} />}
      {tab === "moderation" && <ModerationPanel event={event} />}
      {tab === "quality" && <MatchQualityPanel eventId={event.id} />}
    </>
  );
}
