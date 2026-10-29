"use client";

import Link from "next/link";
import { useState } from "react";

import { TestModeBanner } from "@/components/test-mode";
import { Alert, Card, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import { ADDON_NAMES, FAILURE_MESSAGES, formatMoney } from "@/lib/billing";
import type { AddonOrder, AddonTestCheckout, AddonTestPaymentResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { TestCardForm, type TestPayment } from "../../test-card-form";

const LINK = "inline-flex rounded-lg border border-line bg-paper px-4 py-2 text-sm font-medium text-ink hover:bg-mist";

function photoCount(n: number): string {
  return `${n} ${n === 1 ? "photo" : "photos"}`;
}

function BackToEvent({ order }: { order: AddonOrder }) {
  if (!order.event_id) return null; // the event was deleted since
  return (
    <Link href={`/events/${order.event_id}`} className={LINK}>
      Back to the event
    </Link>
  );
}

/** The fake provider's hosted payment page for photo add-ons (POST
 * /api/events/{id}/addons/checkout sends the buyer here). */
export function AddonCheckout({ session }: { session: string }) {
  const checkout = useApi<AddonTestCheckout>(`/api/billing/addon-checkout/${encodeURIComponent(session)}`);
  const [paid, setPaid] = useState<AddonOrder | null>(null);

  if (checkout.error) {
    return <Alert>{checkout.error.status === 404 ? "This checkout doesn't exist or isn't yours." : checkout.error.message}</Alert>;
  }
  if (!checkout.data) return <p className="text-sm text-muted">Loading…</p>;
  const { order, test_cards } = checkout.data;
  const name = ADDON_NAMES[order.kind];
  const count = order.photo_ids.length;

  if (paid) {
    return (
      <div className="mx-auto max-w-md space-y-4">
        <TestModeBanner />
        <PageHeader title="Order paid" subtitle={`${name} · ${photoCount(count)}`} />
        <Card>
          <p className="text-sm text-ink">
            {formatMoney(paid.amount_cents, paid.currency)} paid, incl. {formatMoney(paid.vat_cents, paid.currency)} VAT ({paid.vat_rate}%).
          </p>
          {/* Fulfilment (an editor's task) isn't built yet: say so rather than promise a delivery. */}
          <p className="mt-2 text-sm text-muted">This is a test order. Editing isn&apos;t offered yet, so nothing more happens with it.</p>
          <div className="mt-5">
            <BackToEvent order={paid} />
          </div>
        </Card>
      </div>
    );
  }

  if (order.status !== "pending") {
    return (
      <div className="mx-auto max-w-md space-y-4">
        <Alert kind="info">This checkout is closed ({order.status}).</Alert>
        <BackToEvent order={order} />
      </div>
    );
  }

  async function pay(payment: TestPayment): Promise<string | null> {
    const result = await post<AddonTestPaymentResult>(`/api/billing/addon-checkout/${encodeURIComponent(session)}/pay`, payment);
    if (result.order.status === "paid") {
      setPaid(result.order);
      return null;
    }
    return FAILURE_MESSAGES[result.order.failure_code ?? "payment_failed"] ?? FAILURE_MESSAGES.payment_failed;
  }

  return (
    <div className="mx-auto max-w-md">
      <TestModeBanner />
      <PageHeader title="Payment" subtitle={`${name} · ${photoCount(count)}`} />
      <Card>
        {order.event_id && (
          <ul className="theme-dark mb-4 flex flex-wrap gap-2 rounded-xl bg-canvas p-2" aria-label="Photos in this order">
            {order.photo_ids.map((id, i) => (
              <li key={id} className="size-16 overflow-hidden rounded-md bg-mist">
                {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                <img
                  src={`/api/events/${order.event_id}/photos/${id}/thumb`}
                  alt={`Photo ${i + 1} of ${count}`}
                  loading="lazy"
                  className="h-full w-full object-cover"
                />
              </li>
            ))}
          </ul>
        )}
        {count > 1 && (
          <p className="mb-2 text-sm text-muted">
            {photoCount(count)} × {formatMoney(Math.round(order.amount_cents / count), order.currency)}
          </p>
        )}
        <TestCardForm amountCents={order.amount_cents} currency={order.currency} vatRate={order.vat_rate} testCards={test_cards} onPay={pay} />
      </Card>
    </div>
  );
}
