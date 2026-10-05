import { CheckoutForm } from "./checkout-form";

const PLAN_KEYS = ["event_s", "event_m", "event_l", "pro"] as const;

export default async function CheckoutPage({ searchParams }: PageProps<"/checkout">) {
  const { plan } = await searchParams;
  const key = PLAN_KEYS.find((k) => k === plan) ?? "event_m";
  return <CheckoutForm planKey={key} />;
}
