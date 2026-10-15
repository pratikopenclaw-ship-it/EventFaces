"use client";

import Link from "next/link";
import { useState } from "react";

import { EventForm, initialInput } from "@/components/event-form";
import { LogoField } from "@/components/logo-field";
import { EventCover } from "@/components/event-cover";
import { Alert, Card, formatDate } from "@/components/ui";
import { accentStyle } from "@/lib/accent";
import { patch } from "@/lib/api";
import type {
  EventAdmin,
  EventInput,
  EventUsage,
  Member,
  ModerationItem,
  PhotoReport,
  RemovalRequestItem,
  SearchLogRow,
  SyncStatus,
} from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { AccessPanel } from "./access-panel";
import { MatchQualityPanel } from "./match-quality-panel";
import { MembersPanel } from "./members-panel";
import { ModerationPanel } from "./moderation-panel";
import { PhotosPanel } from "./photos-panel";
import { VideosPanel } from "./videos-panel";

export type Tab = "settings" | "access" | "members" | "photos" | "videos" | "moderation" | "quality";

const LABELS: Record<Tab, string> = {
  settings: "Settings",
  access: "Access",
  members: "Members",
  photos: "Photos",
  videos: "Videos",
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
      <EventCover event={event} subtitle={event.date ? formatDate(event.date) : undefined}>
        <PlanUsage eventId={event.id} />
      </EventCover>
      <StatsRow eventId={event.id} onTabChange={setTab} />
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
      {tab === "videos" && <VideosPanel eventId={event.id} />}
      {tab === "moderation" && <ModerationPanel event={event} />}
      {tab === "quality" && <MatchQualityPanel eventId={event.id} />}
    </div>
  );
}

/** At-a-glance numbers, visible under the cover regardless of which tab is open. */
function StatsRow({ eventId, onTabChange }: { eventId: string; onTabChange: (t: Tab) => void }) {
  const sync = useApi<SyncStatus>(`/api/events/${eventId}/sync`);
  const members = useApi<Member[]>(`/api/events/${eventId}/members`);
  const searchLog = useApi<SearchLogRow[]>(`/api/events/${eventId}/search-log`);
  const queue = useApi<ModerationItem[]>(`/api/events/${eventId}/moderation`);
  const reports = useApi<PhotoReport[]>(`/api/events/${eventId}/reports`);
  const removals = useApi<RemovalRequestItem[]>(`/api/events/${eventId}/removal-requests`);

  if ([sync, members, searchLog, queue, reports, removals].some((r) => r.loading)) return null;

  const approved = members.data?.filter((m) => m.status === "approved").length ?? 0;
  const pending = members.data?.filter((m) => m.status === "pending").length ?? 0;

  const searches = searchLog.data?.length ?? 0;
  const matched = searchLog.data?.filter((s) => s.match_count > 0).length ?? 0;
  const matchRate = searches > 0 ? Math.round((matched / searches) * 100) : null;

  const needsAttention = (queue.data?.length ?? 0) + (reports.data?.length ?? 0) + (removals.data?.length ?? 0);

  return (
    <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatTile
        label="Photos"
        value={sync.data?.published_photos ?? 0}
        description={sync.data ? `${sync.data.faces.toLocaleString()} faces found` : undefined}
        onClick={() => onTabChange("photos")}
      />
      <StatTile
        label="Members"
        value={approved}
        description={pending > 0 ? `${pending} pending` : undefined}
        onClick={() => onTabChange("members")}
      />
      <StatTile
        label="Searches"
        value={searches}
        description={matchRate !== null ? `${matchRate}% found a match` : undefined}
        onClick={() => onTabChange("members")}
      />
      <StatTile
        label="Needs attention"
        value={needsAttention}
        tone={needsAttention > 0 ? "warn" : "good"}
        description={needsAttention > 0 ? undefined : "All clear"}
        onClick={needsAttention > 0 ? () => onTabChange("moderation") : undefined}
      />
    </div>
  );
}

function StatTile({
  label,
  value,
  description,
  tone = "neutral",
  onClick,
}: {
  label: string;
  value: number;
  description?: string;
  tone?: "neutral" | "good" | "warn";
  onClick?: () => void;
}) {
  const valueColor = { neutral: "text-ink", good: "text-good", warn: "text-warn" }[tone];
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={`rounded-2xl border border-line bg-paper p-4 text-left ${
        onClick ? "transition hover:-translate-y-0.5 hover:border-ink/30 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:hover:translate-y-0" : ""
      }`}
    >
      <p className="text-sm text-muted">{label}</p>
      <p className={`mt-1 text-3xl font-semibold ${valueColor}`}>{value.toLocaleString()}</p>
      {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
    </Tag>
  );
}

/** Paid events: the plan and how much of it is used. Admin-made events have no limits. */
function PlanUsage({ eventId }: { eventId: string }) {
  const { data } = useApi<EventUsage>(`/api/events/${eventId}/usage`);
  if (!data?.plan || data.max_attendees === null || data.max_photos === null) return null;
  const near = data.attendees >= data.max_attendees * 0.9 || data.photos >= data.max_photos * 0.9;
  return (
    <p className="mt-2 text-sm">
      {data.plan_name} plan · {data.attendees.toLocaleString()} / {data.max_attendees.toLocaleString()} attendees ·{" "}
      {data.photos.toLocaleString()} / {data.max_photos.toLocaleString()} photos
      {near && (
        <>
          {" "}· <Link href="/pricing" className="font-medium underline">Need more? See plans</Link>
        </>
      )}
    </p>
  );
}
