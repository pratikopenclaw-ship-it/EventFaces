import { describe, expect, it } from "vitest";

import { FAILURE_MESSAGES, formatMoney, groupCardNumber } from "@/lib/billing";

describe("billing helpers", () => {
  it("formats cents as money", () => {
    expect(formatMoney(4900, "EUR")).toMatch(/49[.,]00/);
    expect(formatMoney(0, "EUR")).toMatch(/0[.,]00/);
  });

  it("groups card digits and drops everything else", () => {
    expect(groupCardNumber("4242424242424242")).toBe("4242 4242 4242 4242");
    expect(groupCardNumber("4242-4242 42x42")).toBe("4242 4242 4242");
    expect(groupCardNumber("")).toBe("");
  });

  it("explains every failure code the API sends", () => {
    for (const code of ["card_declined", "insufficient_funds", "payment_failed"]) expect(FAILURE_MESSAGES[code]).toBeTruthy();
  });
});
