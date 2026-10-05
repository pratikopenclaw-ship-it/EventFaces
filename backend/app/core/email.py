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


def build_message(mail: Mail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = get_settings().email_from
    msg["To"] = _one_line(mail.to)
    msg["Subject"] = _one_line(mail.subject)
    if mail.reply_to:
        msg["Reply-To"] = _one_line(mail.reply_to)
    msg.set_content(mail.body)
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
