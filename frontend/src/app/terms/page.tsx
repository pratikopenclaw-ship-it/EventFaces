import type { Metadata } from "next";

import { Card, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Terms · EventFaces" };

// PLACEHOLDER: the operator must replace this with their own terms of use before launch
// (tracked in DEPLOYMENT.md's go/no-go checklist). The app links here.
export default function TermsPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Terms of use" subtitle="Draft. The operator will publish the final terms here before launch." />
      <Card>
        <div className="space-y-3 text-sm text-muted">
          <p>
            EventFaces helps people who were at an event find the photos they appear in. You can use it only for events
            you were invited to, and only to find photos of yourself.
          </p>
          <p>
            How we process your data, including face data, is explained in the <a href="/privacy" className="text-accent underline">privacy notice</a>.
          </p>
        </div>
      </Card>
    </div>
  );
}
