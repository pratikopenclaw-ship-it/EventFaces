"use client";

import { useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button } from "@/components/ui";
import { post } from "@/lib/api";

type Scope = "event" | "all";

const DONE: Record<Scope, string> = {
  event: "You won't get new-photo alerts for this event any more.",
  all: "You won't get any new-photo alerts any more.",
};

/** The server answers the same for unknown or expired tokens, so this page never tells
 * whether a link was real. */
export function UnsubscribeForm({ token }: { token: string }) {
  const [done, setDone] = useState<Scope | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(token ? null : "This link is missing its token.");

  async function stop(scope: Scope) {
    setBusy(true);
    setError(null);
    try {
      await post("/api/alerts/unsubscribe", { token, scope });
      setDone(scope);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save, try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="New-photo alerts">
      {done ? (
        <p role="status" className="text-sm">
          {DONE[done]} You can turn them back on from the event page or your account.
        </p>
      ) : (
        <div className="space-y-4">
          {error && <Alert>{error}</Alert>}
          <p className="text-sm text-muted">We email you when new photos are added to an event you searched. Stop them?</p>
          <Button className="w-full" disabled={!token || busy} onClick={() => void stop("event")}>
            Stop alerts for this event
          </Button>
          <Button variant="secondary" className="w-full" disabled={!token || busy} onClick={() => void stop("all")}>
            Stop all new-photo alerts
          </Button>
        </div>
      )}
    </AuthCard>
  );
}
