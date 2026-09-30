"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { post } from "@/lib/api";

export function LoginForm({ next, joining }: { next: string; joining: string | null }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await post("/api/auth/login", { email: form.get("email"), password: form.get("password") });
      window.location.href = next; // full reload so the session provider picks up the cookies
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title={joining ? "Log in to join the event" : "Welcome back"}
      subtitle={
        <>
          {joining ? "New to EventFaces? " : "New here? "}
          <Link
            className="text-accent underline underline-offset-2"
            href={joining ? `/signup?next=${encodeURIComponent(joining)}` : "/signup"}
          >
            Create an account
          </Link>
          {joining && " and we'll bring you back to the event after you confirm your email."}
        </>
      }
    >
      <form method="post" onSubmit={onSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Email">
          <Input name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Password">
          <Input name="password" type="password" autoComplete="current-password" required />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Logging in…" : "Log in"}
        </Button>
        <Link href="/forgot-password" className="block text-center text-sm text-ink/70 hover:text-ink">
          Forgot password?
        </Link>
      </form>
    </AuthCard>
  );
}
