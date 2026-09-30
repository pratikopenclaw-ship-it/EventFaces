import { joinNext } from "@/lib/links";

import { VerifyEmail } from "./verify-email";

export default async function VerifyEmailPage({ searchParams }: PageProps<"/verify-email">) {
  const { token, next } = await searchParams;
  return <VerifyEmail token={typeof token === "string" ? token : ""} joining={joinNext(next)} />;
}
