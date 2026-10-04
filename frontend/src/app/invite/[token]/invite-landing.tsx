"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { useSession } from "@/components/session";
import { TermsCheckbox } from "@/components/terms-checkbox";
import { Alert, Button, Field, Input, formatDate } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventPublic, InvitePreview } from "@/lib/types";
import { useApi } from "@/lib/use-api";

export function InviteLanding({ token }: { token: string }) {
  const { user, loading: sessionLoading, logout, reload } = useSession();
  const preview = useApi<InvitePreview>(`/api/invites/${token}`);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const event = await post<EventPublic>("/api/invites/accept", { token });
      router.push(`/events/${event.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not accept the invite");
      setBusy(false);
    }
  }

  async function register(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (form.get("password") !== form.get("confirm")) return setError("Passwords don't match");
    setBusy(true);
    setError(null);
    try {
      await post("/api/invites/register", { token, password: form.get("password"), accept_terms: form.get("accept_terms") === "on" });
      await reload(); // pick up the new session cookies
      router.push("/events");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create your account");
      setBusy(false);
    }
  }

  if (preview.loading || sessionLoading) return <AuthCard title="Opening your invite…">One moment.</AuthCard>;
  if (preview.error || !preview.data) {
    return (
      <AuthCard title="Invite unavailable">
        <Alert>{preview.error?.message ?? "This invite link is invalid or has expired."}</Alert>
        <p className="mt-4 text-sm text-muted">Ask the organizer to send you a new invite.</p>
      </AuthCard>
    );
  }

  const inv = preview.data;
  const title = `You're invited to ${inv.event_name}`;
  const subtitle = inv.event_date ? formatDate(inv.event_date) : undefined;

  // Logged in with the invited address: one click.
  if (user && user.email.toLowerCase() === inv.email.toLowerCase()) {
    return (
      <AuthCard title={title} subtitle={subtitle}>
        {error && (
          <div className="mb-4">
            <Alert>{error}</Alert>
          </div>
        )}
        <Button className="w-full" disabled={busy} onClick={() => void accept()}>
          {busy ? "Joining…" : "Join event"}
        </Button>
      </AuthCard>
    );
  }

  // Logged in as someone else.
  if (user) {
    return (
      <AuthCard title={title} subtitle={subtitle}>
        <Alert kind="info">
          This invite is for <strong>{inv.email}</strong>, but you&apos;re logged in as {user.email}.
        </Alert>
        <Button variant="secondary" className="mt-4 w-full" onClick={() => void logout()}>
          Log out and switch account
        </Button>
      </AuthCard>
    );
  }

  // Has an account: log in, then come back here.
  if (inv.account_exists) {
    return (
      <AuthCard title={title} subtitle={subtitle}>
        <p className="text-sm text-muted">
          Log in as <strong>{inv.email}</strong> to accept.
        </p>
        <Link
          href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}
          className="mt-4 flex w-full justify-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-on-accent hover:bg-accent-hover"
        >
          Log in
        </Link>
      </AuthCard>
    );
  }

  // New here: set a password; the link already proves the email address.
  return (
    <AuthCard title={title} subtitle={subtitle}>
      <form method="post" onSubmit={register} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <p className="text-sm text-muted">
          Create your account for <strong>{inv.email}</strong>. No separate email confirmation needed.
        </p>
        <Field label="Password" hint="At least 10 characters.">
          <Input name="password" type="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <Field label="Confirm password">
          <Input name="confirm" type="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <TermsCheckbox />
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating account…" : "Create account and join"}
        </Button>
      </form>
    </AuthCard>
  );
}
