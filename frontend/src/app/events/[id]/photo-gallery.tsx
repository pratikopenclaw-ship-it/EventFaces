"use client";

import { useEffect, useState } from "react";

import { Alert, Button } from "@/components/ui";
import { post, triggerDownload } from "@/lib/api";
import type { DownloadTicket, MatchedPhoto, Verdict } from "@/lib/types";

import { ReportDialog } from "./report-dialog";

const SECTIONS = [
  { key: "best", title: "Best matches", note: null },
  { key: "possible", title: "Possible matches", note: "Less certain. Please tell us if these are you." },
  { key: "upload", title: "Your uploads", note: null },
] as const;

const sectionOf = (p: MatchedPhoto) => p.tier ?? "upload";

export function PhotoGallery({
  eventId,
  photos: unordered,
  onVerdict,
}: {
  eventId: string;
  photos: MatchedPhoto[];
  onVerdict: (photoId: string, verdict: Verdict) => void;
}) {
  // Best first, then possible, then own uploads; the lightbox walks this order.
  const photos = SECTIONS.flatMap((s) => unordered.filter((p) => sectionOf(p) === s.key));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reporting, setReporting] = useState<string | null>(null);

  async function rate(photoId: string, verdict: Verdict) {
    setError(null);
    try {
      await post(`/api/events/${eventId}/feedback`, { photo_id: photoId, verdict });
      if (verdict === "not_me") {
        setOpen(null);
        setSelected((prev) => {
          const next = new Set(prev);
          next.delete(photoId);
          return next;
        });
      }
      onVerdict(photoId, verdict);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your answer");
    }
  }

  async function download(ids: string[]) {
    setBusy(true);
    setError(null);
    try {
      const ticket = await post<DownloadTicket>(`/api/events/${eventId}/downloads`, { photo_ids: ids });
      triggerDownload(ticket.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Keyboard navigation in the lightbox
  useEffect(() => {
    if (open === null) return;
    function onKey(e: KeyboardEvent) {
      if (reporting) return; // the report dialog owns the keyboard
      if (e.key === "Escape") setOpen(null);
      if (e.key === "ArrowRight") setOpen((i) => (i === null ? i : Math.min(photos.length - 1, i + 1)));
      if (e.key === "ArrowLeft") setOpen((i) => (i === null ? i : Math.max(0, i - 1)));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, photos.length, reporting]);

  const current = open === null ? null : photos[open];

  return (
    // Photos always sit on a dark background, whatever the theme (the switcher says so).
    <div className="theme-dark space-y-4 rounded-2xl bg-canvas p-4 sm:p-5">
      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {photos.length} {photos.length === 1 ? "photo" : "photos"}
          {selected.size > 0 && ` · ${selected.size} selected`}
        </p>
        <div className="flex gap-2">
          {selected.size > 0 && (
            <Button variant="secondary" disabled={busy} onClick={() => void download([...selected])}>
              Download selected
            </Button>
          )}
          <Button disabled={busy} onClick={() => void download(photos.map((p) => p.id))}>
            {photos.length === 1 ? "Download" : `Download all (${photos.length})`}
          </Button>
        </div>
      </div>

      {SECTIONS.map((section) => {
        const items = photos.filter((p) => sectionOf(p) === section.key);
        if (items.length === 0) return null;
        return (
          <section key={section.key} className="space-y-3">
            <div className="flex items-baseline gap-2">
              <h3 className="font-medium">{section.title}</h3>
              <span className="text-sm text-muted">{items.length}</span>
              {section.note && <span className="text-xs text-muted">· {section.note}</span>}
            </div>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {items.map((p) => (
                <li key={p.id} className="group overflow-hidden rounded-xl bg-paper ring-1 ring-line">
                  <div className="relative">
                    <button onClick={() => setOpen(photos.indexOf(p))} className="block aspect-square w-full bg-mist" aria-label="Open photo">
                      {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                      <img
                        src={`/api/events/${eventId}/photos/${p.id}/thumb`}
                        alt=""
                        loading="lazy"
                        className="h-full w-full object-cover transition group-hover:scale-[1.02]"
                      />
                    </button>
                    <label className="absolute left-2 top-2 flex size-7 cursor-pointer items-center justify-center rounded-full bg-paper/90 shadow">
                      <input
                        type="checkbox"
                        aria-label="Select photo"
                        checked={selected.has(p.id)}
                        onChange={() => toggle(p.id)}
                        className="size-4 accent-accent"
                      />
                    </label>
                  </div>
                  {p.tier && (
                    <div className="flex items-center justify-between gap-1 px-2 py-1.5 text-xs">
                      {p.verdict === "me" ? (
                        <span className="font-medium text-leaf">✓ This is me</span>
                      ) : (
                        <>
                          <button onClick={() => void rate(p.id, "me")} className="rounded-md px-2 py-1 font-medium text-muted hover:bg-leaf/10 hover:text-leaf">
                            This is me
                          </button>
                          <button onClick={() => void rate(p.id, "not_me")} className="rounded-md px-2 py-1 text-muted hover:bg-alarm/10 hover:text-alarm">
                            Not me
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}

      {current && open !== null && (
        <div
          role="dialog"
          aria-modal="true"
          className="theme-dark fixed inset-0 z-50 flex flex-col bg-canvas/95 p-4"
          onClick={(e) => e.target === e.currentTarget && setOpen(null)}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink/80">
            <span className="whitespace-nowrap">
              {open + 1} / {photos.length}
            </span>
            {/* Wraps onto a second row on phones instead of squeezing the labels. */}
            <div className="flex flex-wrap justify-end gap-1 sm:gap-2 [&>button]:whitespace-nowrap">
              {current.tier && current.verdict !== "me" && (
                <>
                  <Button variant="secondary" onClick={() => void rate(current.id, "me")}>
                    This is me
                  </Button>
                  <Button variant="ghost" className="text-ink hover:bg-mist hover:text-ink" onClick={() => void rate(current.id, "not_me")}>
                    Not me
                  </Button>
                </>
              )}
              <Button variant="secondary" disabled={busy} onClick={() => void download([current.id])}>
                Download
              </Button>
              <Button
                variant="ghost"
                className="text-ink hover:bg-mist hover:text-ink"
                onClick={() => setReporting(current.id)}
              >
                Report
              </Button>
              <Button variant="ghost" className="text-ink hover:bg-mist hover:text-ink" onClick={() => setOpen(null)}>
                Close
              </Button>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center gap-4 py-4">
            <Button
              variant="ghost"
              aria-label="Previous"
              className="text-2xl text-ink hover:bg-mist hover:text-ink"
              disabled={open === 0}
              onClick={() => setOpen(open - 1)}
            >
              ‹
            </Button>
            {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
            <img
              key={current.id}
              src={`/api/events/${eventId}/photos/${current.id}/preview`}
              alt=""
              className="max-h-full min-w-0 max-w-full rounded-lg object-contain"
            />
            <Button
              variant="ghost"
              aria-label="Next"
              className="text-2xl text-ink hover:bg-mist hover:text-ink"
              disabled={open === photos.length - 1}
              onClick={() => setOpen(open + 1)}
            >
              ›
            </Button>
          </div>
          {reporting && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/60 p-4">
              <ReportDialog eventId={eventId} photoId={reporting} onClose={() => setReporting(null)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
