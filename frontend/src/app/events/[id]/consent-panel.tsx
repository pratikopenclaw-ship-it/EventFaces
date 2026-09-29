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
      <h2 className="font-display text-2xl">Before we look for you</h2>
      <p className="mt-2 text-sm text-ink/65">
        Finding your photos uses face recognition. Face data is <strong>biometric data</strong> under the GDPR, so we
        need your explicit consent first.
      </p>

      <dl className="mt-6 space-y-4 text-sm">
        <div>
          <dt className="font-medium">What we process</dt>
          <dd className="text-ink/70">
            One selfie you take now. We turn the face in it into a numeric face template and compare it with the faces
            in <em>this event&apos;s</em> photos only.
          </dd>
        </div>
        <div>
          <dt className="font-medium">Why</dt>
          <dd className="text-ink/70">Only to show you the photos you appear in, so you can view and download them.</dd>
        </div>
        <div>
          <dt className="font-medium">What we keep and for how long</dt>
          <dd className="space-y-1 text-ink/70">
            <p>
              Your selfie and its face template are <strong>deleted immediately after matching</strong>. They are
              processed in memory and never saved.
            </p>
            <p>
              We keep the list of photos you matched for {info.grant_days} days (or until the event&apos;s access
              ends) so you can come back and download them.
            </p>
            <p>A security log records that you searched, when, and how many photos matched. It never includes your selfie.</p>
          </dd>
        </div>
        <div>
          <dt className="font-medium">Legal basis and your rights</dt>
          <dd className="text-ink/70">
            Your explicit consent (Art. 9(2)(a) GDPR). You can withdraw it at any time on this page, and we then
            delete the list of photos you matched. Withdrawal doesn&apos;t make searches you already did unlawful.
          </dd>
        </div>
      </dl>

      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <label className="mt-6 flex cursor-pointer items-start gap-3 rounded-lg bg-mist p-3 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-accent" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        <span>I consent to EventFaces processing my selfie as described above to find my photos.</span>
      </label>
      <Button className="mt-4 w-full" disabled={!agreed || busy} onClick={() => void accept()}>
        {busy ? "Saving…" : "Continue to selfie"}
      </Button>
    </Card>
  );
}
