from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.schemas import ApiModel, RequestModel

TITLE_MAX = 120


class ConversationOut(ApiModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationPage(ApiModel):
    items: list[ConversationOut]
    next_cursor: str | None


class MessageAttachmentOut(ApiModel):
    file_id: uuid.UUID | None  # None: the file was deleted from the library (its name is kept)
    filename: str


class MessageOut(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    status: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachments: list[MessageAttachmentOut] = Field(default_factory=list)  # user messages only


class MessagePage(ApiModel):
    items: list[MessageOut]
    next_cursor: str | None  # pass as `before` to load older messages


class CreateConversationRequest(RequestModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX)


class RenameConversationRequest(RequestModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("title must not be blank")
        return v
