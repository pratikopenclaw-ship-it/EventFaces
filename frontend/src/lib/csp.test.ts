import { describe, expect, it } from "vitest";

import { buildCsp, newNonce } from "./csp";

describe("CSP", () => {
  const prod = buildCsp("abc123", { dev: false, storageOrigin: "https://storage.example" });

  it("allows only nonce-tagged scripts in production", () => {
    const script = prod.split("; ").find((d) => d.startsWith("script-src"))!;
    expect(script).toContain("'nonce-abc123'");
    expect(script).not.toContain("'unsafe-inline'");
    expect(script).not.toContain("'unsafe-eval'");
  });

  it("locks down framing, objects, base and form targets", () => {
    for (const d of ["frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "default-src 'self'"]) {
      expect(prod).toContain(d);
    }
    expect(prod).not.toMatch(/(^|[ ;])\*($|[ ;])/); // no wildcard sources
    expect(prod).toContain("connect-src 'self' https://storage.example");
  });

  it("nonces are random and 128-bit", () => {
    const a = newNonce(), b = newNonce();
    expect(a).not.toBe(b);
    expect(atob(a)).toHaveLength(16);
  });
});
