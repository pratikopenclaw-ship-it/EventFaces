"use client";

import { useState } from "react";

import { Alert, Badge, Button, Card, Field, Textarea } from "@/components/ui";
import { del, post } from "@/lib/api";
import type { Invite, InviteUploadResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const TONE = { pending: "warn", accepted: "good", revoked: "bad" } as const;

export function InvitesPanel({ eventId }: { eventId: string }) {
  const list = useApi<Invite[]>(`/api/events/${eventId}/invites`);
  const [csv, setCsv] = useState("");
  const [result, setResult] = useState<InviteUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      setResult(await post<InviteUploadResult>(`/api/events/${eventId}/invites`, { csv }));
      setCsv("");
      await list.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send invites");
    } finally {
      setBusy(false);
    }
  }

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await list.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  const invites = list.data ?? [];
  const accepted = invites.filter((i) => i.status === "accepted").length;

  return (
    <div className="space-y-6">
      {error && <Alert>{error}</Alert>}
      <Card>
        <h2 className="font-medium">Invite people</h2>
        <p className="mt-1 text-sm text-muted">
          Paste a list or upload a CSV. Each person gets a personal magic link that only works for their email address.
        </p>
        <div className="mt-4 space-y-3">
          <Field label="Email addresses" hint="One per line, or any CSV with an email column.">
            <Textarea
              value={csv}
              onChange={(e) => setCsv(e.target.value)}
              placeholder={"anna@example.com\nben@example.com"}
              className="min-h-32 font-mono text-xs"
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={busy || csv.trim().length < 3} onClick={() => void send()}>
              {busy ? "Sending…" : "Send invites"}
            </Button>
            <label className="cursor-pointer text-sm font-medium text-accent hover:underline">
              Upload CSV file
              <input
                type="file"
                accept=".csv,text/csv,text/plain"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void file.text().then(setCsv);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        </div>
        {result && (
          <div className="mt-4 space-y-1 text-sm">
            <Alert kind="success">Sent {result.sent.length} {result.sent.length === 1 ? "invite" : "invites"}.</Alert>
            {result.already_members.length > 0 && (
              <p className="text-muted">Already members: {result.already_members.join(", ")}</p>
            )}
            {result.already_accepted.length > 0 && (
              <p className="text-muted">Already accepted: {result.already_accepted.join(", ")}</p>
            )}
            {result.invalid.length > 0 && <p className="text-alarm">Not valid emails: {result.invalid.join(", ")}</p>}
          </div>
        )}
      </Card>

      <div className="overflow-x-auto rounded-2xl border border-line bg-paper">
        <div className="flex items-center justify-between border-b border-line px-5 py-3 text-sm">
          <span className="font-medium">Invites</span>
          <span className="text-muted">
            {accepted} of {invites.length} accepted
          </span>
        </div>
        <table className="w-full text-left text-sm">
          <tbody>
            {invites.length === 0 && (
              <tr>
                <td className="px-5 py-6 text-center text-muted">No invites yet.</td>
              </tr>
            )}
            {invites.map((i) => (
              <tr key={i.id} className="border-b border-line last:border-0">
                <td className="px-5 py-3">{i.email}</td>
                <td className="px-5 py-3">
                  <Badge tone={TONE[i.status]}>{i.status.charAt(0).toUpperCase() + i.status.slice(1)}</Badge>
                </td>
                <td className="px-5 py-3 text-muted">
                  {i.accepted_at
                    ? `Joined ${new Date(i.accepted_at).toLocaleDateString()}`
                    : i.sent_at
                      ? `Sent ${new Date(i.sent_at).toLocaleDateString()}`
                      : ""}
                </td>
                <td className="px-5 py-3 text-right">
                  {i.status !== "accepted" && (
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" onClick={() => void run(() => post(`/api/events/${eventId}/invites/${i.id}/resend`))}>
                        {i.status === "revoked" ? "Re-invite" : "Resend"}
                      </Button>
                      {i.status === "pending" && (
                        <Button variant="ghost" onClick={() => void run(() => del(`/api/events/${eventId}/invites/${i.id}`))}>
                          Revoke
                        </Button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
