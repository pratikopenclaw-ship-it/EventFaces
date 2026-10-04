"use client";

import { useEffect, useState } from "react";

import { get } from "@/lib/api";

export type LegalDocumentName = "terms" | "organizer-terms" | "privacy" | "imprint";

export type LegalDocumentData = {
  document: LegalDocumentName;
  version: string;
  locale: "de" | "en";
  binding_locale: "de";
  title: string;
  intro: string;
  sections: { heading: string; paragraphs: string[] }[];
};

/** Loads a legal document (server-owned, versioned; the same text the iOS app shows). */
export function useLegalDocument(document: LegalDocumentName, lang: "de" | "en" | null) {
  const [data, setData] = useState<LegalDocumentData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<LegalDocumentData>(`/api/legal/${document}${lang ? `?lang=${lang}` : ""}`)
      .then((d) => {
        if (!live) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : "Could not load this document."));
    return () => {
      live = false;
    };
  }, [document, lang]);
  return { data, error };
}

export function LegalDocumentView({ document }: { document: LegalDocumentName }) {
  const [lang, setLang] = useState<"de" | "en" | null>(null);
  const { data, error } = useLegalDocument(document, lang);
  if (error) return <p className="text-sm text-muted">{error}</p>;
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  return <LegalText data={data} onLanguage={setLang} />;
}

export function LegalText({ data, onLanguage }: { data: LegalDocumentData; onLanguage?: (lang: "de" | "en") => void }) {
  const other = data.locale === "de" ? "en" : "de";
  return (
    <article lang={data.locale} className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="font-display text-4xl tracking-tight">{data.title}</h1>
        <p className="text-sm text-muted">
          {data.locale === "de" ? "Stand" : "Version"}: <time dateTime={data.version}>{data.version}</time>
          {data.locale !== data.binding_locale && " · The German version is binding."}
        </p>
        {onLanguage && (
          <button type="button" onClick={() => onLanguage(other)} className="text-sm text-accent underline underline-offset-2" lang={other}>
            {other === "de" ? "Deutsche Fassung (verbindlich)" : "English translation"}
          </button>
        )}
        <p className="text-sm leading-relaxed text-muted">{data.intro}</p>
      </header>
      {data.sections.map((s) => (
        <section key={s.heading} className="space-y-2">
          <h2 className="font-display text-xl">{s.heading}</h2>
          <div className="space-y-2 text-sm leading-relaxed text-muted">
            {s.paragraphs.map((p, i) => (
              <p key={i} className="whitespace-pre-line">
                {p}
              </p>
            ))}
          </div>
        </section>
      ))}
    </article>
  );
}
