import { notFound } from "next/navigation";

import { isToken } from "@/lib/safe";

import { RemovalSubmit } from "./removal-submit";

export default async function RemovalTokenPage({ params }: PageProps<"/removal/[token]">) {
  const { token } = await params;
  if (!isToken(token)) notFound();
  return <RemovalSubmit token={token} />;
}
