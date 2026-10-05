"use client";

import { useEffect, useState } from "react";

export const SECTIONS = [
  { id: "how", label: "How it works" },
  { id: "privacy", label: "Privacy" },
  { id: "features", label: "Features" },
  { id: "pricing", label: "Pricing" },
  { id: "faq", label: "FAQ" },
  { id: "contact", label: "Contact" },
] as const;

/** Sticky in-page navigation; the section in view is marked (aria-current). */
export function SectionNav() {
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    const visible = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) visible.set(e.target.id, e.isIntersecting);
        // The first section (in page order) inside the middle band of the screen.
        setCurrent(SECTIONS.find((s) => visible.get(s.id))?.id ?? null);
      },
      { rootMargin: "-35% 0px -55% 0px" },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav aria-label="On this page" className="sticky top-0 z-20 -mx-4 mb-10 border-b border-line bg-canvas/90 backdrop-blur">
      <ul className="flex gap-1 overflow-x-auto px-4 py-2 text-sm [scrollbar-width:none]">
        {SECTIONS.map((s) => (
          <li key={s.id} className="shrink-0">
            <a
              href={`#${s.id}`}
              aria-current={current === s.id ? "true" : undefined}
              className="block rounded-full px-3 py-1.5 text-muted transition hover:text-ink focus-visible:outline-2 focus-visible:outline-accent aria-[current=true]:bg-accent-soft aria-[current=true]:text-ink"
            >
              {s.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
