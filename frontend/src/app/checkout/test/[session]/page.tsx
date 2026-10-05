import { TestCheckout } from "./test-checkout";

export default async function TestCheckoutPage({ params }: PageProps<"/checkout/test/[session]">) {
  const { session } = await params;
  return <TestCheckout session={session} />;
}
