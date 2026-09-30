"use client";

import { Columns, HBars, SERIES, StackedColumns } from "@/components/charts";
import { Card } from "@/components/ui";
import { lookup } from "@/lib/safe";
import type { MatchQuality } from "@/lib/types";

const REASONS: Record<string, string> = {
  resolution_too_low: "Resolution too low",
  no_face: "No face found",
  multiple_faces: "More than one person",
  low_confidence: "Face not clearly visible",
  face_too_small: "Too far away",
  face_too_large: "Too close",
  yaw_out_of_range: "Head turned too far",
  pitch_out_of_range: "Looking up/down",
  roll_out_of_range: "Head tilted",
  not_facing_camera: "Front shot not frontal",
  wrong_turn_left: "Didn't turn left",
  wrong_turn_right: "Didn't turn right",
  too_blurry: "Blurry",
  too_dark: "Too dark",
  too_bright: "Too bright",
  different_people: "Shots show different people",
  unreadable: "Unreadable image",
};

/** Server-provided codes are looked up as own properties only (no prototype members). */
export const reasonLabel = (code: string): string => lookup(REASONS, code) ?? code;

const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-line bg-paper px-4 py-3">
      <p className="text-xs text-ink/70">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
      {note && <p className="text-xs text-ink/70">{note}</p>}
    </div>
  );
}

export function MatchQualityView({ q }: { q: MatchQuality }) {
  const rated = q.bands.reduce((a, b) => a + b.me + b.not_me, 0);
  const wrong = q.bands.reduce((a, b) => a + b.not_me, 0);
  const at = (t: number) => (t - q.bands[0].lower) / (q.bands[0].upper - q.bands[0].lower);
  const markers = [
    { at: at(q.current_possible), label: `possible ≥ ${q.current_possible.toFixed(2)}` },
    { at: at(q.current_best), label: `best ≥ ${q.current_best.toFixed(2)}` },
    ...(q.suggested_threshold !== null && Math.abs(q.suggested_threshold - q.current_possible) > 1e-6
      ? [{ at: at(q.suggested_threshold), label: `suggested ${q.suggested_threshold.toFixed(2)}` }]
      : []),
  ];
  const reasons = Object.entries(q.rejection_reasons)
    .sort((a, b) => b[1] - a[1])
    .map(([code, value]) => ({ label: reasonLabel(code), value }));

  return (
    <div className="space-y-6">
      <Card>
        <p className="text-sm text-ink/70">Suggested match threshold</p>
        <p className="mt-1 text-5xl font-semibold tracking-tight text-ink">
          {q.suggested_threshold === null ? "–" : q.suggested_threshold.toFixed(2)}
        </p>
        <p className="mt-2 max-w-2xl text-sm text-ink/70">{q.suggestion_note}</p>
        <p className="mt-1 text-xs text-ink/70">
          Current: possible ≥ {q.current_possible.toFixed(2)}, best ≥ {q.current_best.toFixed(2)} (set{" "}
          <code>FACE_MATCH_THRESHOLD</code> / <code>MATCH_BEST_THRESHOLD</code>).
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Searches" value={q.searches.toLocaleString()} />
        <Stat label="Rated matches" value={rated.toLocaleString()} />
        <Stat label="Wrong-match rate" value={pct(rated ? wrong / rated : null)} note={`${wrong} "Not me"`} />
        <Stat label="Missing-photo reports" value={q.missing_reports.toLocaleString()} />
        <Stat label="Selfies passing checks" value={pct(q.shots_total ? q.shots_passed / q.shots_total : null)} note={`${q.shots_total} shots`} />
      </div>

      <Card>
        <h3 className="font-medium">Feedback by similarity</h3>
        <p className="mb-4 text-xs text-ink/70">
          How attendees rated their matches, by similarity score. Orange at high similarity means the threshold is too
          low; the suggestion is the lowest score where at least 90% of ratings are &quot;This is me&quot;.
        </p>
        <StackedColumns
          ariaLabel="Match feedback by similarity band"
          series={[
            { name: "This is me", color: SERIES.blue },
            { name: "Not me", color: SERIES.orange },
          ]}
          markers={markers}
          data={q.bands.map((b) => ({
            label: b.lower.toFixed(2).slice(1),
            values: [b.me, b.not_me],
            note: `${b.lower.toFixed(2)}–${b.upper.toFixed(2)} · wrong ${pct(b.wrong_rate)}`,
          }))}
        />
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-ink/70">Show as table</summary>
          <table className="mt-2 w-full text-left text-xs" style={{ fontVariantNumeric: "tabular-nums" }}>
            <thead className="text-ink/70">
              <tr>
                <th className="py-1 font-medium">Similarity</th>
                <th className="py-1 font-medium">This is me</th>
                <th className="py-1 font-medium">Not me</th>
                <th className="py-1 font-medium">Wrong rate</th>
              </tr>
            </thead>
            <tbody>
              {q.bands
                .filter((b) => b.me + b.not_me > 0)
                .map((b) => (
                  <tr key={b.lower} className="border-t border-line">
                    <td className="py-1">
                      {b.lower.toFixed(2)}–{b.upper.toFixed(2)}
                    </td>
                    <td className="py-1">{b.me}</td>
                    <td className="py-1">{b.not_me}</td>
                    <td className="py-1">{pct(b.wrong_rate)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </details>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h3 className="font-medium">Selfie quality scores</h3>
          <p className="mb-4 text-xs text-ink/70">Composite 0–100 of sharpness, light, pose, face size and detection confidence, per shot.</p>
          <Columns
            ariaLabel="Distribution of selfie quality scores"
            valueLabel="shots"
            data={q.quality_histogram.map((value, i) => ({ label: i === 9 ? "90+" : `${i * 10}`, value }))}
          />
        </Card>
        <Card>
          <h3 className="font-medium">Why selfies were rejected</h3>
          <p className="mb-4 text-xs text-ink/70">Shots that failed the quality checks, by reason.</p>
          {reasons.length ? <HBars data={reasons} /> : <p className="text-sm text-ink/70">No rejected selfies yet.</p>}
        </Card>
      </div>
    </div>
  );
}
