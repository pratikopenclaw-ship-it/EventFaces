"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { TestModeBanner } from "@/components/test-mode";
import { Alert, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import { FAILURE_MESSAGES, formatMoney, groupCardNumber } from "@/lib/billing";
import type { TestCheckout as Checkout, TestPaymentResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const CARD_LABELS: Record<string, string> = {
  "4242424242424242": "Payment succeeds",
  "4000000000000002": "Card is declined",
  "4000000000009995": "Insufficient funds",
};

/** The fake provider's hosted payment page. A real provider (e.g. Stripe Checkout) would
 * host this on its own domain; card details never reach our database either way. */
export function TestCheckout({ session }: { session: string }) {
  const checkout = useApi<Checkout>(`/api/billing/test-checkout/${encodeURIComponent(session)}`);
  const router = useRouter();
  const [card, setCard] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (checkout.error) {
    return <Alert>{checkout.error.status === 404 ? "This checkout doesn't exist or isn't yours." : checkout.error.message}</Alert>;
  }
  if (!checkout.data) return <p className="text-sm text-muted">Loading…</p>;
  const { order, test_cards } = checkout.data;

  if (order.status !== "pending") {
    return (
      <div className="mx-auto max-w-md space-y-4">
        <Alert kind="info">This checkout is closed ({order.status}).</Alert>
        <Button variant="secondary" onClick={() => router.push(`/account/billing/${order.id}`)}>View the order</Button>
      </div>
    );
  }

  async function pay(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const result = await post<TestPaymentResult>(`/api/billing/test-checkout/${encodeURIComponent(session)}/pay`, {
        card_number: card,
        expiry: form.get("expiry"),
        cvc: form.get("cvc"),
      });
      if (result.order.status === "paid") {
        router.push(result.order.event_id ? `/admin/events/${result.order.event_id}?welcome=1` : `/account/billing/${result.order.id}?paid=1`);
        return;
      }
      setError(FAILURE_MESSAGES[result.order.failure_code ?? "payment_failed"] ?? FAILURE_MESSAGES.payment_failed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
    }
    setBusy(false);
  }

  return (
    <div className="mx-auto max-w-md">
      <TestModeBanner />
      <PageHeader title="Payment" subtitle={`${order.plan_name}${order.event_name ? ` · ${order.event_name}` : ""}`} />
      <Card>
        <p className="mb-5 flex items-baseline justify-between">
          <span className="text-sm text-muted">Total incl. {order.vat_rate}% VAT</span>
          <span className="font-display text-3xl tracking-tight text-ink">{formatMoney(order.amount_cents, order.currency)}</span>
        </p>
        <form method="post" onSubmit={pay} className="space-y-4" autoComplete="off">
          <Field label="Card number (test cards only)">
            <Input
              name="test-card"
              inputMode="numeric"
              autoComplete="off"
              value={card}
              onChange={(e) => setCard(groupCardNumber(e.target.value).slice(0, 23))}
              placeholder="4242 4242 4242 4242"
              required
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Expiry">
              <Input name="expiry" autoComplete="off" placeholder="12/30" maxLength={7} required />
            </Field>
            <Field label="CVC">
              <Input name="cvc" inputMode="numeric" autoComplete="off" placeholder="123" pattern="[0-9]{3,4}" maxLength={4} required />
            </Field>
          </div>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Processing…" : `Pay ${formatMoney(order.amount_cents, order.currency)}`}
          </Button>
        </form>
        <div className="mt-6 border-t border-line pt-4">
          <h2 className="text-sm font-medium text-ink">Test cards</h2>
          <ul className="mt-2 space-y-1">
            {test_cards.map((number) => (
              <li key={number}>
                <button
                  type="button"
                  onClick={() => setCard(groupCardNumber(number))}
                  className="flex w-full justify-between rounded-md px-2 py-1 text-left text-sm hover:bg-mist focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <span className="font-mono text-ink">{groupCardNumber(number)}</span>
                  <span className="text-muted">{CARD_LABELS[number] ?? ""}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">Any future expiry date and any 3-digit CVC.</p>
        </div>
      </Card>
    </div>
  );
}
