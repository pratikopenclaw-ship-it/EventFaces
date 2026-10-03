import type { Metadata } from "next";

import { Card, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Sign in with the app · EventFaces", robots: { index: false, follow: false } };

// Where a sign-in link lands when it opens in a browser instead of the app (another
// device, or the app isn't installed). It never uses the link's token: loading this page
// (or a mail scanner prefetching it) can't spend it.
export default function MobileSignInPage() {
  return (
    <div className="mx-auto max-w-lg">
      <PageHeader title="Open this link in the app" />
      <Card>
        <div className="space-y-3 text-sm text-muted">
          <p>This sign-in link is for the EventFaces app on your phone.</p>
          <p>
            Open the email on the phone where you use the app and tap the link there, or type the 6-digit code from the
            same email into the app.
          </p>
          <p>On a computer? Log in on the website with your email and password instead.</p>
        </div>
      </Card>
    </div>
  );
}
