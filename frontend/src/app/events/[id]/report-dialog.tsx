"use client";

import { useState } from "react";

import { Alert, Button, Field, Select, Textarea } from "@/components/ui";
import { post } from "@/lib/api";
import type { ReportReason } from "@/lib/types";

const REASONS: Record<ReportReason, string> = {
  its_me_remove: "I'm in this photo and want it removed",
  privacy: "It shows something private",
  inappropriate: "It's inappropriate",
  other: "Something else",
};

export function ReportDialog({ eventId, photoId, onClose }: { eventId: string; photoId: string; onClose: () => void }) {
  const [reason, setReason] = useState<ReportReason>("its_me_remove");
  const [details, setDetails] = useState("");
  const [state, setState] = useState<"form" | "sending" | "done">("form");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setState("sending");
    setError(null);
    try {
      await post(`/api/events/${eventId}/photos/${photoId}/report`, { reason, details });
      setState("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the report");
      setState("form");
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="report-title" className="w-full max-w-md rounded-2xl bg-paper p-6 text-ink shadow-xl">
      <h2 id="report-title" className="font-display text-xl">
        Report this photo
      </h2>
      {state === "done" ? (
        <>
          <p className="mt-3 text-sm text-muted">Thanks. The organizers will review it and can remove it from the event.</p>
          <Button className="mt-5 w-full" onClick={onClose}>
            Close
          </Button>
        </>
      ) : (
        <div className="mt-4 space-y-4">
          {error && <Alert>{error}</Alert>}
          <Field label="Reason">
            <Select value={reason} onChange={(e) => setReason(e.target.value as ReportReason)}>
              {Object.entries(REASONS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Details (optional)">
            <Textarea value={details} onChange={(e) => setDetails(e.target.value)} maxLength={1000} />
          </Field>
          <div className="flex gap-2">
            <Button className="flex-1" disabled={state === "sending"} onClick={() => void submit()}>
              {state === "sending" ? "Sending…" : "Send report"}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
