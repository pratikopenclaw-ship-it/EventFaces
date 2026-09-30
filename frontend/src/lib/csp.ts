// Content-Security-Policy with a per-request nonce (set by src/proxy.ts).
// Scripts: only nonce-bearing scripts (Next attaches the nonce to its own) + 'strict-dynamic'.
// Styles: 'unsafe-inline' remains because React `style={{…}}` attributes cannot carry a
// nonce (accepted residual risk: CSS injection only, no script execution).

export function buildCsp(nonce: string, opts: { dev: boolean; storageOrigin: string }): string {
  const { dev, storageOrigin } = opts;
  return [
    "default-src 'self'",
    // 'wasm-unsafe-eval': MediaPipe (self-hosted) compiles WebAssembly. Dev adds eval for React tooling.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'wasm-unsafe-eval'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${storageOrigin}${dev ? " ws:" : ""}`,
    "media-src 'self' blob:",
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    ...(dev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

/** 128 random bits, base64. */
export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}
