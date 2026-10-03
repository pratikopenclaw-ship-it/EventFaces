"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AuthCard } from "@/components/auth-card";
import { useSession } from "@/components/session";
import { Alert, Button, Field, Input } from "@/components/ui";
import { post } from "@/lib/api";

type State = "verifying" | "ok" | "failed";

export function VerifyEmail({ token, joining }: { token: string; joining: string | null }) {
  const [state, setState] = useState<State>(token ? "verifying" : "failed");
  const [error, setError] = useState<string>(token ? "" : "This link is missing its token.");
  const [resent, setResent] = useState(false);
  const { reload } = useSession();
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return; // tokens are single-use; don't double-submit in dev StrictMode
    started.current = true;
    post("/api/auth/verify-email", { token })
      .then(() => {
        setState("ok");
        void reload();
      })
      .catch((e: Error) => {
        setState("failed");
        setError(e.message);
      });
  }, [token, reload]);

  async function resend(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await post("/api/auth/resend-verification", { email: new FormData(e.currentTarget).get("email") });
    setResent(true);
  }

  if (state === "verifying") return <AuthCard title="Verifying…">One moment.</AuthCard>;
  if (state === "ok") {
    return (
      <AuthCard title="Email verified">
        <p className="mb-4 text-sm text-muted">{joining ? "Log in to finish joining the event." : "You can now join events."}</p>
        <Link href={joining ?? "/events"} className="text-accent hover:underline">
          {joining ? "Continue to the event →" : "Continue →"}
        </Link>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Link didn't work">
      <div className="space-y-4">
        <Alert>{error}</Alert>
        {resent ? (
          <Alert kind="success">If the address needs verifying, a new link is on its way.</Alert>
        ) : (
          <form method="post" onSubmit={resend} className="space-y-3">
            <Field label="Send a new link to">
              <Input name="email" type="email" required />
            </Field>
            <Button type="submit" variant="secondary" className="w-full">
              Resend verification email
            </Button>
          </form>
        )}
      </div>
    </AuthCard>
  );
}
