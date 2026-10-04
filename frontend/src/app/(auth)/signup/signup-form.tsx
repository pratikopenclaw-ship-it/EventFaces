"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { TermsCheckbox } from "@/components/terms-checkbox";
import { post } from "@/lib/api";

export function SignupForm({ joining }: { joining: string | null }) {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (form.get("password") !== form.get("confirm")) {
      setError("Passwords don't match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post("/api/auth/signup", {
        email: form.get("email"),
        password: form.get("password"),
        accept_terms: form.get("accept_terms") === "on",
        ...(joining ? { next: joining } : {}),
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-up failed");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <AuthCard title="Check your inbox">
        <p className="text-sm text-muted">
          We sent a verification link to your email. Open it to activate your account
          {joining ? ", and it will bring you back to the event." : ", then "}
          {!joining && (
            <>
              <Link href="/login" className="text-accent hover:underline">
                log in
              </Link>
              .
            </>
          )}
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={joining ? "Create an account to join the event" : "Create your account"}
      subtitle={
        <>
          Already registered?{" "}
          <Link className="text-accent underline underline-offset-2" href={joining ? `/login?next=${encodeURIComponent(joining)}` : "/login"}>
            Log in
          </Link>
        </>
      }
    >
      <form method="post" onSubmit={onSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Email">
          <Input name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Password" hint="At least 10 characters.">
          <Input name="password" type="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <Field label="Confirm password">
          <Input name="confirm" type="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <TermsCheckbox />
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating…" : "Create account"}
        </Button>
      </form>
    </AuthCard>
  );
}
