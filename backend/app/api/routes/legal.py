"""Legal documents (Terms, Organizer Terms with the DPA, Privacy Notice, Impressum) and
recording their acceptance. The texts and versions live in services/legal.py."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DB, CurrentUser
from app.schemas.auth import UserOut
from app.schemas.legal import AcceptLegalIn, LegalDocumentOut, LegalSectionOut
from app.services import legal

router = APIRouter(prefix="/api", tags=["legal"])


def channel(request: Request) -> str:
    return "ios" if getattr(request.state, "transport", None) == "mobile" else "web"


@router.get("/legal/{document}", response_model=LegalDocumentOut)
def get_document(document: legal.Document, request: Request, lang: Literal["de", "en"] | None = None) -> LegalDocumentOut:
    """`lang` picks the language; otherwise Accept-Language (German or English)."""
    locale = lang or legal.locale_from(request.headers.get("accept-language"))
    text = legal.render(document, locale)
    return LegalDocumentOut(
        document=document,
        version=legal.VERSIONS[document],
        locale=locale,
        title=text.title,
        intro=text.intro,
        sections=[LegalSectionOut(heading=s.heading, paragraphs=list(s.paragraphs)) for s in text.sections],
    )


@router.post("/me/legal/accept", response_model=UserOut)
def accept_document(body: AcceptLegalIn, request: Request, user: CurrentUser, db: DB) -> UserOut:
    """Accept the current version of the Terms of Use or the Organizer Terms (with the DPA)."""
    if body.version != legal.VERSIONS[body.document]:
        # The user was shown an older text: they must see (and accept) the current one.
        raise HTTPException(status.HTTP_409_CONFLICT, "These terms have changed. Please read the current version.")
    legal.accept(db, user, body.document, locale=legal.locale_from(request.headers.get("accept-language")), channel=channel(request))
    db.commit()
    return UserOut.model_validate(user)
