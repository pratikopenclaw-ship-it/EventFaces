import { notFound } from "next/navigation";

import { isUuid } from "@/lib/safe";

import { EventAdminView, type Tab } from "./event-admin";

const TABS: Tab[] = ["settings", "access", "members", "photos", "shared", "videos", "moderation", "quality"];

export default async function AdminEventPage({ params, searchParams }: PageProps<"/admin/events/[id]">) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  const { tab } = await searchParams;
  const initialTab = TABS.find((t) => t === tab) ?? "settings";
  return <EventAdminView id={id} initialTab={initialTab} />;
}
