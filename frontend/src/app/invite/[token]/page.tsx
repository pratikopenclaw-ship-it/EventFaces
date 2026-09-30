import { notFound } from "next/navigation";

import { isToken } from "@/lib/safe";

import { InviteLanding } from "./invite-landing";

export default async function InvitePage({ params }: PageProps<"/invite/[token]">) {
  const { token } = await params;
  if (!isToken(token)) notFound();
  return <InviteLanding token={token} />;
}
