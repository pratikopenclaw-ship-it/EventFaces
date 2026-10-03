"use client";

import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { post } from "@/lib/api";
import type { ConsentInfo } from "@/lib/types";

export function ConsentPanel({ info, onGiven }: { info: ConsentInfo; onGiven: (c: ConsentInfo) => void }) {
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      onGiven(await post<ConsentInfo>("/api/me/face-consent", { version: info.version }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save your consent");
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-2xl">
      {/* The text comes from the API: one versioned source for web and app. */}
      <h2 className="font-display text-2xl">{info.text.title}</h2>
      <p className="mt-2 text-sm text-muted">{info.text.intro}</p>
      <dl className="mt-6 space-y-4 text-sm">
        {info.text.sections.map((section) => (
          <div key={section.heading}>
            <dt className="font-medium">{section.heading}</dt>
            <dd className="space-y-1 text-muted">
              {section.paragraphs.map((p) => (
                <p key={p}>{p}</p>
              ))}
            </dd>
          </div>
        ))}
      </dl>

      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-lg bg-mist p-3 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-accent" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        <span>{info.text.agreement}</span>
      </label>
      <Button className="mt-4 w-full" disabled={!agreed || busy} onClick={() => void accept()}>
        {busy ? "Saving…" : info.text.action}
      </Button>
    </Card>
  );
}
