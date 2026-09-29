import { JoinForm } from "./join-form";

export default async function JoinPage({ params, searchParams }: PageProps<"/join/[slug]">) {
  const { slug } = await params;
  const { code } = await searchParams;
  return <JoinForm slug={slug} initialCode={typeof code === "string" ? code : ""} />;
}
