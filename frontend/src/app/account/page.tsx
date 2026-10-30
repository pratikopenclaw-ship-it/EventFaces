"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/session";
import { ThemeOptions } from "@/components/theme";
import { Alert, Button, Card, Field, Input, PageHeader, Toggle } from "@/components/ui";
import { del, patch } from "@/lib/api";
import type { ConsentInfo, User } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { DevicesCard } from "./devices";

export default function AccountPage() {
  const { user, reload, logout } = useSession();
  const consent = useApi<ConsentInfo>("/api/me/face-consent");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function withdraw() {
    if (!confirm("Withdraw face-search consent? We forget which photos you matched in every event.")) return;
    consent.setData(await del<ConsentInfo>("/api/me/face-consent"));
  }

  async function deleteAccount(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (form.get("confirm") !== "DELETE") return setError('Type DELETE to confirm.');
    setBusy(true);
    setError(null);
    try {
      await del("/api/me", { password: form.get("password") });
      await reload();
      router.push("/?deleted=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deletion failed");
      setBusy(false);
    }
  }

  if (!user) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <>
      <PageHeader
        title="Your account"
        subtitle={user.email}
        actions={
          <Button variant="secondary" onClick={() => void logout()}>
            Log out
          </Button>
        }
      />
      <div className="grid max-w-2xl gap-6">
        <Card>
          <h2 className="font-medium">Appearance</h2>
          <p className="mt-1 mb-4 text-sm text-muted">Saved to your account, so your other devices follow it too.</p>
          <ThemeOptions />
        </Card>

        <DevicesCard />
        <AlertsCard user={user} onSaved={reload} />

        <Card>
          <h2 className="font-medium">Billing</h2>
          <p className="mt-1 mb-4 text-sm text-muted">Your orders, receipts and subscription.</p>
          <Link href="/account/billing" className="inline-flex rounded-lg border border-line bg-paper px-4 py-2 text-sm font-medium text-ink hover:bg-mist">
            Open billing
          </Link>
        </Card>

        <Card>
          <h2 className="font-medium">Face-search consent</h2>
          {consent.data?.given ? (
            <>
              <p className="mt-1 text-sm text-muted">
                Given on {new Date(consent.data.given_at ?? "").toLocaleDateString()}. Your selfies are never stored;
                we keep the list of photos you matched for up to {consent.data.grant_days} days.
              </p>
              <Button variant="secondary" className="mt-4" onClick={() => void withdraw()}>
                Withdraw consent
              </Button>
            </>
          ) : (
            <p className="mt-1 text-sm text-muted">Not given. You&apos;ll be asked before your first selfie search.</p>
          )}
        </Card>

        <Card className="border-alarm/30">
          <h2 className="font-medium text-alarm">Delete my data</h2>
          <p className="mt-1 text-sm text-muted">
            Permanently deletes your account, event memberships, the photos you matched, the photos you uploaded (and
            their face data) and pending invites. Search logs are kept only without your identity. This can&apos;t be
            undone. See the <Link href="/privacy" className="text-accent underline">privacy notice</Link>.
          </p>
          <form method="post" onSubmit={deleteAccount} className="mt-4 space-y-3">
            {error && <Alert>{error}</Alert>}
            <Field label="Password">
              <Input name="password" type="password" autoComplete="current-password" required />
            </Field>
            <Field label='Type "DELETE" to confirm'>
              <Input name="confirm" autoComplete="off" required />
            </Field>
            <Button type="submit" variant="danger" disabled={busy}>
              {busy ? "Deleting…" : "Delete my account and data"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}

function AlertsCard({ user, onSaved }: { user: User; onSaved: () => Promise<void> }) {
  const [state, setState] = useState<"idle" | "saved" | "error">("idle");
  const [checked, setChecked] = useState(user.new_photo_alerts);

  async function save(on: boolean) {
    setState("idle");
    setChecked(on); // the box flips at once; reverted if the save fails
    try {
      await patch("/api/me/preferences", { new_photo_alerts: on });
      await onSaved();
      setState("saved");
    } catch {
      setChecked(!on);
      setState("error");
    }
  }

  return (
    <Card>
      <h2 className="font-medium">New-photo alerts</h2>
      <p className="mt-1 mb-4 text-sm text-muted">You can also turn them off for a single event on its page.</p>
      <Toggle
        label="Tell me when new photos are added to events I searched"
        hint="By email and in the app, at most once a day per event."
        checked={checked}
        onChange={(v) => void save(v)}
      />
      {state === "saved" && <p className="mt-3 text-sm text-leaf">Saved.</p>}
      {state === "error" && <p className="mt-3 text-sm text-alarm">Couldn&apos;t save, try again.</p>}
    </Card>
  );
}
