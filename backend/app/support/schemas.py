"""Support requests. What a student writes is stored and forwarded as plain text only.

The subject loses line breaks (it becomes an email subject: no header injection) and control
characters; the message keeps its line breaks and tabs but loses every other control
character. At most MAX_LINKS web addresses per message.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.db.models import SUPPORT_KINDS
from app.schemas import ApiModel, RequestModel

SUBJECT_MAX = 120
MESSAGE_MIN = 10
MESSAGE_MAX = 4000
MAX_LINKS = 5

_SUBJECT_JUNK = re.compile(r"[\x00-\x1f\x7f-\x9f  ‪-‮⁦-⁩]")
_MESSAGE_JUNK = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f‪-‮⁦-⁩]")
LINK = re.compile(r"(?i)\b(?:https?://|www\.)")

SupportKind = Literal[*SUPPORT_KINDS]


def clean_subject(value: object) -> object:
    return " ".join(_SUBJECT_JUNK.sub(" ", value).split()) if isinstance(value, str) else value


def clean_message(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").replace(" ", "\n")
    return _MESSAGE_JUNK.sub("", text).strip()


class SupportRequestIn(RequestModel):
    request_id: uuid.UUID = Field(description="Chosen by the client; sending the same request again returns it.")
    kind: SupportKind
    subject: str = Field(min_length=1, max_length=SUBJECT_MAX)
    message: str = Field(min_length=MESSAGE_MIN, max_length=MESSAGE_MAX)
    page: str | None = Field(
        default=None, max_length=200, pattern=r"^/[^\s]*$", description="The app page it is about."
    )

    @field_validator("subject", mode="before")
    @classmethod
    def _subject(cls, value: object) -> object:
        return clean_subject(value)

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, value: object) -> object:
        return clean_message(value)

    @field_validator("message")
    @classmethod
    def _links(cls, value: str) -> str:
        if len(LINK.findall(value)) > MAX_LINKS:
            raise ValueError(f"at most {MAX_LINKS} links")
        return value


class SupportRequestOut(ApiModel):
    id: uuid.UUID
    request_id: uuid.UUID
    kind: SupportKind
    subject: str
    status: Literal["open", "closed"]
    created_at: datetime
