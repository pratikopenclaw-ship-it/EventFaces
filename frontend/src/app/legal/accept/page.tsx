import { AcceptLegal } from "./accept-legal";

export const metadata = { title: "Accept terms · EventFaces" };

export default async function Page({ searchParams }: { searchParams: Promise<{ doc?: string; next?: string }> }) {
  const { doc, next } = await searchParams;
  return <AcceptLegal document={doc === "organizer-terms" ? "organizer-terms" : "terms"} next={next ?? null} />;
}
