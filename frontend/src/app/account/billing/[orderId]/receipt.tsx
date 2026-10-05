"use client";

import Link from "next/link";

import { Alert, Button, Card, PageHeader, formatDate } from "@/components/ui";
import { formatMoney } from "@/lib/billing";
import type { Order, PriceList } from "@/lib/types";
import { useApi } from "@/lib/use-api";

/** A plain payment receipt. Not a tax invoice: invoices come with the real payment provider. */
export function Receipt({ orderId, justPaid }: { orderId: string; justPaid: boolean }) {
  const order = useApi<Order>(`/api/billing/orders/${encodeURIComponent(orderId)}`);
  const prices = useApi<PriceList>("/api/billing/plans");

  if (order.error) return <Alert>{order.error.status === 404 ? "Order not found." : order.error.message}</Alert>;
  if (!order.data) return <p className="text-sm text-muted">Loading…</p>;
  const o = order.data;
  const net = o.amount_cents - o.vat_cents;

  return (
    <div className="mx-auto max-w-xl">
      {justPaid && (
        <div className="mb-4">
          <Alert kind="success">Payment received. Thank you!</Alert>
        </div>
      )}
      <PageHeader
        title="Receipt"
        subtitle={<Link href="/account/billing" className="underline hover:text-ink print:hidden">All orders</Link>}
        actions={<Button variant="secondary" className="print:hidden" onClick={() => window.print()}>Print</Button>}
      />
      <Card>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">Order</dt>
          <dd className="font-mono text-xs text-ink break-all">{o.id}</dd>
          <dt className="text-muted">Date</dt>
          <dd className="text-ink">{formatDate(o.paid_at ?? o.created_at)}</dd>
          <dt className="text-muted">Item</dt>
          <dd className="text-ink">
            {o.plan_name}
            {o.event_name && ` · ${o.event_name}`}
          </dd>
          <dt className="text-muted">Status</dt>
          <dd className="text-ink">{o.status}</dd>
        </dl>
        <dl className="mt-6 space-y-1 border-t border-line pt-4 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted">Net</dt>
            <dd className="text-ink">{formatMoney(net, o.currency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">VAT {o.vat_rate}%</dt>
            <dd className="text-ink">{formatMoney(o.vat_cents, o.currency)}</dd>
          </div>
          <div className="flex justify-between text-base font-semibold">
            <dt className="text-ink">Total</dt>
            <dd className="text-ink">{formatMoney(o.amount_cents, o.currency)}</dd>
          </div>
        </dl>
        {o.event_id && (
          <Link href={`/admin/events/${o.event_id}`} className="mt-6 inline-block text-sm underline hover:text-ink print:hidden">
            Manage this event
          </Link>
        )}
        <p className="mt-6 text-xs text-muted">
          {prices.data?.test_mode ? "TEST MODE: no money was charged. " : ""}This receipt is not a tax invoice.
        </p>
      </Card>
    </div>
  );
}
