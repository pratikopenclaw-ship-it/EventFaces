"use client";

import { useRouter } from "next/navigation";

import { TestModeBanner } from "@/components/test-mode";
import { Alert, Button, Card, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";
import { FAILURE_MESSAGES } from "@/lib/billing";
import type { TestCheckout as Checkout, TestPaymentResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { TestCardForm, type TestPayment } from "../../test-card-form";

/** The fake provider's hosted payment page for event purchases. */
export function TestCheckout({ session }: { session: string }) {
  const checkout = useApi<Checkout>(`/api/billing/test-checkout/${encodeURIComponent(session)}`);
  const router = useRouter();

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

  async function pay(payment: TestPayment): Promise<string | null> {
    const result = await post<TestPaymentResult>(`/api/billing/test-checkout/${encodeURIComponent(session)}/pay`, payment);
    if (result.order.status === "paid") {
      router.push(result.order.event_id ? `/admin/events/${result.order.event_id}?welcome=1` : `/account/billing/${result.order.id}?paid=1`);
      return null;
    }
    return FAILURE_MESSAGES[result.order.failure_code ?? "payment_failed"] ?? FAILURE_MESSAGES.payment_failed;
  }

  return (
    <div className="mx-auto max-w-md">
      <TestModeBanner />
      <PageHeader title="Payment" subtitle={`${order.plan_name}${order.event_name ? ` · ${order.event_name}` : ""}`} />
      <Card>
        <TestCardForm amountCents={order.amount_cents} currency={order.currency} vatRate={order.vat_rate} testCards={test_cards} onPay={pay} />
      </Card>
    </div>
  );
}
