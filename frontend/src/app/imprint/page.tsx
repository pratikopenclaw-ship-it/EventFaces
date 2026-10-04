import { LegalDocumentView } from "@/components/legal-document";

export const metadata = { title: "Legal notice (Impressum) · EventFaces" };

// Server-owned and versioned (backend services/legal.py): the iOS app shows the same text.
export default function Page() {
  return <LegalDocumentView document="imprint" />;
}
