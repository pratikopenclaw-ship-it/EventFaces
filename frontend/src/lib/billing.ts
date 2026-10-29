import type { AddonKind } from "./types";

// Prices arrive in minor units (cents), gross incl. VAT.

export function formatMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(cents / 100);
}

/** "4242424242424242" → "4242 4242 4242 4242" */
export function groupCardNumber(digits: string): string {
  return digits.replace(/\D/g, "").replace(/(\d{4})(?=\d)/g, "$1 ").trim();
}

export const FAILURE_MESSAGES: Record<string, string> = {
  card_declined: "The card was declined. Try another test card.",
  insufficient_funds: "The card has insufficient funds. Try another test card.",
  payment_failed: "The payment didn't go through. Please try again.",
};

export const ADDON_NAMES: Record<AddonKind, string> = {
  human_edit: "Professional photo edit",
};
