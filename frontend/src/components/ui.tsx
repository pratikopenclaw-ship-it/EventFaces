import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover",
  secondary: "border border-line bg-paper text-ink hover:bg-mist",
  danger: "bg-alarm text-paper hover:bg-alarm/85",
  ghost: "text-muted hover:text-ink hover:bg-mist",
};

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition",
        "disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

const fieldBase =
  "w-full rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink/40 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(fieldBase, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(fieldBase, "min-h-24", props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldBase, props.className)} />;
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 accent-accent"
      />
      <span>
        <span className="block text-sm font-medium text-ink">{label}</span>
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
    </label>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-2xl border border-line bg-paper p-6", className)}>{children}</div>;
}

export function Alert({ kind = "error", children }: { kind?: "error" | "success" | "info"; children: ReactNode }) {
  const styles = {
    error: "border-alarm/30 bg-alarm/5 text-alarm",
    success: "border-leaf/30 bg-leaf/5 text-leaf",
    info: "border-accent/30 bg-accent-soft text-ink",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={cx("rounded-lg border px-3 py-2 text-sm", styles)}>
      {children}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const styles = {
    neutral: "bg-mist text-muted",
    // Badge text is darker than the tone colour: small text on a tint needs >= 4.5:1.
    good: "bg-leaf/10 text-good",
    warn: "bg-warn-tint text-warn",
    bad: "bg-alarm/10 text-bad",
  }[tone];
  return <span className={cx("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", styles)}>{children}</span>;
}

/** A list, table or search with nothing in it: an icon, a heading, and optional detail/action.
 * `compact` fits inside a table row (`<td>`); otherwise it reads as a standalone block,
 * typically inside a Card. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  compact = false,
}: {
  icon: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cx("flex flex-col items-center text-center", compact ? "gap-1.5" : "gap-3 py-2")}>
      <span
        className={cx(
          "flex items-center justify-center rounded-full bg-accent-soft text-accent",
          compact ? "size-8" : "size-12",
        )}
        aria-hidden="true"
      >
        {icon}
      </span>
      <div className={compact ? "space-y-0.5" : "space-y-1"}>
        <p className={cx("font-medium text-ink", compact ? "text-sm" : "text-base")}>{title}</p>
        {description && <p className="text-sm text-muted">{description}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export function formatDate(value: string | null): string {
  if (!value) return "No date";
  return new Date(value.length === 10 ? `${value}T00:00:00` : value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
