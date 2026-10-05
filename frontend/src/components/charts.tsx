"use client";

// Small, dependency-free SVG charts following the dataviz rules: thin marks (≤24px,
// 4px rounded data-end, square at the baseline), 2px surface gaps, solid hairline
// grid, text in ink tokens (never the series color), per-mark hover/focus tooltips.
// Palette (validated for CVD & contrast on white): slot 1 blue, slot 2 orange.

import { useEffect, useRef, useState, type ReactNode } from "react";

/** Render SVGs at the container's real pixel width so text stays at its true size. */
function useWidth<T extends HTMLElement>(fallback: number): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export const SERIES = { blue: "#2a78d6", orange: "#eb6834" } as const;
// Theme tokens, so charts follow light/dark (applied via style: var() isn't valid in SVG attributes).
const INK = {
  primary: "var(--color-ink)",
  secondary: "var(--color-muted)",
  muted: "var(--color-muted)",
  grid: "var(--color-line)",
  axis: "color-mix(in oklab, var(--color-ink) 30%, transparent)",
};

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg border border-line bg-paper px-3 py-2 text-xs shadow-lg"
      style={{ left: tip.x, top: tip.y - 8 }}
    >
      {tip.content}
    </div>
  );
}

function TipRow({ color, label, value }: { color?: string; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center gap-2 whitespace-nowrap">
      {color && <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: color }} />}
      <span className="font-semibold" style={{ color: INK.primary }}>
        {value}
      </span>
      <span style={{ color: INK.secondary }}>{label}</span>
    </div>
  );
}

/** Rounded-top column path: 4px radius at the data end, square at the baseline. */
function columnPath(x: number, y: number, w: number, h: number, roundTop: boolean): string {
  const r = roundTop ? Math.min(4, w / 2, h) : 0;
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

/** An even, "round" axis maximum so the midpoint tick is a whole number (counts). */
function niceMax(v: number): number {
  if (v <= 4) return 4;
  if (v <= 10) return 10;
  const pow = 10 ** Math.floor(Math.log10(v));
  const m = Math.ceil(v / pow) * pow;
  return m % 2 === 0 ? m : m + pow;
}

export interface StackedDatum {
  label: string;
  values: number[]; // one per series, bottom → top
  note?: string; // extra tooltip line
}

export interface Marker {
  at: number; // position in label units (index + fraction)
  label: string;
}

/** Stacked columns (e.g. confirmed vs. wrong matches per similarity band). */
export function StackedColumns({
  data,
  series,
  markers = [],
  height = 220,
  ariaLabel,
}: {
  data: StackedDatum[];
  series: { name: string; color: string }[];
  markers?: Marker[];
  height?: number;
  ariaLabel: string;
}) {
  const [tip, setTip] = useState<Tip | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>(640);
  const pad = { top: 28, right: 8, bottom: 28, left: 32 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(1, ...data.map((d) => d.values.reduce((a, b) => a + b, 0))));
  const slot = plotW / data.length;
  const barW = Math.min(24, slot * 0.6);
  const y = (v: number) => pad.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];

  return (
    <div ref={ref} className="relative" onPointerLeave={() => (setTip(null), setHover(null))}>
      {series.length > 1 && (
        // A legend for 2+ series only; a single series is named by the chart title.
        <div className="mb-2 flex flex-wrap gap-4 text-xs" style={{ color: INK.secondary }}>
          {series.map((s) => (
            <span key={s.name} className="flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-sm" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      {/* max-w-full + h-auto: before the first measurement the fallback width would stick out of
          narrow screens (a sideways scroll for a frame); the viewBox scales it down instead. */}
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block h-auto max-w-full" role="img" aria-label={ariaLabel}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} style={{ stroke: t === 0 ? INK.axis : INK.grid }} strokeWidth={1} />
            <text x={pad.left - 6} y={y(t) + 4} textAnchor="end" fontSize={11} style={{ fill: INK.muted, fontVariantNumeric: "tabular-nums" }}>
              {t}
            </text>
          </g>
        ))}
        {markers.map((m) => {
          const x = pad.left + m.at * slot;
          return (
            <g key={m.label}>
              <line x1={x} x2={x} y1={pad.top - 14} y2={pad.top + plotH} style={{ stroke: INK.primary }} strokeWidth={1} strokeOpacity={0.55} />
              <text x={x + 3} y={pad.top - 16} fontSize={11} style={{ fill: INK.secondary }}>
                {m.label}
              </text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const x = pad.left + i * slot + (slot - barW) / 2;
          const total = d.values.reduce((a, b) => a + b, 0);
          let acc = 0;
          const top = d.values.reduce((last, v, s) => (v > 0 ? s : last), -1);
          const show = () => {
            setHover(i);
            setTip({
              x: x + barW / 2,
              y: y(total),
              content: (
                <>
                  <div className="mb-1 font-medium" style={{ color: INK.primary }}>
                    {d.label}
                  </div>
                  {series.map((s, si) => (
                    <TipRow key={s.name} color={s.color} label={s.name} value={d.values[si]} />
                  ))}
                  {d.note && <div className="mt-1" style={{ color: INK.secondary }}>{d.note}</div>}
                </>
              ),
            });
          };
          return (
            <g
              key={d.label}
              tabIndex={0}
              role="img"
              aria-label={`${d.label}: ${series.map((s, si) => `${d.values[si]} ${s.name}`).join(", ")}`}
              onPointerMove={show}
              onFocus={show}
              onBlur={() => (setTip(null), setHover(null))}
              style={{ outline: "none" }}
            >
              {/* Hit target: the whole column slot, bigger than the painted mark. */}
              <rect x={pad.left + i * slot} y={pad.top} width={slot} height={plotH} fill="transparent" />
              {d.values.map((v, s) => {
                if (v <= 0) return null;
                const h = (v / max) * plotH;
                const yTop = y(acc + v);
                acc += v;
                // 2px surface gap between stacked segments.
                const gap = s < top ? 2 : 0;
                return (
                  <path
                    key={s}
                    d={columnPath(x, yTop + (s === top ? 0 : gap), barW, Math.max(0, h - gap), s === top)}
                    fill={series[s].color}
                    opacity={hover === null || hover === i ? 1 : 0.55}
                  />
                );
              })}
              {/* Labels mark each band's lower edge (a tick), so threshold markers line up with them. */}
              <line x1={pad.left + i * slot} x2={pad.left + i * slot} y1={pad.top + plotH} y2={pad.top + plotH + 4} style={{ stroke: INK.axis }} />
              <text x={pad.left + i * slot} y={height - pad.bottom + 16} textAnchor="middle" fontSize={11} style={{ fill: INK.muted }}>
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

/** Single-series columns (e.g. a histogram). No legend: the title names the series. */
export function Columns({
  data,
  color = SERIES.blue,
  height = 180,
  ariaLabel,
  valueLabel,
}: {
  data: { label: string; value: number }[];
  color?: string;
  height?: number;
  ariaLabel: string;
  valueLabel: string;
}) {
  return (
    <StackedColumns
      data={data.map((d) => ({ label: d.label, values: [d.value] }))}
      series={[{ name: valueLabel, color }]}
      height={height}
      ariaLabel={ariaLabel}
    />
  );
}

/** Horizontal bars with the value at the tip (ranked categories). */
export function HBars({ data, color = SERIES.blue }: { data: { label: string; value: number }[]; color?: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="space-y-2">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[minmax(0,11rem)_1fr] items-center gap-3 text-xs">
          <span className="truncate" style={{ color: INK.secondary }} title={d.label}>
            {d.label}
          </span>
          <span className="flex items-center gap-2">
            <span
              className="h-3 rounded-r"
              style={{ width: `${Math.max(2, (d.value / max) * 100)}%`, background: color, maxWidth: "calc(100% - 2.5rem)" }}
              role="img"
              aria-label={`${d.label}: ${d.value}`}
            />
            <span className="font-medium" style={{ color: INK.primary, fontVariantNumeric: "tabular-nums" }}>
              {d.value}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}
