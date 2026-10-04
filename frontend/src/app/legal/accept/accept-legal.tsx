"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { LegalText, useLegalDocument, type LegalDocumentName } from "@/components/legal-document";
import { Alert, Button, Card } from "@/components/ui";
import { post } from "@/lib/api";
import { safeNext } from "@/lib/links";

/** Shown when the API answers 403 + X-Required-Action: the current Terms of Use (or the
 * Organizer Terms with the data processing agreement) haven't been accepted yet. */
export function AcceptLegal({ document, next }: { document: Extract<LegalDocumentName, "terms" | "organizer-terms">; next: string | null }) {
  const router = useRouter();
  const [lang, setLang] = useState<"de" | "en" | null>(null);
  const { data, error } = useLegalDocument(document, lang);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function accept() {
    if (!data) return;
    setBusy(true);
    setFailure(null);
    try {
      // The version the user was shown: if it changed meanwhile, the API refuses (409).
      await post("/api/me/legal/accept", { document, version: data.version });
      router.replace(safeNext(next ?? undefined));
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "Could not save your acceptance.");
      setBusy(false);
    }
  }

  const organizer = document === "organizer-terms";
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <h1 className="font-display text-2xl">{organizer ? "Organizer terms" : "Updated terms"}</h1>
        <p className="mt-2 text-sm text-muted">
          {organizer
            ? "To manage events, please read and accept the Organizer Terms, including the data processing agreement (Art. 28 GDPR)."
            : "Please read and accept the current Terms of Use to continue. You can still manage or delete your account without accepting."}
        </p>
      </Card>
      {error && <Alert>{error}</Alert>}
      {data && <LegalText data={data} onLanguage={setLang} />}
      {data && (
        <Card>
          {failure && (
            <div className="mb-4">
              <Alert>{failure}</Alert>
            </div>
          )}
          <label className="flex cursor-pointer items-start gap-3 rounded-lg bg-mist p-3 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-accent" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
            <span>
              {organizer
                ? "I accept the Organizer Terms and the data processing agreement on behalf of the organizer."
                : "I accept the Terms of Use and confirm that I am at least 16 years old."}
            </span>
          </label>
          <Button className="mt-4 w-full" disabled={!agreed || busy} onClick={() => void accept()}>
            {busy ? "Saving…" : "Accept and continue"}
          </Button>
        </Card>
      )}
    </div>
  );
}
