import type { CSSProperties } from "react";

// A contact sheet of abstract event "photos" (shapes in theme colours, no people). Five
// frames are "yours": the hero animation dims the rest (globals.css, "Landing page").
const COLS = 8;
const ROWS = 5;
const MATCHES = new Set([3, 10, 21, 28, 36]);

const SKIES = ["var(--color-accent-soft)", "var(--color-mist)", "var(--color-line)", "var(--color-paper)"];
const GROUNDS = ["var(--color-accent)", "var(--color-muted)", "var(--color-highlight)", "var(--color-ink)"];

// Deterministic "random" so server and client render the same sheet.
function pick<T>(list: T[], i: number, salt: number): T {
  return list[(i * 7 + salt * 13 + ((i * i) % 5)) % list.length];
}

function Tile({ i, match }: { i: number; match: number | null }) {
  const horizon = 45 + ((i * 17) % 30); // percent from the top
  const style = {
    "--i": i,
    "--m": match ?? 0,
    background: `linear-gradient(to bottom, ${pick(SKIES, i, 1)} 0 ${horizon}%, ${pick(GROUNDS, i, 2)} ${horizon}% 100%)`,
  } as CSSProperties;
  const light = (i * 29) % 70;
  return (
    <div className="sheet-tile relative aspect-[4/3] overflow-hidden rounded-[3px]" style={style} data-match={match !== null ? "" : undefined}>
      {/* a light, a table, a balloon: shapes, not people */}
      <span className="absolute size-[18%] rounded-full bg-highlight/70" style={{ left: `${10 + light}%`, top: "12%" }} />
      {i % 3 === 0 && <span className="absolute bottom-[14%] left-[20%] h-[16%] w-[45%] rounded-sm bg-paper/50" />}
      {i % 4 === 1 && <span className="absolute bottom-[30%] right-[18%] h-[24%] w-[12%] rounded-full bg-accent/60" />}
    </div>
  );
}

export function ContactSheet() {
  let m = 0;
  return (
    <figure className="w-full">
      <div aria-hidden="true" className="grid gap-1.5 rounded-xl border border-line bg-paper p-3" style={{ gridTemplateColumns: `repeat(${COLS}, minmax(0, 1fr))` }}>
        {Array.from({ length: COLS * ROWS }, (_, i) => (
          <Tile key={i} i={i} match={MATCHES.has(i) ? m++ : null} />
        ))}
      </div>
      <figcaption className="mt-3 text-sm text-muted">
        2,140 photos from one summer party. A selfie finds the {MATCHES.size} you&apos;re in.
      </figcaption>
    </figure>
  );
}
