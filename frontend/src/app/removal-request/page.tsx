import { isSlug } from "@/lib/safe";

import { RemovalRequestForm } from "./removal-form";

export default async function RemovalRequestPage({ searchParams }: PageProps<"/removal-request">) {
  const { event } = await searchParams;
  return <RemovalRequestForm initialEvent={isSlug(event) ? event : ""} />;
}
