"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

interface EventBranding {
  eventId: string;
}

const BrandingContext = createContext<{
  branding: EventBranding | null;
  setBranding: (b: EventBranding | null) => void;
} | null>(null);

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<EventBranding | null>(null);
  return <BrandingContext.Provider value={{ branding, setBranding }}>{children}</BrandingContext.Provider>;
}

export function useBranding(): EventBranding | null {
  const ctx = useContext(BrandingContext);
  if (!ctx) throw new Error("useBranding must be used inside BrandingProvider");
  return ctx.branding;
}

/** Call from an event's own page while it has a logo; clears itself on unmount so leaving
 * the page restores the default EventFaces header. */
export function useSetEventBranding(event: { id: string; has_logo: boolean } | null): void {
  const ctx = useContext(BrandingContext);
  if (!ctx) throw new Error("useSetEventBranding must be used inside BrandingProvider");
  const { setBranding } = ctx;
  const eventId = event?.has_logo ? event.id : null;
  useEffect(() => {
    setBranding(eventId ? { eventId } : null);
    return () => setBranding(null);
  }, [eventId, setBranding]);
}
