import type { Metadata } from "next";

import { Pricing } from "@/components/pricing";

export const metadata: Metadata = {
  title: "Pricing · EventFaces",
  description: "Per-event plans and a monthly subscription for organizers. Attendees never pay.",
};

export default function PricingPage() {
  return (
    <div className="py-4">
      <Pricing />
    </div>
  );
}
