"use client";

import { useState } from "react";

import { GuidedCapture, type CapturedShot, type SubmitResult } from "@/components/guided-capture";
import { Alert, Button, Card } from "@/components/ui";
import { ApiError, RawBody, del, post } from "@/lib/api";
import type { SelfieRequirements, Shot } from "@/lib/face-guidance";
import type { ConsentInfo, EventPublic, MatchedPhoto, SearchResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { ConsentPanel } from "./consent-panel";
import { PhotoGallery } from "./photo-gallery";

type Step = "auto" | "capture" | "results";

interface Rejection {
  detail: string;
  code: string;
  shot: Shot | "any";
}

function isRejection(body: unknown): body is Rejection {
  return !!body && typeof body === "object" && "code" in body && "shot" in body;
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

  if (consent.loading || previous.loading || requirements.loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (consent.error) return <Alert>{consent.error.message}</Alert>;
  const info = consent.data;
  const req = requirements.data;
  if (!info || !req) return null;

  if (!info.given) {
    return <ConsentPanel info={info} onGiven={(c) => consent.setData(c)} />;
  }

  const uploadAllowed = req.global_file_upload && event.allow_selfie_file_upload;

  function showResults(r: SearchResult) {
    setResults(r.matches.map((m) => ({ ...m, verdict: null })));
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
      showResults(await post<SearchResult>(`/api/events/${event.id}/search?source=camera`, body));
    } catch (e) {
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
      showResults(await post<SearchResult>(`/api/events/${event.id}/search?source=upload`, new RawBody(file, type)));
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

  return (
    <div className="space-y-6">
      {error && (
        <div className="mx-auto max-w-xl">
          <Alert>{error}</Alert>
        </div>
      )}

      {effective === "capture" ? (
        <>
          <GuidedCapture key={attempt} requirements={req} busy={searching} onSubmit={searchCamera} />
          {uploadAllowed && (
            <label className="block text-center text-sm text-ink/60">
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
        <Card className="mx-auto max-w-xl text-center">
          <h2 className="font-display text-2xl">No photos found yet</h2>
          <p className="mt-2 text-sm text-ink/60">
            We couldn&apos;t find you in this event&apos;s photos. More photos may be added later.
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <Button onClick={() => setStep("capture")}>Try again</Button>
            <MissingButton eventId={event.id} />
          </div>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-2xl">{results ? "We found you" : "Your photos"}</h2>
            <div className="flex gap-2">
              <MissingButton eventId={event.id} />
              <Button variant="secondary" onClick={() => setStep("capture")}>
                Search again
              </Button>
            </div>
          </div>
          <PhotoGallery
            eventId={event.id}
            photos={shown}
            onVerdict={(id, verdict) => {
              const update = (list: MatchedPhoto[]) =>
                verdict === "not_me" ? list.filter((p) => p.id !== id) : list.map((p) => (p.id === id ? { ...p, verdict } : p));
              setResults((r) => (r ? update(r) : r));
              previous.setData(update(earlier));
            }}
          />
        </>
      )}

      <p className="pt-6 text-center text-xs text-ink/45">
        Face-search consent given {info.given_at ? new Date(info.given_at).toLocaleDateString() : ""}.{" "}
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
