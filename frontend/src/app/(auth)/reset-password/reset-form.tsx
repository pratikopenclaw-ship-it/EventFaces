"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { post } from "@/lib/api";

export function ResetPasswordForm({ token }: { token: string }) {
  const [error, setError] = useState<string | null>(token ? null : "This link is missing its token.");
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (form.get("password") !== form.get("confirm")) {
      setError("Passwords don't match");
      return;
    }
    try {
      await post("/api/auth/reset-password", { token, password: form.get("password") });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  return (
    <AuthCard title="Choose a new password">
      {done ? (
        <p className="text-sm">
          Password updated. All other sessions were signed out.{" "}
          <Link href="/login" className="text-accent hover:underline">
            Log in
          </Link>
        </p>
      ) : (
        <form method="post" onSubmit={onSubmit} className="space-y-4">
          {error && <Alert>{error}</Alert>}
          <Field label="New password" hint="At least 10 characters.">
            <Input name="password" type="password" autoComplete="new-password" minLength={10} required />
          </Field>
          <Field label="Confirm password">
            <Input name="confirm" type="password" autoComplete="new-password" minLength={10} required />
          </Field>
          <Button type="submit" disabled={!token} className="w-full">
            Update password
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
