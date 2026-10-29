import { AddonCheckout } from "./addon-checkout";

export default async function AddonCheckoutPage({ params }: PageProps<"/checkout/addon/[session]">) {
  const { session } = await params;
  return <AddonCheckout session={session} />;
}
