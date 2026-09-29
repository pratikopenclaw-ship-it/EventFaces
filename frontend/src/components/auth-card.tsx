import type { ReactNode } from "react";

export function AuthCard({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-sm pt-6">
      <h1 className="font-display text-3xl tracking-tight">{title}</h1>
      {subtitle && <p className="mt-2 text-sm text-ink/60">{subtitle}</p>}
      <div className="mt-8 rounded-2xl border border-line bg-paper p-6">{children}</div>
    </div>
  );
}

/** Only allow same-site relative redirects (prevents open redirects via ?next=). */
export function safeNext(next: string | string[] | undefined, fallback = "/events"): string {
  const value = Array.isArray(next) ? next[0] : next;
  return value && value.startsWith("/") && !value.startsWith("//") ? value : fallback;
}
