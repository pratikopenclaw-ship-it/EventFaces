"use client";

import { useState } from "react";

import { useSession } from "@/components/session";
import { Alert } from "@/components/ui";
import { post } from "@/lib/api";

export function VerifyBanner() {
  const { user } = useSession();
  const [sent, setSent] = useState(false);
  if (!user || user.email_verified_at) return null;

  return (
    <div className="mb-6">
      <Alert kind="info">
        Please verify your email ({user.email}) before joining events.{" "}
        {sent ? (
          "New link sent."
        ) : (
          <button
            className="font-medium text-accent hover:underline"
            onClick={() => void post("/api/auth/resend-verification", { email: user.email }).then(() => setSent(true))}
          >
            Resend link
          </button>
        )}
      </Alert>
    </div>
  );
}
