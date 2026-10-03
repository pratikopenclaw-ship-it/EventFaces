"use client";

import { useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { SelfieCapture } from "@/components/selfie-capture";
import { Alert, Button } from "@/components/ui";
import { RawBody, post } from "@/lib/api";
import { useApi } from "@/lib/use-api";

type Step = "choose" | "selfie" | "done";

export function RemovalSubmit({ token }: { token: string }) {
  const info = useApi<{ event_name: string; email: string }>(`/api/removal-requests/${token}`);
  const [step, setStep] = useState<Step>("choose");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(image?: Blob, contentType?: string) {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/removal-requests/${token}/submit`, image && contentType ? new RawBody(image, contentType) : undefined);
      setStep("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit");
    } finally {
      setBusy(false);
    }
  }

  if (info.loading) return <AuthCard title="Loading…">One moment.</AuthCard>;
  if (info.error || !info.data) {
    return (
      <AuthCard title="Link unavailable">
        <Alert>{info.error?.message ?? "This link is invalid or has expired."}</Alert>
      </AuthCard>
    );
  }
  if (step === "done") {
    return (
      <AuthCard title="Request sent">
        <p className="text-sm text-muted">
          The organizers of {info.data.event_name} will review it and email {info.data.email} with the outcome.
        </p>
      </AuthCard>
    );
  }
  if (step === "selfie") {
    return (
      <div className="space-y-4">
        {error && (
          <div className="mx-auto max-w-xl">
            <Alert>{error}</Alert>
          </div>
        )}
        {/* Non-users may not have a camera handy, so a file is allowed here. */}
        <SelfieCapture key={error ?? "s"} allowUpload busy={busy} onSubmit={(img, type) => void submit(img, type)} />
      </div>
    );
  }

  return (
    <AuthCard title={`Removal request: ${info.data.event_name}`}>
      <div className="space-y-4 text-sm text-muted">
        {error && <Alert>{error}</Alert>}
        <p>
          Adding a reference photo of yourself lets us find the pictures you appear in. It&apos;s compared once with
          this event&apos;s photos and <strong>deleted immediately</strong>. We don&apos;t show you the matches; the
          organizers review them.
        </p>
        <Button className="w-full" onClick={() => setStep("selfie")}>
          Add a reference photo
        </Button>
        <Button variant="secondary" className="w-full" disabled={busy} onClick={() => void submit()}>
          Send without a photo
        </Button>
      </div>
    </AuthCard>
  );
}
