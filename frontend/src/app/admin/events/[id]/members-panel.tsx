"use client";

import { useState, type FormEvent } from "react";

import { useSession } from "@/components/session";
import { Alert, Badge, Button, Card, Field, Input, formatDate } from "@/components/ui";
import { patch, post } from "@/lib/api";
import type { Member, MemberStatus, SearchLogRow } from "@/lib/types";
import { useApi } from "@/lib/use-api";

const STATUS_TONE = { approved: "good", pending: "warn", revoked: "bad" } as const;

export function MembersPanel({ eventId }: { eventId: string }) {
  const { user } = useSession();
  const { data: members, error, reload } = useApi<Member[]>(`/api/events/${eventId}/members`);
  const [actionError, setActionError] = useState<string | null>(null);
  const searchLog = useApi<SearchLogRow[]>(`/api/events/${eventId}/search-log`);
  const isSuperAdmin = user?.role === "super_admin";

  async function setStatus(m: Member, status: MemberStatus) {
    setActionError(null);
    try {
      await patch(`/api/events/${eventId}/members/${m.user_id}`, { status });
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Update failed");
    }
  }

  async function assignOrganizer(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setActionError(null);
    try {
      await post(`/api/events/${eventId}/organizers`, { email: new FormData(form).get("email") });
      form.reset();
      await reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not assign organizer");
    }
  }

  return (
    <div className="space-y-6">
      {(error || actionError) && <Alert>{actionError ?? error?.message}</Alert>}
      {isSuperAdmin && (
        <Card>
          <form method="post" onSubmit={assignOrganizer} className="flex flex-wrap items-end gap-3">
            <div className="min-w-64 flex-1">
              <Field label="Add organizer" hint="The person must already have an account.">
                <Input name="email" type="email" placeholder="organizer@example.com" required />
              </Field>
            </div>
            <Button type="submit" className="mb-5">
              Assign
            </Button>
          </form>
        </Card>
      )}
      <div className="overflow-x-auto rounded-2xl border border-line bg-paper">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-ink/70">
            <tr>
              <th className="px-5 py-3 font-medium">Email</th>
              <th className="px-5 py-3 font-medium">Role</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Joined</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody>
            {members?.length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-6 text-center text-ink/70">
                  No members yet.
                </td>
              </tr>
            )}
            {members?.map((m) => {
              const editable = m.role === "attendee" || isSuperAdmin;
              return (
                <tr key={m.user_id} className="border-b border-line last:border-0">
                  <td className="px-5 py-3">{m.email}</td>
                  <td className="px-5 py-3 capitalize">{m.role}</td>
                  <td className="px-5 py-3">
                    <Badge tone={STATUS_TONE[m.status]}>{m.status}</Badge>
                  </td>
                  <td className="px-5 py-3 text-ink/70">{formatDate(m.joined_at)}</td>
                  <td className="px-5 py-3 text-right">
                    {editable && m.user_id !== user?.id && (
                      m.status === "approved" ? (
                        <Button variant="ghost" onClick={() => void setStatus(m, "revoked")}>
                          Revoke
                        </Button>
                      ) : (
                        <Button variant="secondary" onClick={() => void setStatus(m, "approved")}>
                          Approve
                        </Button>
                      )
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-line bg-paper">
        <div className="border-b border-line px-5 py-3 text-sm">
          <span className="font-medium">Search log</span>{" "}
          <span className="text-ink/70">(who searched and how many photos matched; selfies are never stored)</span>
        </div>
        <table className="w-full text-left text-sm">
          <tbody>
            {(searchLog.data ?? []).length === 0 && (
              <tr>
                <td className="px-5 py-6 text-center text-ink/70">No searches yet.</td>
              </tr>
            )}
            {(searchLog.data ?? []).map((row, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                <td className="px-5 py-2.5">{row.user_email ?? <span className="text-ink/70">deleted account</span>}</td>
                <td className="px-5 py-2.5 text-ink/70">{row.match_count} matched</td>
                <td className="px-5 py-2.5 text-right text-ink/70">{new Date(row.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
