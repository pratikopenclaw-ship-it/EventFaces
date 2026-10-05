"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui";
import { formatMoney } from "@/lib/billing";
import type { Plan, PriceList } from "@/lib/types";
import { useApi } from "@/lib/use-api";

type Mode = "one_off" | "subscription";

/** Plan cards from the API's price list (one source for the page, checkout and limits). */
export function Pricing({ heading = true }: { heading?: boolean }) {
  const prices = useApi<PriceList>("/api/billing/plans");
  const [mode, setMode] = useState<Mode>("one_off");

  if (prices.error) return <Alert>Prices couldn&apos;t be loaded. Please try again later.</Alert>;
  if (!prices.data) return <p className="text-sm text-muted">Loading prices…</p>;
  const list = prices.data;
  const plans = list.plans.filter((p) => p.kind === mode);

  return (
    <section aria-labelledby={heading ? "pricing-heading" : undefined} className="space-y-6">
      {heading && (
        <div className="text-center">
          <h2 id="pricing-heading" className="font-display text-3xl tracking-tight text-ink">
            Simple pricing
          </h2>
          <p className="mt-2 text-sm text-muted">Pay per event, or subscribe if you run events every month. Attendees never pay.</p>
        </div>
      )}
      <div role="radiogroup" aria-label="Billing" className="mx-auto flex w-fit rounded-full border border-line bg-paper p-1">
        {(["one_off", "subscription"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            onClick={() => setMode(m)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              mode === m ? "bg-accent text-on-accent" : "text-muted hover:text-ink"
            }`}
          >
            {m === "one_off" ? "Per event" : "Monthly"}
          </button>
        ))}
      </div>
      <ul className={`grid gap-4 ${plans.length > 1 ? "md:grid-cols-3" : "mx-auto max-w-sm"}`}>
        {plans.map((plan) => (
          <PlanCard key={plan.key} plan={plan} currency={list.currency} featured={plan.key === "event_m"} />
        ))}
      </ul>
      <p className="text-center text-xs text-muted">
        All prices incl. {list.vat_rate}% VAT.
        {list.example_prices && " Example prices for the test phase."}
        {list.test_mode && " Test mode: no real payments are taken."}
      </p>
    </section>
  );
}

function PlanCard({ plan, currency, featured }: { plan: Plan; currency: string; featured: boolean }) {
  const monthly = plan.kind === "subscription";
  return (
    <li className={`flex flex-col rounded-2xl border bg-paper p-6 ${featured ? "border-accent shadow-sm" : "border-line"}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-ink">{plan.name}</h3>
        {featured && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-ink">Most popular</span>}
      </div>
      <p className="mt-3">
        <span className="font-display text-4xl tracking-tight text-ink">{formatMoney(plan.price_cents, currency)}</span>
        <span className="ml-1 text-sm text-muted">{monthly ? "/ month" : "/ event"}</span>
      </p>
      <ul className="mt-5 flex-1 space-y-2 text-sm text-ink/80">
        {monthly && <li>{plan.events_per_period} events every month</li>}
        <li>Up to {plan.max_attendees.toLocaleString()} attendees{monthly ? " per event" : ""}</li>
        <li>Up to {plan.max_photos.toLocaleString()} photos{monthly ? " per event" : ""}</li>
        <li>Selfie search, downloads and guest uploads</li>
        {monthly && <li>Cancel any time</li>}
      </ul>
      <Link
        href={`/checkout?plan=${plan.key}`}
        className={`mt-6 inline-flex justify-center rounded-lg px-4 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          featured ? "bg-accent text-on-accent hover:bg-accent-hover" : "border border-line bg-paper text-ink hover:bg-mist"
        }`}
      >
        {monthly ? "Subscribe" : `Choose ${plan.name}`}
      </Link>
    </li>
  );
}
