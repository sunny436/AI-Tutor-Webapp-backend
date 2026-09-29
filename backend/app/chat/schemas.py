from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, field_validator

from app.conversations.schemas import ConversationOut, MessageOut
from app.schemas import ApiModel, RequestModel


class ChatRequest(RequestModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=16_000)
    # Ready files from the student's File Library to attach to this message (app/files).
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v

    @field_validator("attachment_ids")
    @classmethod
    def _unique(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(v))


class ChatResponse(ApiModel):
    conversation: ConversationOut
    user_message: MessageOut | None
    message: MessageOut


class CancelOut(ApiModel):
    status: str


class FeedbackRequest(RequestModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(ApiModel):
    message_id: uuid.UUID
    rating: Literal["up", "down"]
    comment: str | None
