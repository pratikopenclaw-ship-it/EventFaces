"use client";

import { MatchQualityView } from "@/components/match-quality";
import { Alert } from "@/components/ui";
import type { MatchQuality } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export function MatchQualityPanel({ eventId }: { eventId: string }) {
  const { data, error, loading } = useApi<MatchQuality>(`/api/events/${eventId}/match-quality`);
  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (error || !data) return <Alert>{error?.message ?? "Could not load match quality"}</Alert>;
  return <MatchQualityView q={data} />;
}
