import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { ContactForm } from "@/components/landing/contact-form";
import { ContactSheet } from "@/components/landing/contact-sheet";
import { HeroActions } from "@/components/landing/hero-actions";
import { SectionNav } from "@/components/landing/section-nav";
import { Pricing } from "@/components/pricing";

export const metadata: Metadata = {
  title: "EventFaces: find every photo of you from the event",
  description:
    "Join your event, take a quick selfie, and see only the photos you're in. Your selfie is never stored. For organizers: per-event plans and a monthly subscription.",
  openGraph: {
    title: "EventFaces: find every photo of you from the event",
    description: "A selfie finds your photos among thousands. Selfies are never stored; face data stays in its event.",
    type: "website",
  },
};

function Section({ id, title, intro, children, className = "" }: { id: string; title: string; intro?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={`landing-section py-16 ${className}`}>
      <h2 id={`${id}-title`} className="font-display text-3xl tracking-tight text-ink md:text-4xl">
        {title}
      </h2>
      {intro && <p className="mt-3 max-w-2xl text-muted">{intro}</p>}
      <div className="mt-10">{children}</div>
    </section>
  );
}

function Steps({ title, steps }: { title: string; steps: [string, string][] }) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-ink">{title}</h3>
      <ol className="mt-5 space-y-6">
        {steps.map(([head, text], i) => (
          <li key={head} className="grid grid-cols-[2.5rem_1fr] gap-x-3">
            <span aria-hidden="true" className="font-display text-3xl leading-none text-accent">
              {i + 1}
            </span>
            <div>
              <p className="font-medium text-ink">{head}</p>
              <p className="mt-1 text-sm text-muted">{text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

const FEATURES: [string, string][] = [
  ["Best and possible matches", "Results come in two tiers, so a blurry side profile doesn't hide behind a sharp portrait."],
  ["One photo or all of them", "Download single photos in full resolution, or everything you're in as one ZIP."],
  ["Guest uploads", "Attendees can add their own shots. You approve them first, or let them through automatically."],
  ["Your event, your look", "Add your logo and brand colour; the event pages follow it in light and dark mode."],
  ["Photos straight from Google Drive", "Share a Drive folder once; new photos are imported and indexed as they arrive."],
  ["iPhone app", "Attendees can also use the EventFaces app: same account, same privacy rules."],
];

const PROMISES: [string, string][] = [
  ["Selfies are never stored", "They are compared in memory and discarded the moment the search ends. Not on disk, not in backups."],
  ["Face data stays in its event", "A search only ever looks at the event you joined, never across events."],
  ["Nothing without consent", "You read what happens before the camera turns on, and you can withdraw consent at any time."],
  ["Deleted on schedule", "When an event's access period ends, its face data is deleted automatically."],
  ["No trackers, no ads", "Only strictly necessary cookies. No analytics or advertising scripts on any page."],
  ["People in photos have a say", "Anyone can ask for a photo of them to be removed, even without an account."],
];

const FAQ: [string, ReactNode][] = [
  ["Do I need to install an app?", "No. Everything works in your phone's browser. There's an optional iPhone app if you prefer."],
  [
    "What happens to my selfie?",
    "It is used for one search and discarded straight away. We keep only the list of photos you matched, so you can find them again, for a limited time.",
  ],
  [
    "Who can see the photos I'm in?",
    "Your search results are yours. Organizers see all photos of their event, as they would in any shared album; other attendees only see photos they appear in.",
  ],
  [
    "I'm in a photo and want it taken down.",
    <>
      Send a <Link href="/removal-request" className="underline hover:text-ink">removal request</Link>. You don&apos;t need an account, and the organizer
      reviews it.
    </>,
  ],
  ["How do the photos get in?", "The organizer connects a Google Drive folder, lets guests upload, or both. New photos are processed automatically."],
  ["Do attendees pay anything?", "No. Organizers pay per event or by subscription; joining and searching are free."],
  ["Can we try it before our event?", "Yes. Get in touch below and tell us about your event."],
];

export default function Home() {
  return (
    <>
      <section className="grid gap-12 pb-12 md:grid-cols-[1fr_1.15fr] md:items-center" aria-labelledby="hero-title">
        <div>
          <h1 id="hero-title" className="font-display text-5xl leading-[1.04] tracking-tight text-ink md:text-6xl">
            Skip the scroll. Find every photo of you.
          </h1>
          <p className="mt-6 max-w-md text-lg text-muted">
            Join your event, take a quick selfie, and see only the photos you&apos;re in. Your selfie is deleted as soon as the search
            is done.
          </p>
          <HeroActions />
        </div>
        <ContactSheet />
      </section>

      <SectionNav />

      <Section id="how" title="How it works" intro="Two minutes for attendees, one setup for organizers.">
        <div className="grid gap-12 md:grid-cols-2">
          <Steps
            title="At the event"
            steps={[
              ["Join", "Scan the QR code or type the access code from the organizer."],
              ["Agree and take a selfie", "Read what happens to your data, then look at the camera and turn your head left and right."],
              ["Get your photos", "See every photo you're in and download them, one by one or all at once."],
            ]}
          />
          <Steps
            title="For organizers"
            steps={[
              ["Pick a plan", "Per event or monthly. Your event is ready as soon as you've paid."],
              ["Add the photos", "Connect a Google Drive folder, switch on guest uploads, or both."],
              ["Share the link", "Put the QR code on a table card or send the join link. That's all attendees need."],
            ]}
          />
        </div>
      </Section>

      <section id="privacy" aria-labelledby="privacy-title" className="landing-section theme-dark my-16 rounded-3xl border border-line bg-canvas px-6 py-14 text-ink md:px-12">
        <h2 id="privacy-title" className="max-w-2xl font-display text-3xl tracking-tight md:text-4xl">
          Faces are biometric data. We treat them that way.
        </h2>
        <p className="mt-3 max-w-2xl text-muted">
          EventFaces is built around the GDPR&apos;s strictest category of personal data, and hosted in the EU.
        </p>
        <dl className="mt-10 grid gap-x-12 gap-y-8 md:grid-cols-2">
          {PROMISES.map(([title, text]) => (
            <div key={title} className="border-l-2 border-accent pl-4">
              <dt className="font-medium text-ink">{title}</dt>
              <dd className="mt-1 text-sm text-muted">{text}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-10 text-sm text-muted">
          The details are in our <Link href="/privacy" className="text-ink underline">privacy notice</Link>.
        </p>
      </section>

      <Section id="features" title="What you get">
        <dl className="grid gap-x-12 gap-y-8 md:grid-cols-2">
          {FEATURES.map(([title, text]) => (
            <div key={title}>
              <dt className="font-medium text-ink">{title}</dt>
              <dd className="mt-1 text-sm text-muted">{text}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <section id="pricing" aria-label="Pricing" className="landing-section py-16">
        <Pricing />
      </section>

      <Section id="faq" title="Questions people ask">
        <div className="max-w-3xl divide-y divide-line border-y border-line">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium text-ink focus-visible:outline-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
                {q}
                <span aria-hidden="true" className="text-xl leading-none text-muted transition group-open:rotate-45">
                  +
                </span>
              </summary>
              <p className="mt-3 max-w-2xl text-sm text-muted">{a}</p>
            </details>
          ))}
        </div>
      </Section>

      <Section id="contact" title="Talk to us" intro="Planning an event, a question about your photos, or about your data: write to us.">
        <div className="grid gap-10 md:grid-cols-[1.6fr_1fr]">
          <ContactForm />
          <aside className="text-sm text-muted">
            <p>Organizers usually ask about event size, how photos get in, and dates. Mention those and we can answer in one go.</p>
            <p className="mt-4">
              Our address and legal details are in the <Link href="/imprint" className="underline hover:text-ink">imprint</Link>.
            </p>
          </aside>
        </div>
      </Section>

      <section aria-labelledby="cta-title" className="mt-8 flex flex-wrap items-center justify-between gap-6 rounded-3xl bg-accent px-6 py-10 text-on-accent md:px-12">
        <h2 id="cta-title" className="font-display text-3xl tracking-tight">
          Running an event soon?
        </h2>
        <a
          href="#pricing"
          className="rounded-lg bg-paper px-5 py-3 font-medium text-ink hover:bg-mist focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-paper"
        >
          See plans
        </a>
      </section>
    </>
  );
}
