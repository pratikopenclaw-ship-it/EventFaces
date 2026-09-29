import { InviteLanding } from "./invite-landing";

export default async function InvitePage({ params }: PageProps<"/invite/[token]">) {
  const { token } = await params;
  return <InviteLanding token={token} />;
}
