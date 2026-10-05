"""The website's contact form: delivered by email to the operator, never stored."""

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from app.core import rate_limit
from app.core.config import get_settings
from app.core.email import Mail, get_mailer
from app.schemas.contact import ContactIn, ContactOut

router = APIRouter(prefix="/api", tags=["contact"])
log = logging.getLogger(__name__)

TOPICS = {
    "organizer": "Organizing an event",
    "attendee": "Finding my photos",
    "privacy": "Privacy and my data",
    "other": "Something else",
}


def recipient() -> str:
    s = get_settings()
    return s.contact_email or s.legal_email or s.email_from


def contact_mail(body: ContactIn) -> Mail:
    topic = TOPICS[body.topic]
    return Mail(
        to=recipient(),
        subject=f"[EventFaces contact] {topic}: {body.name}",
        body=f"From: {body.name} <{body.email}>\nTopic: {topic}\n\n{body.message}\n\n"
        "(Sent from the contact form on the website. Reply to answer; nothing was stored.)",
        reply_to=str(body.email),
    )


@router.post("/contact", response_model=ContactOut, status_code=status.HTTP_202_ACCEPTED)
async def contact(body: ContactIn, request: Request) -> ContactOut:
    s = get_settings()
    rate_limit.enforce(f"contact:{rate_limit.client_ip(request)}", rate_limit.Limit.parse(s.contact_rate_limit))
    # Per sender too, keyed by a hash: no address is kept, not even in Redis.
    sender = hashlib.sha256(str(body.email).lower().encode()).hexdigest()
    rate_limit.enforce(f"contact-from:{sender}", rate_limit.Limit.parse(s.contact_email_rate_limit))
    if body.website:  # a bot filled the hidden field: look successful, send nothing
        return ContactOut(status="sent")
    try:
        await run_in_threadpool(get_mailer().send, contact_mail(body))
    except Exception as e:
        # The error type only: SMTP errors can carry addresses, and the message stays private.
        log.error("Contact form mail could not be sent: %s", type(e).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Your message couldn't be sent right now. Please try again later or email us.",
            headers={"Retry-After": "60"},
        ) from None
    return ContactOut(status="sent")
