from typing import Literal

from pydantic import BaseModel, Field, StrictBool, field_validator


class LegalSectionOut(BaseModel):
    heading: str
    paragraphs: list[str]


class LegalDocumentOut(BaseModel):
    document: Literal["terms", "organizer-terms", "privacy", "imprint"]
    version: str
    locale: Literal["de", "en"]
    binding_locale: Literal["de"] = "de"
    title: str
    intro: str
    sections: list[LegalSectionOut]


class AcceptLegalIn(BaseModel):
    document: Literal["terms", "organizer-terms"]
    version: str = Field(min_length=1, max_length=20)  # the version the user was shown


TERMS_REQUIRED_MESSAGE = "Please accept the Terms of Use and confirm that you are at least 16."


class AcceptsTerms(BaseModel):
    """Mixin for requests that create an account: accepting the Terms of Use (and confirming
    the minimum age, which the checkbox states) is required and recorded."""

    # Strict: only JSON `true` counts as acceptance (lax parsing would take "yes" or 1).
    accept_terms: StrictBool = Field(description="The user ticked: accepts the Terms of Use and is at least 16.")

    @field_validator("accept_terms")
    @classmethod
    def _must_accept(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError(TERMS_REQUIRED_MESSAGE)
        return value
