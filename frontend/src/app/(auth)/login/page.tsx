import { safeNext } from "@/components/auth-card";
import { joinNext } from "@/lib/links";

import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next } = await searchParams;
  return <LoginForm next={safeNext(next)} joining={joinNext(next)} />;
}
