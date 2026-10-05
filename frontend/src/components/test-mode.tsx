/** Shown on every billing screen while the fake payment provider is in use. */
export function TestModeBanner() {
  return (
    <div role="note" className="mb-6 rounded-lg border border-warn/40 bg-warn-tint px-4 py-3 text-sm text-warn">
      <strong className="font-semibold">TEST MODE</strong> · No real money is charged. Use the test cards shown at checkout;
      real card numbers are refused.
    </div>
  );
}
