import { notFound } from "next/navigation";

import { isSlug } from "@/lib/safe";

import { JoinForm } from "./join-form";

export default async function JoinPage({ params, searchParams }: PageProps<"/join/[slug]">) {
  const { slug } = await params;
  if (!isSlug(slug)) notFound();
  const { code } = await searchParams;
  return <JoinForm slug={slug} initialCode={typeof code === "string" ? code : ""} />;
}
