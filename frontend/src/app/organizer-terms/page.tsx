import { LegalDocumentView } from "@/components/legal-document";

export const metadata = { title: "Organizer Terms · EventFaces" };

// Server-owned and versioned (backend services/legal.py): the iOS app shows the same text.
export default function Page() {
  return <LegalDocumentView document="organizer-terms" />;
}
