import { UnsubscribeForm } from "./unsubscribe-form";

// The link in new-photo alert emails. Opening it changes nothing (mail scanners follow
// links); only a button press does, and it works without logging in.
export default async function UnsubscribePage({ searchParams }: PageProps<"/unsubscribe">) {
  const { token } = await searchParams;
  return <UnsubscribeForm token={typeof token === "string" ? token : ""} />;
}
