import Link from "next/link";

/** Required at every account creation. Unticked by default; the server records the
 * accepted version with time and channel (proof of inclusion of the terms). */
export function TermsCheckbox() {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-lg bg-mist p-3 text-sm">
      <input type="checkbox" name="accept_terms" required className="mt-0.5 size-4 accent-accent" />
      <span>
        I accept the{" "}
        <Link href="/terms" target="_blank" className="text-accent underline underline-offset-2">
          Terms of Use
        </Link>{" "}
        and confirm that I am at least 16 years old. The{" "}
        <Link href="/privacy" target="_blank" className="text-accent underline underline-offset-2">
          Privacy Notice
        </Link>{" "}
        explains how we handle your data.
      </span>
    </label>
  );
}
