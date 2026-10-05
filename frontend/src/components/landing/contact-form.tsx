"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Alert, Button, Field, Input, Select, Textarea } from "@/components/ui";
import { post } from "@/lib/api";

/** Sent by email to the operator (POST /api/contact); nothing is stored. */
export function ContactForm() {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setState("sending");
    setError(null);
    try {
      await post("/api/contact", {
        name: String(form.get("name") ?? "").trim(),
        email: String(form.get("email") ?? "").trim(),
        topic: form.get("topic"),
        message: String(form.get("message") ?? "").trim(),
        website: String(form.get("website") ?? ""),
      });
      setState("sent");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Your message couldn't be sent.");
      setState("idle");
    }
  }

  if (state === "sent") {
    return <Alert kind="success">Thanks, your message is on its way. We&apos;ll reply to the address you gave.</Alert>;
  }

  return (
    <form method="post" onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Your name">
          <Input name="name" required maxLength={100} autoComplete="name" />
        </Field>
        <Field label="Email">
          <Input name="email" type="email" required maxLength={254} autoComplete="email" />
        </Field>
      </div>
      <Field label="What is it about?">
        <Select name="topic" defaultValue="organizer">
          <option value="organizer">Organizing an event</option>
          <option value="attendee">Finding my photos</option>
          <option value="privacy">Privacy and my data</option>
          <option value="other">Something else</option>
        </Select>
      </Field>
      <Field label="Message">
        <Textarea name="message" required minLength={10} maxLength={5000} rows={5} />
      </Field>
      {/* For bots only: people never see this field. */}
      <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
        <label>
          Leave this empty
          <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={state === "sending"}>
          {state === "sending" ? "Sending…" : "Send message"}
        </Button>
        <p className="text-xs text-muted">
          We use your name and email only to answer you; the message is emailed to us and not stored on our servers. See the{" "}
          <Link href="/privacy" className="underline hover:text-ink">privacy notice</Link>.
        </p>
      </div>
    </form>
  );
}
