import Link from "next/link";

export const metadata = { title: "Privacy · EventFaces" };

// NOTE FOR THE OPERATOR: fill in the [bracketed] parts and have the text reviewed by
// your data protection advisor before going live. Face search is biometric processing
// (GDPR Art. 9) and likely requires a DPIA (Art. 35).

const RETENTION: [string, string][] = [
  ["Your selfies and their face template", "Not stored. Processed in memory and deleted as soon as matching finishes (if the service is busy, they wait in memory for at most 15 minutes)."],
  ["Face templates of people in event photos", "Until the event's access period ends, then deleted automatically."],
  ["Which photos you matched", "7 days, or until the event's access ends if that's sooner. Deleted when you withdraw consent."],
  ["Event photos", "As decided by the organizer; optionally deleted when access ends."],
  ["Search log (who searched, when, number of matches)", "365 days. Anonymized if you delete your account."],
  ["Your account", "Until you delete it. Accounts that never verified their email are deleted after 14 days."],
  ["Removal requests", "Unconfirmed: 48 hours. Completed: 180 days."],
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="font-display text-xl">{title}</h2>
      <div className="space-y-2 text-sm leading-relaxed text-ink/75">{children}</div>
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-8">
      <header>
        <h1 className="font-display text-4xl tracking-tight">Privacy notice</h1>
        <p className="mt-2 text-sm text-ink/70">How EventFaces handles your data.</p>
      </header>

      <Section title="Who is responsible">
        <p>
          The controller is [operator name, address, email]. For each event, the event organizer decides which photos
          are published. Data protection contact: [DPO or contact email].
        </p>
      </Section>

      <Section title="What we process and why">
        <p>
          <strong>Account data</strong> (email, password hash) to give you access to events you belong to (Art. 6(1)(b)
          GDPR).
        </p>
        <p>
          <strong>Face search.</strong> When you search, we turn the face in your selfie into a numeric template and
          compare it with faces in that event&apos;s photos only. Faces are biometric data, so we do this only with your
          explicit consent (Art. 9(2)(a) GDPR), which you can withdraw at any time on your{" "}
          <Link href="/account" className="text-accent underline underline-offset-2">
            account page
          </Link>
          .
        </p>
        <p>
          <strong>Event photos</strong> are provided by the organizer or uploaded by attendees. Location and camera
          metadata are removed from every photo. Other attendees only see a photo if they appear in it.
        </p>
        <p>
          <strong>Security logs</strong> (searches, rate limiting) to protect the service and detect misuse (Art.
          6(1)(f) GDPR).
        </p>
      </Section>

      <Section title="How long we keep it">
        <table className="w-full text-left">
          <tbody>
            {RETENTION.map(([what, how]) => (
              <tr key={what} className="border-b border-line align-top last:border-0">
                <td className="py-2 pr-4 font-medium text-ink">{what}</td>
                <td className="py-2">{how}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Recipients">
        <p>
          Hosting and storage: [hosting provider, storage provider, e.g. Cloudflare R2 (region)]. Email delivery:
          [email provider]. Photos from Google Drive are imported via Google&apos;s API when an organizer links a folder.
          We don&apos;t sell data or use it for advertising.
        </p>
      </Section>

      <Section title="Your rights">
        <p>
          You can access, correct, delete or export your data, restrict or object to processing, and withdraw consent at
          any time. Delete your account and its data yourself on the{" "}
          <Link href="/account" className="text-accent underline underline-offset-2">
            account page
          </Link>
          . If you appear in an event&apos;s photos, attendee or not, you can{" "}
          <Link href="/removal-request" className="text-accent underline underline-offset-2">
            request removal
          </Link>
          . You can also complain to a supervisory authority, for example the Berlin Commissioner for Data Protection
          and Freedom of Information.
        </p>
      </Section>
    </article>
  );
}
