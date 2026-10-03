"""The face-search consent text: one versioned source for the web app and the iOS app.

Users consent to a specific version (`search.FACE_CONSENT_VERSION`). Changing any word
here must bump that version so everyone is asked again: `tests/test_consent_text.py`
pins a hash of the text per version and fails otherwise.

German is a draft translation pending legal review (see SECURITY_QA_REPORT.md).
"""

from dataclasses import dataclass

LOCALES = ("en", "de")


@dataclass(frozen=True)
class Section:
    heading: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class ConsentText:
    title: str
    intro: str
    sections: tuple[Section, ...]
    agreement: str  # the checkbox label
    action: str  # the button


_TEXTS: dict[str, ConsentText] = {
    "en": ConsentText(
        title="Before we look for you",
        intro="Finding your photos uses face recognition. Face data is biometric data under the GDPR, so we need your explicit consent first.",
        sections=(
            Section(
                "What we process",
                ("Three quick selfies you take now. We turn the face in them into a numeric face template and compare it with the faces in this event's photos only.",),
            ),
            Section("Why", ("Only to show you the photos you appear in, so you can view and download them.",)),
            Section(
                "What we keep and for how long",
                (
                    "Your selfies and their face template are deleted immediately after matching. They are processed in memory and never saved.",
                    "If many people are searching at once, your selfies may wait in our server's memory for up to 15 minutes until it's your turn; we then email you when your photos are ready. They are still never saved, and are deleted right after matching, or if the wait runs out.",
                    "We keep the list of photos you matched for {grant_days} days (or until the event's access ends) so you can come back and download them.",
                    "A security log records that you searched, when, and how many photos matched. It never includes your selfie.",
                ),
            ),
            Section(
                "Legal basis and your rights",
                (
                    "Your explicit consent (Art. 9(2)(a) GDPR). You can withdraw it at any time on this page, and we then delete the list of photos you matched. Withdrawal doesn't make searches you already did unlawful.",
                ),
            ),
        ),
        agreement="I consent to EventFaces processing my selfie as described above to find my photos.",
        action="Continue to selfie",
    ),
    "de": ConsentText(
        title="Bevor wir nach dir suchen",
        intro="Um deine Fotos zu finden, nutzen wir Gesichtserkennung. Gesichtsdaten sind nach der DSGVO biometrische Daten, deshalb brauchen wir zuerst deine ausdrückliche Einwilligung.",
        sections=(
            Section(
                "Was wir verarbeiten",
                ("Drei kurze Selfies, die du jetzt aufnimmst. Wir wandeln das Gesicht darin in eine numerische Gesichtsvorlage um und vergleichen sie nur mit den Gesichtern auf den Fotos dieses Events.",),
            ),
            Section("Warum", ("Nur, um dir die Fotos zu zeigen, auf denen du zu sehen bist, damit du sie ansehen und herunterladen kannst.",)),
            Section(
                "Was wir speichern und wie lange",
                (
                    "Deine Selfies und ihre Gesichtsvorlage werden direkt nach dem Abgleich gelöscht. Sie werden nur im Arbeitsspeicher verarbeitet und nie gespeichert.",
                    "Wenn viele Menschen gleichzeitig suchen, können deine Selfies bis zu 15 Minuten im Arbeitsspeicher unseres Servers warten, bis du an der Reihe bist; wir schicken dir dann eine E-Mail, sobald deine Fotos bereit sind. Auch dann werden sie nie gespeichert und direkt nach dem Abgleich gelöscht, oder wenn die Wartezeit abläuft.",
                    "Die Liste der Fotos, auf denen wir dich gefunden haben, behalten wir {grant_days} Tage (oder bis der Zugang zum Event endet), damit du sie später herunterladen kannst.",
                    "Ein Sicherheitsprotokoll hält fest, dass und wann du gesucht hast und wie viele Fotos gefunden wurden. Dein Selfie ist nie darin enthalten.",
                ),
            ),
            Section(
                "Rechtsgrundlage und deine Rechte",
                (
                    "Deine ausdrückliche Einwilligung (Art. 9 Abs. 2 lit. a DSGVO). Du kannst sie jederzeit hier widerrufen; wir löschen dann die Liste der Fotos, auf denen wir dich gefunden haben. Der Widerruf macht bereits durchgeführte Suchen nicht rechtswidrig.",
                ),
            ),
        ),
        agreement="Ich willige ein, dass EventFaces mein Selfie wie oben beschrieben verarbeitet, um meine Fotos zu finden.",
        action="Weiter zum Selfie",
    ),
}


def locale_from(accept_language: str | None) -> str:
    """The first supported language in Accept-Language; English otherwise."""
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag[:2] in LOCALES:
            return tag[:2]
    return "en"


def consent_text(locale: str, grant_days: int) -> ConsentText:
    t = _TEXTS[locale if locale in _TEXTS else "en"]
    return ConsentText(
        title=t.title,
        intro=t.intro,
        sections=tuple(Section(s.heading, tuple(p.replace("{grant_days}", str(grant_days)) for p in s.paragraphs)) for s in t.sections),
        agreement=t.agreement,
        action=t.action,
    )


def fingerprint() -> str:
    """Hash of every locale's raw text (placeholders unexpanded)."""
    import hashlib
    import json
    from dataclasses import asdict

    return hashlib.sha256(json.dumps({k: asdict(v) for k, v in sorted(_TEXTS.items())}, sort_keys=True).encode()).hexdigest()
