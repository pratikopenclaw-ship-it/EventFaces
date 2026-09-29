"use client";

import { useRouter } from "next/navigation";

import { EventForm, initialInput } from "@/components/event-form";
import { Card, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import type { EventAdmin, EventInput } from "@/lib/types";

export default function NewEventPage() {
  const router = useRouter();

  async function create(input: EventInput) {
    const event = await post<EventAdmin>("/api/events", input);
    router.push(`/admin/events/${event.id}?tab=access`);
  }

  return (
    <>
      <PageHeader title="New event" />
      <Card>
        <EventForm initial={initialInput()} submitLabel="Create event" onSubmit={create} />
      </Card>
    </>
  );
}
