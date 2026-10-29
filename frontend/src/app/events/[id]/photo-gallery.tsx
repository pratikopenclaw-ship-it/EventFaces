"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { Alert, Button } from "@/components/ui";
import { del, post, triggerDownload } from "@/lib/api";
import type { AddonCheckoutStart, DownloadTicket, MatchedPhoto, Verdict } from "@/lib/types";

import { ReportDialog } from "./report-dialog";

// Matches AddonCheckoutIn.photo_ids (backend/app/schemas/billing.py).
const MAX_ORDER_PHOTOS = 50;

type Section = { key: string; title: string; note: string | null };

const SECTIONS: Section[] = [
  { key: "best", title: "Best matches", note: null },
  { key: "possible", title: "Possible matches", note: "Less certain. Please tell us if these are you." },
  { key: "upload", title: "Your uploads", note: null },
];

export function PhotoGallery({
  eventId,
  photos: unordered,
  onVerdict,
  onShortlistChange,
  reveal = false,
  heading,
  shortlist = true,
  orderEdits = true,
}: {
  eventId: string;
  photos: MatchedPhoto[];
  onVerdict: (photoId: string, verdict: Verdict) => void;
  onShortlistChange?: (photoId: string, shortlisted: boolean) => void;
  /** Fresh search results: play the one-time reveal (globals.css, "Results reveal"). */
  reveal?: boolean;
  /** One section with this title instead of best / possible / uploads (shared photos). */
  heading?: string;
  /** Show the shortlist star (the shortlist only holds matched and own photos). */
  shortlist?: boolean;
  /** Offer the paid professional edit (web only; the iOS app has no purchase UI). */
  orderEdits?: boolean;
}) {
  const sections: Section[] = heading ? [{ key: "all", title: heading, note: null }] : SECTIONS;
  const sectionOf = (p: MatchedPhoto) => (heading ? "all" : (p.tier ?? "upload"));
  // Best first, then possible, then own uploads; the lightbox walks this order.
  const photos = sections.flatMap((s) => unordered.filter((p) => sectionOf(p) === s.key));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reporting, setReporting] = useState<string | null>(null);
  const router = useRouter();

  async function toggleShortlist(photo: MatchedPhoto) {
    const next = !photo.shortlisted;
    onShortlistChange?.(photo.id, next); // optimistic
    try {
      if (next) await post(`/api/events/${eventId}/photos/${photo.id}/shortlist`);
      else await del(`/api/events/${eventId}/photos/${photo.id}/shortlist`);
    } catch (e) {
      onShortlistChange?.(photo.id, photo.shortlisted); // revert
      setError(e instanceof Error ? e.message : "Couldn't update your shortlist");
    }
  }

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

  async function orderEdit(ids: string[]) {
    if (ids.length > MAX_ORDER_PHOTOS) {
      setError(`An order can hold up to ${MAX_ORDER_PHOTOS} photos. Select fewer and order the rest separately.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const start = await post<AddonCheckoutStart>(`/api/events/${eventId}/addons/checkout`, { kind: "human_edit", photo_ids: ids });
      // The test provider's page is ours; a real provider's hosted page would be on its own domain.
      if (start.checkout_url.startsWith("/")) router.push(start.checkout_url);
      else window.location.assign(start.checkout_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the order");
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
  const dialog = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLDivElement>(null);
  const swipeFrom = useRef<number | null>(null);
  const isOpen = open !== null;

  // Move focus into the viewer when it opens (keyboard and screen-reader users land in it).
  useEffect(() => {
    if (isOpen) dialog.current?.focus();
  }, [isOpen]);

  // Keep the current photo visible in the filmstrip.
  useEffect(() => {
    if (open === null) return;
    strip.current?.querySelector<HTMLElement>(`[data-index="${open}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [open]);

  function swipeEnd(x: number) {
    if (swipeFrom.current === null || open === null) return;
    const dx = x - swipeFrom.current;
    swipeFrom.current = null;
    if (Math.abs(dx) < 50) return;
    setOpen(dx < 0 ? Math.min(photos.length - 1, open + 1) : Math.max(0, open - 1));
  }

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
          {orderEdits && selected.size > 0 && (
            <Button variant="ghost" className="text-ink hover:bg-mist hover:text-ink" disabled={busy} onClick={() => void orderEdit([...selected])}>
              Order editing ({selected.size})
            </Button>
          )}
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

      {sections.map((section) => {
        const items = photos.filter((p) => sectionOf(p) === section.key);
        if (items.length === 0) return null;
        return (
          <section key={section.key} className="space-y-3">
            <div className="flex items-baseline gap-2">
              <h3 className="font-medium">{section.title}</h3>
              <span className="text-sm text-muted">{items.length}</span>
              {section.note && <span className="text-xs text-muted">· {section.note}</span>}
            </div>
            {/* Justified rows: each photo grows by its aspect ratio, so nothing is cropped
                into a square and rows end flush. The spacer keeps the last row natural. */}
            <ul className="flex flex-wrap gap-2 after:flex-[10] after:content-['']">
              {items.map((p) => {
                const ratio = p.width && p.height ? Math.min(2.5, Math.max(0.5, p.width / p.height)) : 4 / 3;
                const index = photos.indexOf(p);
                return (
                  <li
                    key={p.id}
                    className={`group overflow-hidden rounded-xl bg-paper ring-1 ring-line ${reveal ? "reveal-tile" : ""}`}
                    style={{ flexGrow: ratio, flexBasis: `${Math.round(ratio * 190)}px`, "--i": Math.min(index, 12) } as CSSProperties}
                  >
                    <div className="relative">
                      <button
                        onClick={() => setOpen(index)}
                        className="block w-full bg-mist"
                        style={{ aspectRatio: String(ratio) }}
                        aria-label="Open photo"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                        <img
                          src={`/api/events/${eventId}/photos/${p.id}/thumb`}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-cover transition group-hover:scale-[1.02] motion-reduce:transition-none"
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
                      {shortlist && (
                        <button
                          onClick={() => void toggleShortlist(p)}
                          aria-pressed={p.shortlisted}
                          aria-label={p.shortlisted ? "Remove from shortlist" : "Add to shortlist"}
                          className="absolute right-2 top-2 flex size-7 items-center justify-center rounded-full bg-paper/90 text-lg leading-none shadow"
                        >
                          <span className={p.shortlisted ? "text-accent" : "text-ink/40"}>{p.shortlisted ? "★" : "☆"}</span>
                        </button>
                      )}
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
                );
              })}
            </ul>
          </section>
        );
      })}

      {current && open !== null && (
        <div
          ref={dialog}
          role="dialog"
          aria-modal="true"
          aria-label="Photo viewer"
          tabIndex={-1}
          className="theme-dark fixed inset-0 z-50 flex flex-col bg-canvas/95 p-4 outline-none"
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
              {shortlist && (
                <Button
                  variant="ghost"
                  className="text-ink hover:bg-mist hover:text-ink"
                  onClick={() => void toggleShortlist(current)}
                >
                  {current.shortlisted ? "★ Shortlisted" : "☆ Shortlist"}
                </Button>
              )}
              {orderEdits && (
                <Button
                  variant="ghost"
                  className="text-ink hover:bg-mist hover:text-ink"
                  disabled={busy}
                  onClick={() => void orderEdit([current.id])}
                >
                  Order editing
                </Button>
              )}
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
          <div
            className="flex min-h-0 flex-1 touch-pan-y items-center justify-center gap-4 py-4"
            onPointerDown={(e) => (swipeFrom.current = e.clientX)}
            onPointerUp={(e) => swipeEnd(e.clientX)}
            onPointerCancel={() => (swipeFrom.current = null)}
          >
            <Button
              variant="ghost"
              aria-label="Previous"
              className="size-11 shrink-0 rounded-full bg-paper/80 p-0 text-2xl text-ink shadow hover:bg-mist hover:text-ink"
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
              draggable={false}
              className="max-h-full min-w-0 max-w-full select-none rounded-lg object-contain"
            />
            <Button
              variant="ghost"
              aria-label="Next"
              className="size-11 shrink-0 rounded-full bg-paper/80 p-0 text-2xl text-ink shadow hover:bg-mist hover:text-ink"
              disabled={open === photos.length - 1}
              onClick={() => setOpen(open + 1)}
            >
              ›
            </Button>
          </div>
          {photos.length > 1 && (
            <div ref={strip} className="flex shrink-0 justify-center-safe gap-2 overflow-x-auto pb-1" aria-label="All photos">
              {photos.map((p, i) => (
                <button
                  key={p.id}
                  data-index={i}
                  onClick={() => setOpen(i)}
                  aria-label={`Photo ${i + 1}`}
                  aria-current={i === open ? "true" : undefined}
                  className="size-14 shrink-0 overflow-hidden rounded-md opacity-60 ring-2 ring-transparent transition hover:opacity-100 aria-[current=true]:opacity-100 aria-[current=true]:ring-accent focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                  <img src={`/api/events/${eventId}/photos/${p.id}/thumb`} alt="" loading="lazy" className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          )}
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
