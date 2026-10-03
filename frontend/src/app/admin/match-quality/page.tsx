"use client";

import Link from "next/link";

import { MatchQualityView } from "@/components/match-quality";
import { Alert, PageHeader } from "@/components/ui";
import type { GlobalMatchQuality } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function GlobalMatchQualityPage() {
  const { data, error, loading } = useApi<GlobalMatchQuality>("/api/admin/match-quality");
  if (loading) return <p className="text-sm text-muted">Loading…</p>;
  if (error || !data) return <Alert>{error?.status === 403 ? "Only super admins can see this page." : error?.message}</Alert>;
  return (
    <>
      <PageHeader title="Match quality" subtitle="All events. Use this to tune the similarity thresholds." />
      <MatchQualityView q={data} />
      <div className="mt-6 overflow-x-auto rounded-2xl border border-line bg-paper">
        <table className="w-full text-left text-sm" style={{ fontVariantNumeric: "tabular-nums" }}>
          <thead className="border-b border-line text-muted">
            <tr>
              <th className="px-5 py-3 font-medium">Event</th>
              <th className="px-5 py-3 font-medium">Searches</th>
              <th className="px-5 py-3 font-medium">Rated</th>
              <th className="px-5 py-3 font-medium">Wrong-match rate</th>
              <th className="px-5 py-3 font-medium">Missing reports</th>
            </tr>
          </thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={e.event_id} className="border-b border-line last:border-0">
                <td className="px-5 py-3">
                  <Link href={`/admin/events/${e.event_id}?tab=quality`} className="text-accent hover:underline">
                    {e.event_name}
                  </Link>
                </td>
                <td className="px-5 py-3">{e.searches}</td>
                <td className="px-5 py-3">{e.feedback}</td>
                <td className="px-5 py-3">{e.wrong_rate === null ? "–" : `${Math.round(e.wrong_rate * 100)}%`}</td>
                <td className="px-5 py-3">{e.missing_reports}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
