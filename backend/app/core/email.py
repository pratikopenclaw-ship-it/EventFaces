import html
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.core.config import get_settings


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str
    reply_to: str | None = None  # e.g. the sender of a contact-form message


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


def _one_line(value: str) -> str:
    """Header values can't span lines: organizer-chosen text (event names) goes into
    subjects, so control characters are flattened instead of failing the send."""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


_URL_RE = re.compile(r'https?://[^\s<>"]+')
_ACCENT = "#0F766E"
_TEXT = "#10231F"
_MUTED = "#586B66"
_BORDER = "#DCE6E3"
_SURFACE = "#F3F7F6"


def _escaped_with_links(text: str) -> str:
    """Escapes plain text for HTML, then turns bare http(s) URLs into links. Operates on
    the ESCAPED text and URL alike (never on raw, unescaped input) so an event name or
    other user-supplied text can't break out of the markup or an href attribute."""
    escaped = html.escape(text)

    def linkify(m: re.Match[str]) -> str:
        url = m.group(0)
        return f'<a href="{url}" style="color:{_ACCENT};text-decoration:underline">{url}</a>'

    # Matching against already-escaped text: "&" in a URL reads as "&amp;" here, which
    # _URL_RE's [^\s<>"] class still accepts, so the link (and its visible text) stays intact.
    return _URL_RE.sub(linkify, escaped)


def _body_html(body: str) -> str:
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    return "".join(f'<p style="margin:0 0 16px">{_escaped_with_links(p).replace(chr(10), "<br>")}</p>' for p in paragraphs)


def render_html(mail: Mail) -> str:
    """A branded HTML alternative alongside the plain-text body every email already sends.
    Light-only (email clients' automatic dark-mode inversion is unreliable; `color-scheme`
    tells the ones that respect it to leave this alone), table-based layout (works in
    clients that don't support modern CSS), and no remote resources (no images/fonts to
    load, so nothing for a client to block and nothing that could act as an open-tracking
    pixel)."""
    operator = get_settings().legal_operator_name
    footer = f"{html.escape(operator)} · " if operator else ""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
</head>
<body style="margin:0;padding:24px;background:{_SURFACE};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="100%" style="max-width:480px" cellpadding="0" cellspacing="0">
<tr><td style="background:{_ACCENT};border-radius:12px 12px 0 0;padding:20px 28px">
<span style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:-0.01em">EventFaces</span>
</td></tr>
<tr><td style="background:#ffffff;border:1px solid {_BORDER};border-top:none;border-radius:0 0 12px 12px;padding:28px;color:{_TEXT};font-size:15px;line-height:1.6">
{_body_html(mail.body)}
</td></tr>
<tr><td style="padding:20px 4px 0;color:{_MUTED};font-size:12px;line-height:1.5">
{footer}This is an automated message from EventFaces.
</td></tr>
</table>
</td></tr></table>
</body>
</html>"""


def build_message(mail: Mail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = get_settings().email_from
    msg["To"] = _one_line(mail.to)
    msg["Subject"] = _one_line(mail.subject)
    if mail.reply_to:
        msg["Reply-To"] = _one_line(mail.reply_to)
    msg.set_content(mail.body)
    msg.add_alternative(render_html(mail), subtype="html")
    return msg


class SmtpMailer:
    def send(self, mail: Mail) -> None:
        s = get_settings()
        msg = build_message(mail)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            if s.smtp_tls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)


_mailer: Mailer = SmtpMailer()


def get_mailer() -> Mailer:
    return _mailer


def set_mailer(mailer: Mailer) -> None:
    """Used by tests to capture outgoing mail."""
    global _mailer  # noqa: PLW0603 - deliberate test-injection hook
    _mailer = mailer
