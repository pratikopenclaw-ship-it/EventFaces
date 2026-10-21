"use client";

import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { del } from "@/lib/api";
import type { Device } from "@/lib/types";
import { useApi } from "@/lib/use-api";

/** Phones and tablets signed in to the app, so a lost one can be signed out from the web
 * (the app has the same list under Settings → Devices). */
export function DevicesCard() {
  const devices = useApi<Device[]>("/api/me/devices");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function signOut(device: Device) {
    setBusy(device.id);
    setError(null);
    try {
      await del(`/api/me/devices/${device.id}`);
      await devices.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't sign out that device");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <section aria-labelledby="devices-heading">
        <h2 id="devices-heading" className="font-medium">
          Signed-in devices
        </h2>
        <p className="mt-1 text-sm text-muted">Phones and tablets signed in to the EventFaces app. Sign out one you no longer use.</p>
        {error && (
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
        )}
        {devices.data === null ? (
          <p className="mt-4 text-sm text-muted">{devices.error ? "Couldn't load your devices." : "Loading…"}</p>
        ) : devices.data.length === 0 ? (
          <p className="mt-4 text-sm text-muted">No phones or tablets are signed in to the app.</p>
        ) : (
          <ul className="mt-4 divide-y divide-line">
            {devices.data.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">{d.name}</p>
                  <p className="text-xs text-muted">
                    App {d.app_version} · last used {new Date(d.last_seen_at).toLocaleDateString()}
                  </p>
                </div>
                <Button
                  variant="secondary"
                  aria-label={`Sign out ${d.name}`}
                  disabled={busy === d.id}
                  onClick={() => void signOut(d)}
                >
                  {busy === d.id ? "Signing out…" : "Sign out"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </Card>
  );
}
