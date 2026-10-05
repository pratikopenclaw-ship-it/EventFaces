import { Receipt } from "./receipt";

export default async function ReceiptPage({ params, searchParams }: PageProps<"/account/billing/[orderId]">) {
  const { orderId } = await params;
  const { paid } = await searchParams;
  return <Receipt orderId={orderId} justPaid={paid === "1"} />;
}
