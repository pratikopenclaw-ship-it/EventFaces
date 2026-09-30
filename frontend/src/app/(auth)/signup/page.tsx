import { joinNext } from "@/lib/links";

import { SignupForm } from "./signup-form";

export default async function SignupPage({ searchParams }: PageProps<"/signup">) {
  const { next } = await searchParams;
  return <SignupForm joining={joinNext(next)} />;
}
