"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { TestModeBanner } from "@/components/test-mode";
import { Alert, Badge, Button, Card, Field, Input, PageHeader, formatDate } from "@/components/ui";
import { post } from "@/lib/api";
import { formatMoney } from "@/lib/billing";
import type { BillingOverview, Order, PriceList, Subscription } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const STATUS_TONE = { paid: "good", pending: "warn", canceled: "neutral" } as const;
const KIND_LABEL = { one_off: "Event plan", subscription: "Subscription", allowance: "Included in subscription" } as const;

export default function BillingPage() {
  const overview = useApi<BillingOverview>("/api/billing/overview");
  const prices = useApi<PriceList>("/api/billing/plans");

  if (overview.error) return <Alert>{overview.error.message}</Alert>;
  if (!overview.data) return <p className="text-sm text-muted">Loading…</p>;
  const { subscription, orders } = overview.data;

  return (
    <>
      {prices.data?.test_mode && <TestModeBanner />}
      <PageHeader
        title="Billing"
        subtitle={<Link href="/account" className="underline hover:text-ink">Back to your account</Link>}
        actions={<Link href="/pricing" className="rounded-lg border border-line bg-paper px-4 py-2 text-sm font-medium text-ink hover:bg-mist">Buy an event</Link>}
      />
      <div className="space-y-6">
        {subscription && <SubscriptionCard sub={subscription} onChange={overview.reload} />}
        <Card>
          <h2 className="mb-4 text-lg font-semibold text-ink">Orders</h2>
          {orders.length === 0 ? (
            <p className="text-sm text-muted">No orders yet. <Link href="/pricing" className="underline hover:text-ink">See plans</Link>.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Date</th>
                    <th className="py-2 pr-4 font-medium">What</th>
                    <th className="py-2 pr-4 font-medium">Amount</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 font-medium"><span className="sr-only">Receipt</span></th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <OrderRow key={o.id} order={o} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function OrderRow({ order }: { order: Order }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2 pr-4 whitespace-nowrap text-ink">{formatDate(order.created_at)}</td>
      <td className="py-2 pr-4 text-ink">
        {order.plan_name} <span className="text-muted">· {KIND_LABEL[order.kind]}</span>
        {order.event_name && <span className="block text-xs text-muted">{order.event_name}</span>}
      </td>
      <td className="py-2 pr-4 whitespace-nowrap text-ink">{formatMoney(order.amount_cents, order.currency)}</td>
      <td className="py-2 pr-4"><Badge tone={STATUS_TONE[order.status]}>{order.status}</Badge></td>
      <td className="py-2 text-right">
        {order.status === "paid" ? (
          <Link href={`/account/billing/${order.id}`} className="text-sm underline hover:text-ink">Receipt</Link>
        ) : null}
      </td>
    </tr>
  );
}

function SubscriptionCard({ sub, onChange }: { sub: Subscription; onChange: () => Promise<void> }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const left = Math.max(0, sub.events_included - sub.events_used);

  async function newEvent(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const { event_id } = await post<{ event_id: string }>("/api/billing/subscription/events", {
        name: String(form.get("name")).trim(),
        date: form.get("date") || null,
      });
      router.push(`/admin/events/${event_id}?welcome=1`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the event");
      setBusy(false);
    }
  }

  async function cancel() {
    if (!confirm(`Cancel ${sub.plan_name}? It stays active until ${formatDate(sub.current_period_end)}, then ends.`)) return;
    try {
      await post("/api/billing/subscription/cancel");
      await onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't cancel");
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-ink">{sub.plan_name} subscription</h2>
          <p className="mt-1 text-sm text-muted">
            {sub.canceled_at ? `Canceled: ends on ${formatDate(sub.current_period_end)}` : `Renews on ${formatDate(sub.current_period_end)}`} ·{" "}
            {sub.events_used} of {sub.events_included} events used this period
          </p>
        </div>
        {!sub.canceled_at && (
          <Button variant="secondary" onClick={() => void cancel()}>Cancel subscription</Button>
        )}
      </div>
      {left > 0 ? (
        <form method="post" onSubmit={newEvent} className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
          <Field label="New event">
            <Input name="name" required maxLength={200} placeholder="Event name" />
          </Field>
          <Field label="Date (optional)">
            <Input name="date" type="date" />
          </Field>
          <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create event"}</Button>
        </form>
      ) : (
        <p className="mt-4 text-sm text-muted">This period&apos;s events are used up. New ones are available from {formatDate(sub.current_period_end)}.</p>
      )}
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
    </Card>
  );
}
