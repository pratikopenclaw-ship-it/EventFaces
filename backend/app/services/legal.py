"""Legal documents, one versioned source for the web app and the iOS app: Terms of Use,
Organizer Terms with the data processing agreement (Art. 28 GDPR), Privacy Notice and the
Impressum (§ 5 DDG).

German is binding; English is a convenience translation. The operator's identity comes from
settings (LEGAL_*); `Settings` refuses to start in production while required fields are
empty. Accepting the Terms or the Organizer Terms is recorded per version
(`legal_acceptances`): changing any word of an accepted document must bump its version so
everyone is asked again, and `tests/test_legal.py` pins a hash per version to enforce that.

These texts are drafts written for how EventFaces works. They must be reviewed by a lawyer
before launch (see LEGAL_REVIEW.md).
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from app.core.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import User

LOCALES = ("de", "en")
BINDING_LOCALE = "de"
MIN_AGE = 16

Document = Literal["terms", "organizer-terms", "privacy", "imprint"]
DOCUMENTS: tuple[Document, ...] = ("terms", "organizer-terms", "privacy", "imprint")
# Documents users accept (and must accept again when the version changes).
ACCEPTED: tuple[Document, ...] = ("terms", "organizer-terms")
VERSIONS: dict[Document, str] = {
    "terms": "2026-10-03",
    "organizer-terms": "2026-10-03",
    "privacy": "2026-10-29",
    "imprint": "2026-10-03",
}

# Placeholders: {name} is required in production; [name] in a paragraph marks an optional
# field whose whole paragraph is left out when the field is empty.
OPTIONAL_FIELDS = ("register", "vat_id")


@dataclass(frozen=True)
class Section:
    heading: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class LegalText:
    title: str
    intro: str
    sections: tuple[Section, ...]


def _s(heading: str, *paragraphs: str) -> Section:
    return Section(heading, paragraphs)


# --- Terms of Use ---------------------------------------------------------------------------

_TERMS_DE = LegalText(
    title="Nutzungsbedingungen",
    intro="Diese Nutzungsbedingungen gelten für die Nutzung von EventFaces über die Website und die iOS-App.",
    sections=(
        _s(
            "1. Geltungsbereich und Anbieter",
            "EventFaces wird betrieben von {operator_name}, {operator_address} („wir“). Diese Bedingungen gelten für alle Nutzerinnen und Nutzer. Für Veranstalter gelten zusätzlich die Veranstalterbedingungen mit dem Auftragsverarbeitungsvertrag.",
            "Abweichende Bedingungen von Nutzerinnen und Nutzern gelten nicht, auch wenn wir ihnen nicht ausdrücklich widersprechen.",
        ),
        _s(
            "2. Leistungen",
            "Mit EventFaces finden Teilnehmende einer Veranstaltung die Fotos dieser Veranstaltung, auf denen sie zu sehen sind, über eine Selfie-Suche, sehen sie an und laden sie herunter. Wo der Veranstalter es zulässt, können Teilnehmende eigene Fotos beitragen.",
            "Welche Fotos veröffentlicht werden und wer einer Veranstaltung beitreten darf, entscheidet der Veranstalter. Ein Anspruch auf bestimmte Fotos oder Treffer besteht nicht. Die automatische Gesichtssuche kann Fotos übersehen oder falsch zuordnen; Sie können falsche Treffer markieren.",
        ),
        _s(
            "3. Voraussetzungen und Konto",
            "Sie müssen mindestens {min_age} Jahre alt sein. Jedes Konto gehört einer Person. Halten Sie Ihre E-Mail-Adresse aktuell und Anmeldecodes, Links und Passwörter geheim, und informieren Sie uns, wenn Sie einen Missbrauch Ihres Kontos vermuten.",
        ),
        _s(
            "4. Kosten",
            "Die Nutzung ist für Teilnehmende kostenlos. Kostenpflichtige Leistungen für Veranstalter regeln die Veranstalterbedingungen.",
        ),
        _s(
            "5. Teilnahme an Veranstaltungen",
            "Sie treten einer Veranstaltung über einen Zugangscode, einen Link oder eine Einladung bei, wie der Veranstalter es festlegt. Der Veranstalter kann Ihre Teilnahme beenden. Mit dem Ende des Zugangszeitraums einer Veranstaltung endet auch Ihr Zugang zu ihren Fotos.",
        ),
        _s(
            "6. Gesichtssuche",
            "Die Gesichtssuche ist freiwillig und erfordert Ihre ausdrückliche Einwilligung, die Sie gesondert erteilen und jederzeit widerrufen können. Einzelheiten stehen in der Datenschutzerklärung.",
            "Sie dürfen nur nach sich selbst suchen. Die Suche mit Fotos anderer Personen ist untersagt.",
        ),
        _s(
            "7. Eigene Fotos",
            "Laden Sie nur Fotos hoch, die Sie selbst aufgenommen haben oder für die Sie die nötigen Rechte besitzen. Sie sind dafür verantwortlich, dass die Veröffentlichung zulässig ist, insbesondere dass abgebildete Personen einverstanden sind, wo das Gesetz es verlangt (§§ 22, 23 KUG, DSGVO). Rechtswidrige Inhalte sind untersagt.",
            "Sie räumen uns und dem Veranstalter ein einfaches, unentgeltliches, auf den Betrieb von EventFaces beschränktes Recht ein, Ihre Fotos zu speichern, zu bearbeiten (Größe, Format, Entfernen von Metadaten), für die Gesichtssuche zu verarbeiten und den Teilnehmenden der Veranstaltung nach diesen Regeln anzuzeigen. Das Recht endet, wenn Sie das Foto löschen lassen oder Ihr Konto löschen.",
        ),
        _s(
            "8. Unzulässige Nutzung",
            "Untersagt sind insbesondere: die Suche nach anderen Personen; automatisierte Zugriffe (Scraping, Bots) außerhalb der von uns bereitgestellten Apps; das Umgehen von Sicherheits- und Zugangsbeschränkungen; das Hochladen von Schadsoftware; jede Nutzung, die Rechte Dritter verletzt.",
            "Heruntergeladene Fotos dürfen Sie für private Zwecke nutzen. Achten Sie bei jeder Weitergabe die Rechte der abgebildeten Personen.",
        ),
        _s(
            "9. Meldungen und Kontaktstelle (Digital Services Act)",
            "Rechtswidrige oder unerwünschte Inhalte melden Sie über „Melden“ am Foto, über die Seite „Entfernung anfragen“ (auch ohne Konto) oder per E-Mail an {email}. Wir prüfen Meldungen sorgfältig und zügig, informieren Sie über unsere Entscheidung und begründen Einschränkungen. Gegen Entscheidungen können Sie sich unter {email} beschweren.",
            "Zentrale Kontaktstelle für Behörden und Nutzer (Art. 11, 12 DSA): {email}. Sprachen: Deutsch, Englisch.",
        ),
        _s(
            "10. Verfügbarkeit und Änderungen des Dienstes",
            "Wir bemühen uns um einen störungsfreien Betrieb, schulden aber keine ununterbrochene Verfügbarkeit, insbesondere nicht während Wartungsarbeiten. Wir dürfen Funktionen ändern, soweit das für Sie zumutbar ist.",
        ),
        _s(
            "11. Laufzeit und Kündigung",
            "Sie können Ihr Konto jederzeit in der App oder auf der Website löschen. Wir können den Nutzungsvertrag mit einer Frist von zwei Wochen kündigen, aus wichtigem Grund (insbesondere bei Verstößen gegen Ziffern 6 bis 8) auch fristlos. Nach dem Ende löschen wir Ihre Daten wie in der Datenschutzerklärung beschrieben.",
        ),
        _s(
            "12. Haftung",
            "Wir haften unbeschränkt bei Vorsatz und grober Fahrlässigkeit, bei der Verletzung von Leben, Körper oder Gesundheit, nach dem Produkthaftungsgesetz und im Umfang übernommener Garantien.",
            "Bei leichter Fahrlässigkeit haften wir nur für die Verletzung wesentlicher Vertragspflichten, deren Erfüllung die ordnungsgemäße Durchführung des Vertrags überhaupt erst ermöglicht und auf deren Einhaltung Sie regelmäßig vertrauen dürfen, und zwar begrenzt auf den vertragstypischen, vorhersehbaren Schaden. Im Übrigen ist die Haftung ausgeschlossen. Diese Regeln gelten auch für unsere Mitarbeitenden und Beauftragten.",
        ),
        _s(
            "13. Änderungen dieser Bedingungen",
            "Wir können diese Bedingungen aus sachlichem Grund ändern (etwa bei neuen Funktionen oder geänderter Rechtslage), soweit das für Sie zumutbar ist. Die neue Fassung zeigen wir Ihnen vor der weiteren Nutzung an; sie gilt erst, wenn Sie ihr zustimmen. Stimmen Sie nicht zu, können Sie den Dienst nicht weiter nutzen, Ihr Konto aber jederzeit löschen.",
        ),
        _s(
            "14. Schlussbestimmungen",
            "Es gilt das Recht der Bundesrepublik Deutschland unter Ausschluss des UN-Kaufrechts. Für Verbraucherinnen und Verbraucher gilt diese Rechtswahl nur, soweit ihnen nicht der Schutz zwingender Vorschriften des Staates ihres gewöhnlichen Aufenthalts entzogen wird.",
            "Ist die Nutzerin oder der Nutzer Kaufmann, juristische Person des öffentlichen Rechts oder öffentlich-rechtliches Sondervermögen, ist Gerichtsstand unser Sitz.",
            "Wir sind nicht bereit und nicht verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.",
            "Verbindlich ist die deutsche Fassung; die englische Fassung dient nur der Information. Sind einzelne Bestimmungen unwirksam, bleibt der Vertrag im Übrigen wirksam (§ 306 BGB).",
        ),
    ),
)

_TERMS_EN = LegalText(
    title="Terms of Use",
    intro="These Terms of Use apply to using EventFaces through the website and the iOS app. The German version is binding; this English version is a translation for your convenience.",
    sections=(
        _s(
            "1. Scope and provider",
            "EventFaces is operated by {operator_name}, {operator_address} (“we”). These terms apply to all users. Organizers additionally accept the Organizer Terms with the data processing agreement.",
            "Users' own terms do not apply, even if we do not expressly object to them.",
        ),
        _s(
            "2. The service",
            "EventFaces lets attendees of an event find the event's photos they appear in with a selfie search, view them and download them. Where the organizer allows it, attendees can add their own photos.",
            "The organizer decides which photos are published and who may join an event. There is no entitlement to particular photos or matches. Automatic face matching can miss photos or match the wrong ones; you can mark wrong matches.",
        ),
        _s(
            "3. Eligibility and account",
            "You must be at least {min_age} years old. Each account belongs to one person. Keep your email address up to date, keep sign-in codes, links and passwords secret, and tell us if you suspect your account is being misused.",
        ),
        _s("4. Fees", "Using EventFaces is free for attendees. Paid services for organizers are governed by the Organizer Terms."),
        _s(
            "5. Joining events",
            "You join an event with an access code, a link or an invitation, as the organizer decides. The organizer can end your participation. When an event's access period ends, your access to its photos ends too.",
        ),
        _s(
            "6. Face search",
            "Face search is optional and needs your explicit consent, which you give separately and can withdraw at any time. The details are in the Privacy Notice.",
            "You may only search for yourself. Searching with photos of other people is prohibited.",
        ),
        _s(
            "7. Your photos",
            "Only upload photos you took yourself or hold the necessary rights to. You are responsible for publication being lawful, in particular for depicted people agreeing where the law requires it (Sections 22, 23 KUG, GDPR). Unlawful content is prohibited.",
            "You grant us and the organizer a simple, free right, limited to operating EventFaces, to store your photos, process them (size, format, removing metadata), use them for face search and show them to the event's attendees under these rules. The right ends when you have the photo deleted or delete your account.",
        ),
        _s(
            "8. Prohibited use",
            "In particular, it is prohibited to search for other people; to access the service automatically (scraping, bots) other than through the apps we provide; to circumvent security or access restrictions; to upload malware; or to use the service in any way that infringes the rights of others.",
            "You may use downloaded photos for private purposes. Respect the rights of the people depicted whenever you share them.",
        ),
        _s(
            "9. Reports and point of contact (Digital Services Act)",
            "Report unlawful or unwanted content with “Report” on the photo, on the “Request removal” page (no account needed) or by email to {email}. We review reports diligently and promptly, inform you of our decision and give reasons for any restriction. You can complain about decisions at {email}.",
            "Single point of contact for authorities and users (Art. 11, 12 DSA): {email}. Languages: German, English.",
        ),
        _s(
            "10. Availability and changes to the service",
            "We aim for smooth operation but do not owe uninterrupted availability, in particular during maintenance. We may change features where this is reasonable for you.",
        ),
        _s(
            "11. Term and termination",
            "You can delete your account at any time in the app or on the website. We can terminate the agreement with two weeks' notice, or without notice for good cause (in particular breaches of sections 6 to 8). Afterwards we delete your data as described in the Privacy Notice.",
        ),
        _s(
            "12. Liability",
            "We are liable without limitation for intent and gross negligence, for injury to life, body or health, under the Product Liability Act and to the extent of any guarantee given.",
            "For slight negligence we are liable only for breaching essential contractual obligations, whose fulfilment makes proper performance of the agreement possible in the first place and on whose observance you may regularly rely, and only up to the typical, foreseeable damage. Otherwise liability is excluded. These rules also apply to our staff and agents.",
        ),
        _s(
            "13. Changes to these terms",
            "We may change these terms for an objective reason (such as new features or a change in the law) where this is reasonable for you. We show you the new version before you continue using the service; it applies only once you accept it. If you don't, you can't continue using the service, but you can always delete your account.",
        ),
        _s(
            "14. Final provisions",
            "German law applies, excluding the UN Convention on Contracts for the International Sale of Goods. For consumers, this choice of law applies only insofar as it does not deprive them of the protection of mandatory provisions of the country of their habitual residence.",
            "If the user is a merchant, a legal entity under public law or a special fund under public law, the place of jurisdiction is our registered office.",
            "We are neither willing nor obliged to take part in dispute resolution proceedings before a consumer arbitration board.",
            "The German version is binding; the English version is for information only. If individual provisions are invalid, the rest of the agreement remains valid (Section 306 BGB).",
        ),
    ),
)

# --- Organizer Terms with the data processing agreement ----------------------------------------

_DPA_DE = (
    _s(
        "Anlage: Auftragsverarbeitungsvertrag (Art. 28 DSGVO) – 1. Gegenstand und Dauer",
        "Wir verarbeiten personenbezogene Daten in den Veranstaltungsfotos im Auftrag des Veranstalters (Verantwortlicher), um den Teilnehmenden das Finden ihrer Fotos zu ermöglichen. Die Verarbeitung dauert so lange wie der Vertrag zuzüglich der Löschfristen nach Ziffer 9 dieser Anlage.",
    ),
    _s(
        "2. Art und Zweck der Verarbeitung",
        "Speichern der Fotos; Umwandeln und Entfernen von Metadaten (z. B. Standort); Erkennen von Gesichtern und Erstellen von Gesichtsvorlagen; Abgleich mit Suchen von Teilnehmenden, die eingewilligt haben; Bereitstellen der Fotos an berechtigte Teilnehmende; Unterstützung der Moderation; Löschen.",
    ),
    _s(
        "3. Art der Daten und Betroffene",
        "Daten: Fotos und darauf abgebildete Personen, Gesichtsvorlagen (biometrische Daten, Art. 9 DSGVO), technische Foto-Metadaten, Dateikennungen aus Google Drive. Betroffene: Personen, die auf den Veranstaltungsfotos abgebildet sind (Teilnehmende, Personal, sonstige Personen).",
    ),
    _s(
        "4. Weisungen",
        "Wir verarbeiten die Daten nur auf dokumentierte Weisung des Veranstalters. Weisungen sind dieser Vertrag sowie die Einstellungen, die der Veranstalter in EventFaces vornimmt (Zugang, Moderation, Aufbewahrung, Löschung). Halten wir eine Weisung für rechtswidrig, teilen wir das unverzüglich mit.",
    ),
    _s("5. Vertraulichkeit", "Alle Personen, die Zugriff auf die Daten haben, sind zur Vertraulichkeit verpflichtet."),
    _s(
        "6. Technische und organisatorische Maßnahmen (Art. 32 DSGVO)",
        "Hosting in Rechenzentren in Deutschland; Verschlüsselung bei der Übertragung (TLS); privater Speicher, Fotos werden nur über autorisierungsgeprüfte Schnittstellen ausgeliefert; Trennung der Daten je Veranstaltung, auch der Gesichtsvorlagen; Zugriff nach dem Prinzip der minimalen Rechte; automatische Löschung der Gesichtsvorlagen am Ende des Zugangszeitraums; Protokollierung und Begrenzung von Zugriffen; Datensicherungen; regelmäßige Sicherheitstests. Wir dürfen die Maßnahmen weiterentwickeln, solange das Schutzniveau nicht sinkt.",
    ),
    _s(
        "7. Unterauftragsverarbeiter",
        "Der Veranstalter genehmigt allgemein den Einsatz von Unterauftragsverarbeitern. Derzeit: {hosting_provider} (Hosting) und {storage_provider} (Speicher). Über geplante Änderungen informieren wir mindestens 30 Tage vorher; der Veranstalter kann aus wichtigem datenschutzrechtlichem Grund widersprechen. Wir verpflichten Unterauftragsverarbeiter vertraglich auf gleichwertige Pflichten. Übermittlungen in Drittländer erfolgen nur unter den Voraussetzungen der Art. 44 ff. DSGVO.",
    ),
    _s(
        "8. Unterstützung, Meldungen, Nachweise",
        "Wir unterstützen den Veranstalter bei Anfragen Betroffener (z. B. leiten wir Entfernungsanfragen weiter), bei Datenschutz-Folgenabschätzungen und bei Meldepflichten. Verletzungen des Schutzes personenbezogener Daten melden wir unverzüglich, nachdem sie uns bekannt werden. Wir stellen die zum Nachweis nötigen Informationen bereit und ermöglichen Überprüfungen nach angemessener Vorankündigung.",
    ),
    _s(
        "9. Löschung und Rückgabe",
        "Gesichtsvorlagen löschen wir automatisch am Ende des Zugangszeitraums. Fotos löschen wir nach der Einstellung des Veranstalters, spätestens 30 Tage nach Vertragsende; aus Datensicherungen werden sie innerhalb von höchstens 30 weiteren Tagen entfernt. Die Originale verbleiben beim Veranstalter (z. B. in dessen Google Drive); eine gesonderte Rückgabe ist daher nicht erforderlich.",
    ),
)

_DPA_EN = (
    _s(
        "Annex: Data processing agreement (Art. 28 GDPR) – 1. Subject and duration",
        "We process personal data in the event photos on behalf of the organizer (the controller) so that attendees can find their photos. Processing lasts as long as the agreement plus the deletion periods in section 9 of this annex.",
    ),
    _s(
        "2. Nature and purpose",
        "Storing the photos; converting them and removing metadata (such as location); detecting faces and creating face templates; matching them with searches by attendees who consented; delivering photos to authorized attendees; supporting moderation; deletion.",
    ),
    _s(
        "3. Types of data and data subjects",
        "Data: photos and the people depicted in them, face templates (biometric data, Art. 9 GDPR), technical photo metadata, Google Drive file identifiers. Data subjects: people depicted in the event photos (attendees, staff, others).",
    ),
    _s(
        "4. Instructions",
        "We process the data only on the organizer's documented instructions. Instructions are this agreement and the settings the organizer makes in EventFaces (access, moderation, retention, deletion). If we consider an instruction unlawful, we say so without delay.",
    ),
    _s("5. Confidentiality", "Everyone with access to the data is bound to confidentiality."),
    _s(
        "6. Technical and organizational measures (Art. 32 GDPR)",
        "Hosting in data centres in Germany; encryption in transit (TLS); private storage, with photos delivered only through authorization-checked interfaces; separation of data per event, including face templates; least-privilege access; automatic deletion of face templates at the end of the access period; logging and rate limiting; backups; regular security testing. We may develop these measures further as long as the level of protection does not decrease.",
    ),
    _s(
        "7. Sub-processors",
        "The organizer gives general authorization for sub-processors. Currently: {hosting_provider} (hosting) and {storage_provider} (storage). We announce planned changes at least 30 days in advance; the organizer can object for an important data protection reason. We bind sub-processors to equivalent obligations by contract. Transfers to third countries take place only under the conditions of Art. 44 et seq. GDPR.",
    ),
    _s(
        "8. Assistance, notifications, evidence",
        "We assist the organizer with data subject requests (for example, we forward removal requests), with data protection impact assessments and with notification duties. We report personal data breaches without undue delay after becoming aware of them. We provide the information needed to demonstrate compliance and allow audits after reasonable notice.",
    ),
    _s(
        "9. Deletion and return",
        "We delete face templates automatically at the end of the access period. We delete photos as the organizer sets, at the latest 30 days after the agreement ends; they are removed from backups within at most a further 30 days. The originals remain with the organizer (for example in their Google Drive), so a separate return is not needed.",
    ),
)

_ORGANIZER_DE = LegalText(
    title="Veranstalterbedingungen",
    intro="Diese Bedingungen gelten für Veranstalter, die EventFaces für ihre Veranstaltungen nutzen. Sie ergänzen die Nutzungsbedingungen. Die Anlage enthält den Auftragsverarbeitungsvertrag.",
    sections=(
        _s(
            "1. Vertragsschluss",
            "Der Vertrag zwischen {operator_name} und dem Veranstalter kommt durch eine Einzelbestellung (Angebot und Annahme in Textform) zustande. Vertragsbestandteile sind die Bestellung, diese Bedingungen mit der Anlage und die Nutzungsbedingungen; bei Widersprüchen gilt diese Reihenfolge. Allgemeine Geschäftsbedingungen des Veranstalters gelten nicht.",
        ),
        _s(
            "2. Leistungen",
            "Wir richten die Veranstaltung in EventFaces ein und stellen bereit: Import von Fotos (z. B. aus Google Drive) und Uploads, Gesichtserkennung für die Selfie-Suche, Zugangsverwaltung für Teilnehmende, Moderation und Einstellungen zur Aufbewahrung. Umfang und Grenzen ergeben sich aus der Bestellung.",
        ),
        _s(
            "3. Vergütung",
            "Die Vergütung ergibt sich aus der Bestellung bzw. der dort genannten Preisliste. Gegenüber Unternehmern verstehen sich Preise zuzüglich gesetzlicher Umsatzsteuer. Rechnungen sind innerhalb von 14 Tagen ohne Abzug fällig. Für Teilnehmende ist EventFaces kostenlos.",
        ),
        _s(
            "4. Pflichten des Veranstalters zu Fotos und Rechtsgrundlagen",
            "Der Veranstalter ist Verantwortlicher für die Veranstaltungsfotos. Er stellt sicher, dass die Fotos rechtmäßig aufgenommen und veröffentlicht werden (DSGVO, §§ 22, 23 KUG), und informiert die Teilnehmenden vor der Veranstaltung über das Fotografieren und über EventFaces, einschließlich der Informationen nach Art. 13, 14 DSGVO.",
            "Gesichtsvorlagen sind biometrische Daten (Art. 9 DSGVO). Der Veranstalter stellt eine Rechtsgrundlage für die Gesichtserkennung auf den Fotos sicher, in der Regel die ausdrückliche Einwilligung der abgebildeten Personen (etwa bei der Anmeldung), und bietet eine einfache Möglichkeit, nicht erfasst zu werden. Widersprüche und Entfernungsanfragen bearbeitet er unverzüglich.",
            "Fotos von Personen unter {min_age} Jahren lädt der Veranstalter nur mit Einwilligung der Sorgeberechtigten hoch. Fotos aus sensiblen Zusammenhängen (z. B. Gesundheit, Religion) gehören nicht in EventFaces.",
        ),
        _s(
            "5. Rechte an Inhalten",
            "Der Veranstalter versichert, die nötigen Rechte an den Fotos zu besitzen, und räumt uns die für die Leistungen nötigen einfachen Nutzungsrechte ein. Ist der Veranstalter Unternehmer, stellt er uns von Ansprüchen Dritter frei, die auf rechtswidrig eingestellten Fotos beruhen, einschließlich angemessener Kosten der Rechtsverteidigung.",
        ),
        _s(
            "6. Moderation und rechtswidrige Inhalte",
            "Der Veranstalter prüft Uploads von Teilnehmenden, bevor er sie freigibt. Wir dürfen rechtswidrige Inhalte sperren oder entfernen (Digital Services Act) und informieren den Veranstalter darüber.",
        ),
        _s(
            "7. Datenverarbeitung",
            "Die Verarbeitung personenbezogener Daten in den Veranstaltungsfotos einschließlich der Gesichtsvorlagen erfolgt im Auftrag des Veranstalters nach der Anlage. Konten der Teilnehmenden, die Selfie-Suche mit ihrer Einwilligung und Sicherheitsprotokolle verarbeiten wir in eigener Verantwortung (siehe Datenschutzerklärung).",
        ),
        _s(
            "8. Verfügbarkeit",
            "Ziel-Verfügbarkeiten und Wartungsfenster ergeben sich aus der Bestellung. Ohne Vereinbarung gilt Ziffer 10 der Nutzungsbedingungen.",
        ),
        _s(
            "9. Haftung",
            "Es gilt Ziffer 12 der Nutzungsbedingungen. Gegenüber Unternehmern ist die Haftung bei leichter Fahrlässigkeit zusätzlich je Schadensfall auf die in den vorangegangenen zwölf Monaten gezahlte Vergütung begrenzt. Für Datenverlust haften wir nur in Höhe des Aufwands, der bei ordnungsgemäßer Datensicherung durch den Veranstalter für die Wiederherstellung angefallen wäre.",
        ),
        _s(
            "10. Laufzeit und Kündigung",
            "Laufzeit und Kündigungsfristen ergeben sich aus der Bestellung. Das Recht zur fristlosen Kündigung aus wichtigem Grund bleibt unberührt. Nach Vertragsende werden die Daten nach Ziffer 9 der Anlage gelöscht.",
        ),
        _s(
            "11. Widerrufsrecht für Verbraucher",
            "Ist der Veranstalter Verbraucher, hat er das Recht, binnen vierzehn Tagen ohne Angabe von Gründen diesen Vertrag zu widerrufen. Die Widerrufsfrist beträgt vierzehn Tage ab dem Tag des Vertragsschlusses. Um das Widerrufsrecht auszuüben, ist uns ({operator_name}, {operator_address}, {email}) mittels einer eindeutigen Erklärung (z. B. Brief oder E-Mail) der Entschluss mitzuteilen, diesen Vertrag zu widerrufen. Zur Wahrung der Frist reicht die rechtzeitige Absendung.",
            "Folgen des Widerrufs: Wir erstatten alle erhaltenen Zahlungen unverzüglich, spätestens binnen vierzehn Tagen ab Eingang des Widerrufs, über dasselbe Zahlungsmittel. Hat der Veranstalter verlangt, dass die Dienstleistung während der Widerrufsfrist beginnt, zahlt er einen angemessenen Betrag für den bis zum Widerruf erbrachten Anteil. Das Widerrufsrecht erlischt, wenn wir die Dienstleistung vollständig erbracht haben und mit der Ausführung erst begonnen haben, nachdem der Veranstalter ausdrücklich zugestimmt und bestätigt hat, dass er sein Widerrufsrecht bei vollständiger Vertragserfüllung verliert.",
        ),
        _s(
            "12. Schlussbestimmungen",
            "Es gilt Ziffer 14 der Nutzungsbedingungen. Änderungen dieser Bedingungen werden dem Veranstalter vor der weiteren Nutzung angezeigt und gelten erst mit seiner Zustimmung.",
        ),
        *_DPA_DE,
    ),
)

_ORGANIZER_EN = LegalText(
    title="Organizer Terms",
    intro="These terms apply to organizers who use EventFaces for their events. They supplement the Terms of Use. The annex contains the data processing agreement. The German version is binding; this English version is a translation for your convenience.",
    sections=(
        _s(
            "1. Conclusion of the agreement",
            "The agreement between {operator_name} and the organizer is concluded by an individual order (offer and acceptance in text form). It consists of the order, these terms with the annex and the Terms of Use; in case of conflict they apply in this order. The organizer's general terms and conditions do not apply.",
        ),
        _s(
            "2. Services",
            "We set up the event in EventFaces and provide: photo import (for example from Google Drive) and uploads, face recognition for the selfie search, access management for attendees, moderation and retention settings. Scope and limits follow from the order.",
        ),
        _s(
            "3. Fees",
            "Fees follow from the order or the price list it refers to. For businesses, prices are exclusive of statutory VAT. Invoices are due within 14 days without deduction. EventFaces is free for attendees.",
        ),
        _s(
            "4. Organizer's obligations regarding photos and legal bases",
            "The organizer is the controller for the event photos. The organizer ensures that the photos are taken and published lawfully (GDPR, Sections 22, 23 KUG) and informs attendees before the event about photography and about EventFaces, including the information under Art. 13, 14 GDPR.",
            "Face templates are biometric data (Art. 9 GDPR). The organizer ensures a legal basis for face recognition in the photos, usually the explicit consent of the people depicted (for example at registration), and offers an easy way not to be included. The organizer handles objections and removal requests without delay.",
            "The organizer uploads photos of people under {min_age} only with the consent of their legal guardians. Photos from sensitive contexts (such as health or religion) do not belong in EventFaces.",
        ),
        _s(
            "5. Rights to content",
            "The organizer warrants holding the necessary rights to the photos and grants us the simple rights of use needed for the services. If the organizer is a business, it indemnifies us against third-party claims based on unlawfully posted photos, including reasonable legal defence costs.",
        ),
        _s(
            "6. Moderation and unlawful content",
            "The organizer reviews attendees' uploads before approving them. We may block or remove unlawful content (Digital Services Act) and inform the organizer.",
        ),
        _s(
            "7. Data processing",
            "Personal data in the event photos, including face templates, is processed on the organizer's behalf under the annex. Attendee accounts, the selfie search with their consent and security logs are processed under our own responsibility (see the Privacy Notice).",
        ),
        _s("8. Availability", "Target availability and maintenance windows follow from the order. Without an agreement, section 10 of the Terms of Use applies."),
        _s(
            "9. Liability",
            "Section 12 of the Terms of Use applies. Towards businesses, liability for slight negligence is additionally limited per incident to the fees paid in the preceding twelve months. For data loss we are liable only for the effort that restoring it would have required had the organizer kept proper backups.",
        ),
        _s(
            "10. Term and termination",
            "Term and notice periods follow from the order. The right to terminate without notice for good cause is unaffected. After the agreement ends, the data is deleted under section 9 of the annex.",
        ),
        _s(
            "11. Right of withdrawal for consumers",
            "If the organizer is a consumer, they have the right to withdraw from this agreement within fourteen days without giving any reason. The withdrawal period is fourteen days from the day the agreement is concluded. To exercise the right, the organizer must inform us ({operator_name}, {operator_address}, {email}) of the decision to withdraw by an unequivocal statement (for example a letter or email). Sending it before the period expires is sufficient.",
            "Effects of withdrawal: we refund all payments received without undue delay and at the latest within fourteen days of receiving the withdrawal, using the same means of payment. If the organizer requested that the service begin during the withdrawal period, they pay a reasonable amount for the part provided up to the withdrawal. The right of withdrawal expires once we have fully provided the service, if we only began after the organizer expressly agreed and acknowledged losing the right of withdrawal on full performance.",
        ),
        _s(
            "12. Final provisions",
            "Section 14 of the Terms of Use applies. Changes to these terms are shown to the organizer before further use and apply only once the organizer accepts them.",
        ),
        *_DPA_EN,
    ),
)

# --- Privacy Notice -------------------------------------------------------------------------

_PRIVACY_DE = LegalText(
    title="Datenschutzerklärung",
    intro="Hier erfahren Sie, welche personenbezogenen Daten EventFaces verarbeitet, warum, wie lange und welche Rechte Sie haben. Sie gilt für die Website und die iOS-App.",
    sections=(
        _s(
            "1. Verantwortlicher und Datenschutzbeauftragter",
            "Verantwortlich ist {operator_name}, {operator_address}, E-Mail: {email}, Telefon: {phone}. Unseren Datenschutzbeauftragten erreichen Sie unter {dpo_contact}.",
        ),
        _s(
            "2. Wer wofür verantwortlich ist",
            "Für Ihr Konto, die Selfie-Suche, die App und die Sicherheit des Dienstes sind wir verantwortlich. Für die Veranstaltungsfotos und die daraus erstellten Gesichtsvorlagen ist der jeweilige Veranstalter verantwortlich; wir verarbeiten diese Daten in seinem Auftrag (Art. 28 DSGVO). Anfragen dazu können Sie an den Veranstalter oder an uns richten; wir leiten sie weiter.",
        ),
        _s(
            "3. Konto und Anmeldung",
            "Wir verarbeiten Ihre E-Mail-Adresse, gegebenenfalls einen Passwort-Hash (nie das Passwort selbst), Ihre Rolle, Ihre Veranstaltungen, die Zustimmung zu den Nutzungsbedingungen (Fassung und Zeitpunkt) und Ihre Darstellungseinstellung, um Ihnen den Dienst bereitzustellen (Art. 6 Abs. 1 lit. b DSGVO). Anmeldecodes und -links gelten zehn Minuten und sind nur einmal verwendbar.",
        ),
        _s(
            "4. Selfie-Suche (biometrische Daten)",
            "Wenn Sie suchen, wandeln wir das Gesicht auf Ihren drei Selfies in eine numerische Gesichtsvorlage um und vergleichen sie nur mit den Gesichtern auf den Fotos dieser Veranstaltung. Gesichtsvorlagen sind biometrische Daten; wir verarbeiten sie nur mit Ihrer ausdrücklichen Einwilligung (Art. 9 Abs. 2 lit. a, Art. 6 Abs. 1 lit. a DSGVO), die Sie jederzeit in den Einstellungen widerrufen können. Der Widerruf berührt die Rechtmäßigkeit bisheriger Suchen nicht.",
            "Ihre Selfies und deren Gesichtsvorlage werden nur im Arbeitsspeicher verarbeitet und nie gespeichert, auch nicht in der App. Sind viele Suchen gleichzeitig aktiv, warten sie höchstens 15 Minuten im Arbeitsspeicher. Gespeichert wird nur, welche Fotos zu Ihnen passen ({grant_days} Tage oder bis der Zugang zur Veranstaltung endet), sowie Ihre Rückmeldungen dazu („Das bin ich“ / „Nicht ich“).",
            "Die Suche ist automatisiert, trifft aber keine Entscheidungen mit rechtlicher Wirkung (Art. 22 DSGVO): Sie zeigt Ihnen nur mögliche Fotos, die Sie korrigieren können.",
            "Hinweis auf neue Fotos: Nach einer Suche merken wir uns, dass und wann Sie diese Veranstaltung durchsucht haben (keine Selfies, keine Gesichtsvorlage). Kommen danach neue Fotos mit Gesichtern hinzu, schicken wir Ihnen höchstens einmal am Tag je Veranstaltung eine E-Mail und, wenn Sie Mitteilungen erlauben, eine Push-Mitteilung, damit Sie erneut suchen können; beide nennen keine Anzahlen und zeigen keine Fotos (Art. 6 Abs. 1 lit. b und f DSGVO). Sie können das je Veranstaltung, in den Einstellungen oder über den Link in jeder E-Mail abschalten; auch der Veranstalter kann es abschalten. Veranstalter sehen nie, wer gesucht hat.",
        ),
        _s(
            "5. Veranstaltungsfotos (Information nach Art. 14 DSGVO)",
            "Fotos stammen vom Veranstalter (etwa aus dessen Google Drive) oder von Teilnehmenden. Wir entfernen Standort- und Kameradaten, erkennen Gesichter und erstellen Gesichtsvorlagen, damit Teilnehmende ihre Fotos finden. Andere Teilnehmende sehen ein Foto nur, wenn sie selbst darauf zu sehen sind. Die Gesichtsvorlagen werden am Ende des Zugangszeitraums automatisch gelöscht, die Fotos nach der Einstellung des Veranstalters.",
            "Sind Sie auf einem Foto zu sehen und möchten das nicht, nutzen Sie die Seite „Entfernung anfragen“, auch ohne Konto. Wir zeigen Ihnen dabei keine Fotos und keine Trefferzahlen, damit niemand nach Fotos anderer Personen suchen kann.",
        ),
        _s(
            "6. Eigene Uploads, Downloads und Meldungen",
            "Fotos, die Sie hochladen, verarbeiten wir zur Bereitstellung des Dienstes (Art. 6 Abs. 1 lit. b DSGVO); der Veranstalter prüft sie vor der Freigabe. Download-Links sind kurzlebig und an Ihr Konto gebunden. Meldungen und Entfernungsanfragen verarbeiten wir zur Erfüllung rechtlicher Pflichten und zum Schutz der Betroffenen (Art. 6 Abs. 1 lit. c und f DSGVO).",
        ),
        _s(
            "7. iOS-App",
            "Für jede angemeldete Installation speichern wir einen Geräteeintrag (Gerätename, App-Version, einen öffentlichen Schlüssel des Geräts, Zeitpunkte), damit eine Anmeldung nur auf diesem Gerät gilt und Sie Geräte abmelden können (Art. 6 Abs. 1 lit. b und f DSGVO). Wenn Sie Mitteilungen erlauben, speichern wir das Push-Token von Apple; Mitteilungen enthalten keine Namen, Fotos oder Anzahlen.",
            "Mit Apple App Attest prüfen wir, ob Anfragen von einer echten EventFaces-App kommen (Art. 6 Abs. 1 lit. f DSGVO, Schutz vor Missbrauch). Die Kamera nutzt die App nur für QR-Codes und Selfies, die Fotomediathek nur zum Hinzufügen, wenn Sie „Sichern“ tippen. Face ID für die App-Sperre prüft iOS auf dem Gerät; wir erhalten dabei keine Daten. Die App enthält keine Analyse- oder Werbedienste.",
        ),
        _s(
            "8. Server-Protokolle und Sicherheit",
            "Beim Aufruf verarbeiten unsere Server technisch notwendige Daten (IP-Adresse, Zeitpunkt, aufgerufene Adresse, Browser-Kennung), um den Dienst auszuliefern und Angriffe abzuwehren (Art. 6 Abs. 1 lit. f DSGVO); sie werden nach höchstens 14 Tagen gelöscht. Suchen protokollieren wir ohne Selfie (wer, wann, Anzahl der Treffer) zum Schutz vor Missbrauch für 365 Tage; bei Kontolöschung werden die Einträge anonymisiert.",
        ),
        _s(
            "9. Cookies und Speicherung auf Ihrem Gerät",
            "Die Website setzt ausschließlich technisch unbedingt erforderliche Cookies. Rechtsgrundlage für das Speichern auf Ihrem Gerät ist § 25 Abs. 2 Nr. 2 TDDDG, für die damit verbundene Verarbeitung Art. 6 Abs. 1 lit. b und f DSGVO. Eine Einwilligung ist dafür nicht erforderlich; deshalb zeigen wir kein Cookie-Banner. Alle Cookies sind Erstanbieter-Cookies von EventFaces; Cookies Dritter gibt es nicht.",
            "ef_access – hält Sie angemeldet (Anmelde-Token, nicht per JavaScript lesbar). Speicherdauer: {access_minutes} Minuten.",
            "ef_refresh – erneuert die Anmeldung, damit Sie angemeldet bleiben (nicht per JavaScript lesbar). Speicherdauer: {refresh_days} Tage oder bis zur Abmeldung.",
            "ef_csrf – schützt Formulare vor Cross-Site-Request-Forgery. Speicherdauer: bis Sie den Browser schließen.",
            "ef_theme – merkt sich Ihre gewählte Darstellung (System, Hell, Dunkel). Speicherdauer: 1 Jahr.",
            "Wir verwenden keine Cookies oder ähnlichen Techniken für Analyse, Tracking, Werbung oder Social Media, und keine Fingerprinting-Verfahren. Sie können Cookies in Ihrem Browser löschen oder blockieren; ohne die Anmelde-Cookies ist eine Anmeldung jedoch nicht möglich.",
            "Die iOS-App verwendet keine Cookies. Sie speichert Anmeldedaten nur im Schlüsselbund des Geräts (nur auf diesem Gerät, ohne iCloud-Synchronisation), Ihre Einstellungen (gesehene Einführung, Darstellung, App-Sperre) auf dem Gerät sowie heruntergeladene Fotos in einem geschützten Zwischenspeicher, der nicht in Backups landet und beim Abmelden geleert wird.",
        ),
        _s(
            "10. Empfänger und Auftragsverarbeiter",
            "Hosting: {hosting_provider}. Speicher: {storage_provider}. E-Mail-Versand: {email_provider}. Für Push-Mitteilungen und App Attest: Apple. Für den Import aus Google Drive, wenn ein Veranstalter einen Ordner verknüpft: Google. Veranstalter sehen, wer ihrer Veranstaltung angehört, und die Uploads, aber nie Ihre Selfies oder Suchen. Wir verkaufen keine Daten.",
            "Soweit Apple, Google oder Cloudflare Daten in den USA verarbeiten, stützt sich die Übermittlung auf den Angemessenheitsbeschluss zum EU-US Data Privacy Framework (Art. 45 DSGVO) oder auf Standardvertragsklauseln (Art. 46 DSGVO).",
        ),
        _s(
            "11. Speicherdauer",
            "Selfies und deren Gesichtsvorlage: nicht gespeichert. Gesichtsvorlagen der Personen auf Veranstaltungsfotos: bis zum Ende des Zugangszeitraums. Ihre Treffer: {grant_days} Tage oder bis zum Ende des Zugangs, gelöscht beim Widerruf der Einwilligung. Veranstaltungsfotos: nach Festlegung des Veranstalters. Suchprotokoll: 365 Tage. Konto: bis Sie es löschen; nie bestätigte Konten nach 14 Tagen. Entfernungsanfragen: unbestätigt 48 Stunden, abgeschlossen 180 Tage. Zustimmungen zu Nutzungsbedingungen: solange Ihr Konto besteht. Vermerk für Hinweise auf neue Fotos (wann Sie eine Veranstaltung durchsucht haben): bis zum Ende des Zugangszeitraums, gelöscht beim Widerruf der Einwilligung oder mit Ihrem Konto.",
        ),
        _s(
            "12. Ihre Rechte",
            "Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung und Datenübertragbarkeit (Art. 15 bis 20 DSGVO) sowie das Recht, der Verarbeitung auf Grundlage berechtigter Interessen zu widersprechen (Art. 21 DSGVO). Einwilligungen können Sie jederzeit mit Wirkung für die Zukunft widerrufen (Art. 7 Abs. 3 DSGVO). Ihr Konto und Ihre Daten löschen Sie selbst in den Einstellungen; für alles andere schreiben Sie an {email}.",
            "Sie können sich bei einer Datenschutz-Aufsichtsbehörde beschweren, insbesondere bei der für uns zuständigen: {supervisory_authority}.",
        ),
        _s(
            "13. Pflicht zur Bereitstellung und Mindestalter",
            "Ihre E-Mail-Adresse brauchen wir für das Konto; ohne sie ist die Nutzung nicht möglich. Die Selfie-Suche ist freiwillig. EventFaces richtet sich an Personen ab {min_age} Jahren.",
        ),
        _s(
            "14. Sicherheit und Änderungen",
            "Wir schützen Daten unter anderem durch Hosting in Deutschland, Verschlüsselung bei der Übertragung, getrennte Speicherung je Veranstaltung und regelmäßige Sicherheitstests. Diese Erklärung passen wir an, wenn sich der Dienst oder die Rechtslage ändert; maßgeblich ist die Fassung mit dem oben angegebenen Datum.",
        ),
    ),
)

_PRIVACY_EN = LegalText(
    title="Privacy Notice",
    intro="This notice explains which personal data EventFaces processes, why, for how long and which rights you have. It covers the website and the iOS app. The German version is binding.",
    sections=(
        _s(
            "1. Controller and data protection officer",
            "The controller is {operator_name}, {operator_address}, email: {email}, phone: {phone}. You can reach our data protection officer at {dpo_contact}.",
        ),
        _s(
            "2. Who is responsible for what",
            "We are responsible for your account, the selfie search, the app and the security of the service. The organizer of each event is responsible for the event photos and the face templates created from them; we process that data on their behalf (Art. 28 GDPR). You can send requests about it to the organizer or to us; we forward them.",
        ),
        _s(
            "3. Account and sign-in",
            "We process your email address, a password hash if you set a password (never the password itself), your role, your events, your acceptance of the Terms of Use (version and time) and your appearance setting, to provide the service (Art. 6(1)(b) GDPR). Sign-in codes and links are valid for ten minutes and can be used once.",
        ),
        _s(
            "4. Selfie search (biometric data)",
            "When you search, we turn the face in your three selfies into a numeric face template and compare it only with the faces in that event's photos. Face templates are biometric data; we process them only with your explicit consent (Art. 9(2)(a), Art. 6(1)(a) GDPR), which you can withdraw at any time in Settings. Withdrawal does not affect the lawfulness of earlier searches.",
            "Your selfies and their face template are processed in memory only and never stored, not in the app either. If many searches run at once, they wait in memory for at most 15 minutes. We store only which photos matched you ({grant_days} days, or until the event's access ends) and your feedback on them (“This is me” / “Not me”).",
            "The search is automated but makes no decisions with legal effect (Art. 22 GDPR): it only shows you possible photos, which you can correct.",
            "New-photo alerts: after a search we remember that and when you searched this event (no selfies, no face template). If photos with faces are added later, we send you at most one email a day per event and, if you allow notifications, a push notification so you can search again; neither says how many or shows any photo (Art. 6(1)(b) and (f) GDPR). You can turn this off per event, in Settings or with the link in each email; the organizer can also turn it off. Organizers never see who searched.",
        ),
        _s(
            "5. Event photos (information under Art. 14 GDPR)",
            "Photos come from the organizer (for example from their Google Drive) or from attendees. We remove location and camera data, detect faces and create face templates so attendees can find their photos. Other attendees only see a photo if they appear in it themselves. Face templates are deleted automatically when the access period ends; photos as the organizer sets.",
            "If you appear in a photo and don't want to, use the “Request removal” page, no account needed. We show you no photos and no match counts there, so nobody can search for other people's photos.",
        ),
        _s(
            "6. Your uploads, downloads and reports",
            "We process photos you upload to provide the service (Art. 6(1)(b) GDPR); the organizer reviews them before approval. Download links are short-lived and bound to your account. We process reports and removal requests to meet legal obligations and to protect the people concerned (Art. 6(1)(c) and (f) GDPR).",
        ),
        _s(
            "7. iOS app",
            "For each signed-in installation we store a device record (device name, app version, a public key of the device, timestamps) so that a sign-in only works on that device and you can sign devices out (Art. 6(1)(b) and (f) GDPR). If you allow notifications, we store Apple's push token; notifications contain no names, photos or counts.",
            "We use Apple App Attest to check that requests come from a genuine EventFaces app (Art. 6(1)(f) GDPR, protection against misuse). The app uses the camera only for QR codes and selfies, and the photo library only to add photos when you tap “Save”. iOS checks Face ID for the app lock on the device; we receive no data from it. The app contains no analytics or advertising services.",
        ),
        _s(
            "8. Server logs and security",
            "When you visit, our servers process technically necessary data (IP address, time, requested address, browser identifier) to deliver the service and fend off attacks (Art. 6(1)(f) GDPR); it is deleted after at most 14 days. We log searches without the selfie (who, when, number of matches) for 365 days to prevent misuse; the entries are anonymized when you delete your account.",
        ),
        _s(
            "9. Cookies and storage on your device",
            "The website sets only strictly necessary cookies. The legal basis for storing them on your device is Section 25(2) no. 2 TDDDG, and for the related processing Art. 6(1)(b) and (f) GDPR. No consent is needed for them, which is why we show no cookie banner. All cookies are first-party cookies of EventFaces; there are no third-party cookies.",
            "ef_access – keeps you signed in (sign-in token, not readable by JavaScript). Lifetime: {access_minutes} minutes.",
            "ef_refresh – renews your sign-in so you stay signed in (not readable by JavaScript). Lifetime: {refresh_days} days or until you sign out.",
            "ef_csrf – protects forms against cross-site request forgery. Lifetime: until you close the browser.",
            "ef_theme – remembers your chosen appearance (System, Light, Dark). Lifetime: 1 year.",
            "We use no cookies or similar technologies for analytics, tracking, advertising or social media, and no fingerprinting. You can delete or block cookies in your browser; without the sign-in cookies, however, you can't sign in.",
            "The iOS app uses no cookies. It stores sign-in data only in the device's Keychain (this device only, no iCloud sync), your settings (onboarding seen, appearance, app lock) on the device, and downloaded photos in a protected cache that is excluded from backups and cleared when you sign out.",
        ),
        _s(
            "10. Recipients and processors",
            "Hosting: {hosting_provider}. Storage: {storage_provider}. Email delivery: {email_provider}. Push notifications and App Attest: Apple. Importing from Google Drive when an organizer links a folder: Google. Organizers see who belongs to their event and the uploads, but never your selfies or searches. We do not sell data.",
            "Where Apple, Google or Cloudflare process data in the USA, transfers rely on the adequacy decision for the EU-US Data Privacy Framework (Art. 45 GDPR) or on standard contractual clauses (Art. 46 GDPR).",
        ),
        _s(
            "11. Retention",
            "Selfies and their face template: not stored. Face templates of people in event photos: until the access period ends. Your matches: {grant_days} days or until access ends, deleted when you withdraw consent. Event photos: as the organizer sets. Search log: 365 days. Account: until you delete it; never-verified accounts after 14 days. Removal requests: unconfirmed 48 hours, completed 180 days. Acceptances of the Terms of Use: as long as your account exists. Record for new-photo alerts (when you searched an event): until the access period ends, deleted when you withdraw consent or with your account.",
        ),
        _s(
            "12. Your rights",
            "You have the right of access, rectification, erasure, restriction of processing and data portability (Art. 15 to 20 GDPR), and the right to object to processing based on legitimate interests (Art. 21 GDPR). You can withdraw consent at any time with effect for the future (Art. 7(3) GDPR). You can delete your account and data yourself in Settings; for anything else, write to {email}.",
            "You can complain to a data protection supervisory authority, in particular the one responsible for us: {supervisory_authority}.",
        ),
        _s(
            "13. Obligation to provide data and minimum age",
            "We need your email address for the account; without it you can't use the service. The selfie search is optional. EventFaces is intended for people aged {min_age} and over.",
        ),
        _s(
            "14. Security and changes",
            "We protect data by hosting in Germany, encryption in transit, separate storage per event and regular security testing, among other measures. We update this notice when the service or the law changes; the version with the date shown above applies.",
        ),
    ),
)

# --- Impressum ------------------------------------------------------------------------------

_IMPRINT_DE = LegalText(
    title="Impressum",
    intro="Angaben gemäß § 5 Digitale-Dienste-Gesetz (DDG).",
    sections=(
        _s("Anbieter", "{operator_name}", "{operator_address}"),
        _s("Vertreten durch", "{representative}"),
        _s("Kontakt", "Telefon: {phone}", "E-Mail: {email}"),
        _s("Registereintrag", "[register]"),
        _s("Umsatzsteuer-Identifikationsnummer", "USt-IdNr. gemäß § 27a Umsatzsteuergesetz: [vat_id]"),
        _s("Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV", "{representative}, {operator_address}"),
        _s(
            "Zentrale Kontaktstelle nach dem Digital Services Act",
            "Für Behörden, die Europäische Kommission und Nutzerinnen und Nutzer (Art. 11, 12 DSA): {email}. Sprachen: Deutsch, Englisch.",
        ),
        _s(
            "Verbraucherstreitbeilegung",
            "Wir sind nicht bereit und nicht verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.",
        ),
    ),
)

_IMPRINT_EN = LegalText(
    title="Legal notice (Impressum)",
    intro="Information under Section 5 of the German Digital Services Act (DDG). The German version is binding.",
    sections=(
        _s("Provider", "{operator_name}", "{operator_address}"),
        _s("Represented by", "{representative}"),
        _s("Contact", "Phone: {phone}", "Email: {email}"),
        _s("Register entry", "[register]"),
        _s("VAT identification number", "VAT ID under Section 27a of the German VAT Act: [vat_id]"),
        _s("Responsible for content under Section 18(2) MStV", "{representative}, {operator_address}"),
        _s(
            "Single point of contact under the Digital Services Act",
            "For authorities, the European Commission and users (Art. 11, 12 DSA): {email}. Languages: German, English.",
        ),
        _s(
            "Consumer dispute resolution",
            "We are neither willing nor obliged to take part in dispute resolution proceedings before a consumer arbitration board.",
        ),
    ),
)

_TEXTS: dict[Document, dict[str, LegalText]] = {
    "terms": {"de": _TERMS_DE, "en": _TERMS_EN},
    "organizer-terms": {"de": _ORGANIZER_DE, "en": _ORGANIZER_EN},
    "privacy": {"de": _PRIVACY_DE, "en": _PRIVACY_EN},
    "imprint": {"de": _IMPRINT_DE, "en": _IMPRINT_EN},
}

# Every cookie the web app sets must be listed in the privacy notice's cookie section.
DOCUMENTED_COOKIES = ("ef_access", "ef_refresh", "ef_csrf", "ef_theme")

# --- Rendering ------------------------------------------------------------------------------

REQUIRED_FIELDS = (
    "operator_name",
    "operator_address",
    "representative",
    "email",
    "phone",
    "dpo_contact",
    "supervisory_authority",
    "email_provider",
)


def identity() -> dict[str, str]:
    """The operator's details from settings; empty fields show as visible placeholders."""
    s = get_settings()
    values = {
        "operator_name": s.legal_operator_name,
        "operator_address": ", ".join(p.strip() for p in s.legal_operator_address.replace("\\n", "\n").splitlines() if p.strip()),
        "representative": s.legal_representative,
        "email": s.legal_email,
        "phone": s.legal_phone,
        "register": s.legal_register,
        "vat_id": s.legal_vat_id,
        "dpo_contact": s.legal_dpo_contact,
        "supervisory_authority": s.legal_supervisory_authority,
        "hosting_provider": s.legal_hosting_provider,
        "storage_provider": s.legal_storage_provider,
        "email_provider": s.legal_email_provider,
    }
    return values


def missing_fields() -> list[str]:
    values = identity()
    return [f for f in REQUIRED_FIELDS if not values[f].strip()]


_FIELD = re.compile(r"\{(\w+)\}|\[(\w+)\]")


def _fill(text: str, values: dict[str, str]) -> str | None:
    """Fill {required} and [optional] fields. A paragraph whose optional field is empty is
    dropped (returns None); an empty required field shows as a visible placeholder."""
    out = text
    for match in _FIELD.finditer(text):
        name = match.group(1) or match.group(2)
        value = values.get(name, "").strip()
        if not value:
            if match.group(2):
                return None
            value = f"[{name.replace('_', ' ')}]"
        out = out.replace(match.group(0), value, 1)
    return out


def locale_from(accept_language: str | None) -> str:
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag[:2] in LOCALES:
            return tag[:2]
    return "en"


def render(document: Document, locale: str) -> LegalText:
    text = _TEXTS[document][locale if locale in LOCALES else "en"]
    s = get_settings()
    values = identity() | {
        "min_age": str(MIN_AGE),
        "grant_days": str(s.search_grant_days),
        "access_minutes": str(s.access_token_minutes),
        "refresh_days": str(s.refresh_token_days),
    }
    sections = []
    for section in text.sections:
        paragraphs = tuple(p for p in (_fill(p, values) for p in section.paragraphs) if p)
        if paragraphs:
            sections.append(Section(section.heading, paragraphs))
    return LegalText(title=text.title, intro=_fill(text.intro, values) or "", sections=tuple(sections))


def fingerprint(document: Document) -> str:
    """Hash of every locale's raw text (placeholders unexpanded)."""
    raw = {k: asdict(v) for k, v in sorted(_TEXTS[document].items())}
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


# --- Acceptance -----------------------------------------------------------------------------


def accept(db: "Session", user: "User", document: Document, *, locale: str, channel: str) -> None:
    """Record acceptance of the current version (history row + the user's current version)."""
    from app.models import LegalAcceptance

    if document not in ACCEPTED:
        raise ValueError(document)
    version = VERSIONS[document]
    db.add(LegalAcceptance(user_id=user.id, document=document, version=version, locale=locale if locale in LOCALES else "en", channel=channel))
    if document == "terms":
        user.terms_version = version
    else:
        user.organizer_terms_version = version


def has_current_terms(user: "User") -> bool:
    return user.terms_version == VERSIONS["terms"]


def has_current_organizer_terms(user: "User") -> bool:
    return user.organizer_terms_version == VERSIONS["organizer-terms"]
