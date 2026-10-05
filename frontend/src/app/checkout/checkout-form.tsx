"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { TestModeBanner } from "@/components/test-mode";
import { Alert, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import { formatMoney } from "@/lib/billing";
import type { PlanKey, PriceList } from "@/lib/types";
import { useApi } from "@/lib/use-api";

/** Step 1: which event (name, date) and a summary; then the provider's checkout. */
export function CheckoutForm({ planKey }: { planKey: PlanKey }) {
  const prices = useApi<PriceList>("/api/billing/plans");
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const plan = prices.data?.plans.find((p) => p.key === planKey);
  if (prices.error) return <Alert>Prices couldn&apos;t be loaded. Please try again later.</Alert>;
  if (!prices.data || !plan) return <p className="text-sm text-muted">Loading…</p>;
  const subscription = plan.kind === "subscription";
  const currency = prices.data.currency;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const name = String(form.get("event_name") ?? "").trim();
    const date = String(form.get("event_date") ?? "");
    setBusy(true);
    setError(null);
    try {
      const { checkout_url } = await post<{ order_id: string; checkout_url: string }>("/api/billing/checkout", {
        plan: planKey,
        event_name: name || null,
        event_date: date || null,
      });
      router.push(checkout_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checkout failed");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      {prices.data.test_mode && <TestModeBanner />}
      <PageHeader title={subscription ? `Subscribe to ${plan.name}` : `Buy ${plan.name}`} subtitle={<Link href="/pricing" className="underline hover:text-ink">Change plan</Link>} />
      <Card>
        <form method="post" onSubmit={submit} className="space-y-5">
          <Field label={subscription ? "Your first event (optional)" : "Event name"} hint={subscription ? `Your plan includes ${plan.events_per_period} events a month. You can add them any time.` : undefined}>
            <Input name="event_name" required={!subscription} maxLength={200} placeholder="e.g. Anna & Ben's wedding" />
          </Field>
          <Field label="Event date (optional)">
            <Input name="event_date" type="date" />
          </Field>
          <dl className="space-y-1 rounded-lg bg-mist px-4 py-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted">{plan.name}{subscription ? " (monthly)" : ""}</dt>
              <dd className="font-medium text-ink">{formatMoney(plan.price_cents, currency)}</dd>
            </div>
            <div className="flex justify-between text-xs text-muted">
              <dt>Includes {prices.data.vat_rate}% VAT</dt>
              <dd>
                {formatMoney(Math.round((plan.price_cents * prices.data.vat_rate) / (100 + prices.data.vat_rate)), currency)}
              </dd>
            </div>
          </dl>
          <p className="-mt-3 px-4 text-xs text-muted">
            Up to {plan.max_attendees.toLocaleString()} attendees and {plan.max_photos.toLocaleString()} photos per event.
          </p>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Starting checkout…" : "Continue to payment"}
          </Button>
          <p className="text-xs text-muted">
            By continuing you order a paid service under our{" "}
            <Link href="/organizer-terms" className="underline hover:text-ink">Organizer Terms</Link>. You&apos;ll accept them before
            managing your event.
          </p>
        </form>
      </Card>
    </div>
  );
}
