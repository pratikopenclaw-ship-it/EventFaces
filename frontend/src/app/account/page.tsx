"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useSession } from "@/components/session";
import { Alert, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { del } from "@/lib/api";
import type { ConsentInfo } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export default function AccountPage() {
  const { user, reload } = useSession();
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

  if (!user) return <p className="text-sm text-ink/50">Loading…</p>;

  return (
    <>
      <PageHeader title="Your account" subtitle={user.email} />
      <div className="grid max-w-2xl gap-6">
        <Card>
          <h2 className="font-medium">Face-search consent</h2>
          {consent.data?.given ? (
            <>
              <p className="mt-1 text-sm text-ink/65">
                Given on {new Date(consent.data.given_at ?? "").toLocaleDateString()}. Your selfies are never stored;
                we keep the list of photos you matched for up to {consent.data.grant_days} days.
              </p>
              <Button variant="secondary" className="mt-4" onClick={() => void withdraw()}>
                Withdraw consent
              </Button>
            </>
          ) : (
            <p className="mt-1 text-sm text-ink/65">Not given. You&apos;ll be asked before your first selfie search.</p>
          )}
        </Card>

        <Card className="border-alarm/30">
          <h2 className="font-medium text-alarm">Delete my data</h2>
          <p className="mt-1 text-sm text-ink/65">
            Permanently deletes your account, event memberships, the photos you matched, the photos you uploaded (and
            their face data) and pending invites. Search logs are kept only without your identity. This can&apos;t be
            undone. See the <Link href="/privacy" className="text-accent hover:underline">privacy notice</Link>.
          </p>
          <form onSubmit={deleteAccount} className="mt-4 space-y-3">
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
