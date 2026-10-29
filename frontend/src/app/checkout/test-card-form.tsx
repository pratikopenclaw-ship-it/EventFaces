"use client";

import { useState, type FormEvent } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { formatMoney, groupCardNumber } from "@/lib/billing";

const CARD_LABELS: Record<string, string> = {
  "4242424242424242": "Payment succeeds",
  "4000000000000002": "Card is declined",
  "4000000000009995": "Insufficient funds",
};

export interface TestPayment {
  card_number: string;
  expiry: FormDataEntryValue | null;
  cvc: FormDataEntryValue | null;
}

/** The fake provider's card form, shared by the event and add-on test checkouts. A real
 * provider (e.g. Stripe Checkout) would host this on its own domain; card details never
 * reach our database either way. `onPay` resolves to an error message, or null once it
 * has moved on (the form then stays busy). */
export function TestCardForm({
  amountCents,
  currency,
  vatRate,
  testCards,
  onPay,
}: {
  amountCents: number;
  currency: string;
  vatRate: number;
  testCards: string[];
  onPay: (payment: TestPayment) => Promise<string | null>;
}) {
  const [card, setCard] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function pay(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    let message: string | null;
    try {
      message = await onPay({ card_number: card, expiry: form.get("expiry"), cvc: form.get("cvc") });
    } catch (err) {
      message = err instanceof Error ? err.message : "Payment failed";
    }
    if (message !== null) {
      setError(message);
      setBusy(false);
    }
  }

  return (
    <>
      <p className="mb-5 flex items-baseline justify-between">
        <span className="text-sm text-muted">Total incl. {vatRate}% VAT</span>
        <span className="font-display text-3xl tracking-tight text-ink">{formatMoney(amountCents, currency)}</span>
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
          {busy ? "Processing…" : `Pay ${formatMoney(amountCents, currency)}`}
        </Button>
      </form>
      <div className="mt-6 border-t border-line pt-4">
        <h2 className="text-sm font-medium text-ink">Test cards</h2>
        <ul className="mt-2 space-y-1">
          {testCards.map((number) => (
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
    </>
  );
}
