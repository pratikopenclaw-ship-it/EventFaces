"use client";

import { useEffect, useState } from "react";

import { FaceSearchIcon } from "@/components/empty-icons";
import { GuidedCapture, type CapturedShot, type SubmitResult } from "@/components/guided-capture";
import { Alert, Button, Card, EmptyState } from "@/components/ui";
import { ApiError, RawBody, del, get, post } from "@/lib/api";
import { oneOf } from "@/lib/safe";
import type { SelfieRequirements, Shot } from "@/lib/face-guidance";
import type { ConsentInfo, EventPublic, MatchedPhoto, QueuedSearch, SearchResult, SearchStatus, Verdict } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { ConsentPanel } from "./consent-panel";
import { PhotoGallery } from "./photo-gallery";

type Step = "auto" | "capture" | "results" | "queued";

const POLL_MS = 10_000;

function isQueued(r: SearchResult | QueuedSearch): r is QueuedSearch {
  return "queued" in r && r.queued === true;
}

interface Rejection {
  detail: string;
  code: string;
  shot: Shot | "any";
}

const SHOT_VALUES = ["front", "left", "right", "any"] as const;

/** Validates the 422 body before it drives UI state (the shot becomes an object key). */
export function isRejection(body: unknown): body is Rejection {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  return typeof b.code === "string" && typeof b.detail === "string" && oneOf(SHOT_VALUES, b.shot);
}

/** Concatenate the shots into one body; lengths go in a header (see app/api/selfie.py). */
function selfieSet(shots: { shot: string; blob: Blob }[]): RawBody {
  return new RawBody(new Blob(shots.map((s) => s.blob)), "application/x-selfie-set", {
    "X-Selfie-Shots": shots.map((s) => s.shot).join(","),
    "X-Selfie-Lengths": shots.map((s) => String(s.blob.size)).join(","),
  });
}

export function FindPhotos({ event }: { event: EventPublic }) {
  const consent = useApi<ConsentInfo>("/api/me/face-consent");
  const requirements = useApi<SelfieRequirements>("/api/selfie-requirements");
  const previous = useApi<MatchedPhoto[]>(`/api/events/${event.id}/my-photos`);
  const [step, setStep] = useState<Step>("auto");
  const [results, setResults] = useState<MatchedPhoto[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // A search queued while the service was busy: show it on return, and poll while open.
  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const s = await get<SearchStatus>(`/api/events/${event.id}/search-status`);
        if (!active) return;
        if (s.state === "queued") {
          setStep("queued");
        } else if (step === "queued") {
          if (s.state === "done") {
            setResults(null); // the finished search's grants arrive via my-photos
            await previous.reload();
            setStep("results");
          } else {
            setError(
              s.state === "rejected" && s.message
                ? s.message
                : s.state === "expired"
                  ? "We lost your queued search (the service restarted). Please search again."
                  : "Your queued search was cancelled. Please search again.",
            );
            setStep("capture");
          }
        }
      } catch {
        /* transient: try again on the next tick */
      }
    };
    if (step === "auto" || step === "queued") void check();
    const timer = step === "queued" ? setInterval(() => void check(), POLL_MS) : undefined;
    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `previous` is a stable loader
  }, [event.id, step]);

  if (consent.loading || previous.loading || requirements.loading) return <p className="text-sm text-muted">Loading…</p>;
  if (consent.error) return <Alert>{consent.error.message}</Alert>;
  const info = consent.data;
  const req = requirements.data;
  if (!info || !req) return null;

  if (!info.given) {
    return <ConsentPanel info={info} onGiven={(c) => consent.setData(c)} />;
  }

  const uploadAllowed = req.global_file_upload && event.allow_selfie_file_upload;

  function showResults(r: SearchResult) {
    setResults(r.matches.map((m) => ({ ...m, verdict: null, shortlisted: false })));
    setStep("results");
    void previous.reload();
  }

  async function searchCamera(shots: CapturedShot[]): Promise<SubmitResult> {
    setSearching(true);
    setError(null);
    try {
      // Fresh single-use token right before submitting (valid 60 s).
      const { token } = await post<{ token: string }>(`/api/events/${event.id}/capture-token`);
      const body = selfieSet(shots);
      body.headers["X-Capture-Token"] = token;
      const r = await post<SearchResult | QueuedSearch>(`/api/events/${event.id}/search?source=camera`, body);
      if (isQueued(r)) setStep("queued");
      else showResults(r);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setStep("queued"); // an earlier search is still queued
        return;
      }
      if (e instanceof ApiError && e.message === "consent_required") {
        await consent.reload();
        return;
      }
      if (e instanceof ApiError && isRejection(e.body)) {
        const retake = e.body.code === "different_people" || e.body.shot === "any" ? "all" : e.body.shot;
        return { retake, message: e.body.detail };
      }
      setError(e instanceof Error ? e.message : "Search failed");
      setAttempt((a) => a + 1); // remount capture
    } finally {
      setSearching(false);
    }
  }

  async function searchUpload(file: File) {
    setSearching(true);
    setError(null);
    try {
      const type = file.type || (/\.hei[cf]$/i.test(file.name) ? "image/heic" : "image/jpeg");
      const r = await post<SearchResult | QueuedSearch>(`/api/events/${event.id}/search?source=upload`, new RawBody(file, type));
      if (isQueued(r)) setStep("queued");
      else showResults(r);
    } catch (e) {
      setError(e instanceof ApiError && isRejection(e.body) ? e.body.detail : e instanceof Error ? e.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function withdraw() {
    if (!confirm("Withdraw consent? We'll forget which photos you matched, and you'll need to consent again to search.")) return;
    consent.setData(await del<ConsentInfo>("/api/me/face-consent"));
    setResults(null);
    setStep("auto");
    void previous.reload();
  }

  const earlier = previous.data ?? [];
  const effective: Step = step !== "auto" ? step : earlier.length > 0 ? "results" : "capture";
  const shown = results ?? earlier;

  function onVerdict(id: string, verdict: Verdict) {
    const update = (list: MatchedPhoto[]) =>
      verdict === "not_me" ? list.filter((p) => p.id !== id) : list.map((p) => (p.id === id ? { ...p, verdict } : p));
    setResults((r) => (r ? update(r) : r));
    previous.setData(update(earlier));
  }

  function onShortlistChange(id: string, shortlisted: boolean) {
    const update = (list: MatchedPhoto[]) => list.map((p) => (p.id === id ? { ...p, shortlisted } : p));
    setResults((r) => (r ? update(r) : r));
    previous.setData(update(earlier));
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="mx-auto max-w-xl">
          <Alert>{error}</Alert>
        </div>
      )}

      {effective === "queued" ? (
        <Card className="mx-auto max-w-xl text-center">
          <h2 className="font-display text-2xl">You&apos;re in the queue</h2>
          <p className="mt-2 text-sm text-muted">
            Lots of people are searching right now. We&apos;ll email you and show your photos here as soon as they&apos;re
            ready, usually within a few minutes. You can close this page.
          </p>
          <p role="status" aria-live="polite" className="mt-4 text-xs text-muted">
            Checking for your results…
          </p>
        </Card>
      ) : effective === "capture" ? (
        <>
          <GuidedCapture key={attempt} requirements={req} busy={searching} onSubmit={searchCamera} />
          {uploadAllowed && (
            <label className="block text-center text-sm text-muted">
              No camera?{" "}
              <span className="cursor-pointer font-medium text-accent hover:underline">
                Upload a photo of yourself
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/heic,image/heif"
                  className="sr-only"
                  disabled={searching}
                  onChange={(e) => e.target.files?.[0] && void searchUpload(e.target.files[0])}
                />
              </span>
            </label>
          )}
        </>
      ) : shown.length === 0 ? (
        <Card className="mx-auto max-w-xl">
          <EmptyState
            icon={<FaceSearchIcon className="size-6" />}
            title="No photos found yet"
            description="We couldn't find you in this event's photos. More photos may be added later."
            action={
              <div className="flex justify-center gap-2">
                <Button onClick={() => setStep("capture")}>Try again</Button>
                <MissingButton eventId={event.id} />
              </div>
            }
          />
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-3xl tracking-tight">{results ? foundHeadline(results) : "Your photos"}</h2>
            <div className="flex gap-2">
              <MissingButton eventId={event.id} />
              <Button variant="secondary" onClick={() => setStep("capture")}>
                Search again
              </Button>
            </div>
          </div>
          <PhotoGallery eventId={event.id} photos={shown} reveal={results !== null} onVerdict={onVerdict} onShortlistChange={onShortlistChange} />
        </>
      )}

      {earlier.some((p) => p.shortlisted) && (
        <div className="space-y-3">
          <h2 className="font-display text-xl tracking-tight">Your shortlist</h2>
          <PhotoGallery
            eventId={event.id}
            photos={earlier.filter((p) => p.shortlisted)}
            onVerdict={onVerdict}
            onShortlistChange={onShortlistChange}
          />
        </div>
      )}

      <p className="pt-6 text-center text-xs text-muted">
        Face-search consent given{" "}
        {info.given_at ? <time dateTime={info.given_at}>{new Date(info.given_at).toLocaleDateString()}</time> : null}.{" "}
        <button onClick={() => void withdraw()} className="underline hover:text-ink">
          Withdraw consent
        </button>
      </p>
    </div>
  );
}

function MissingButton({ eventId }: { eventId: string }) {
  const [state, setState] = useState<"idle" | "sent" | "error">("idle");
  if (state === "sent") return <span className="self-center text-sm text-leaf">Thanks, we&apos;ll use this to improve matching.</span>;
  return (
    <Button
      variant="ghost"
      onClick={() =>
        void post(`/api/events/${eventId}/feedback/missing`)
          .then(() => setState("sent"))
          .catch(() => setState("error"))
      }
    >
      {state === "error" ? "Couldn't send, try later" : "Photos of me are missing"}
    </Button>
  );
}

/** "You're in 12 photos": the matches (not the user's own uploads). */
function foundHeadline(matches: MatchedPhoto[]): string {
  const n = matches.filter((p) => p.tier).length;
  return n === 1 ? "You're in 1 photo" : `You're in ${n} photos`;
}
