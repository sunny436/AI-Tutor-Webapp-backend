from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, field_validator, model_validator

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


class AssessmentResponseRequest(RequestModel):
    """Answer or skip the waiting question of a practice test in a reply. Only which question and
    which option: the questions and the grading come from the reply the server saved."""

    position: int = Field(ge=0, le=9, description="Which test of the reply (0: replies hold one).")
    hash: str = Field(pattern=r"^[0-9a-f]{64}$", description="The test's `hash`, as it was shown.")
    question: int = Field(ge=0, lt=30, description="0-based; must be the waiting question.")
    action: Literal["answer", "skip"]
    value: int | None = Field(default=None, ge=0, lt=8, description="The chosen option (0-based); answers only.")

    @model_validator(mode="after")
    def _value_only_to_answer(self) -> AssessmentResponseRequest:
        if (self.action == "answer") != (self.value is not None):
            raise ValueError("value is required to answer, and only then")
        return self


class AssessmentAnswerOut(ApiModel):
    status: Literal["answered", "skipped"]
    value: int | None
    earned: int
    possible: int
    at: str


class AssessmentQuestionOut(ApiModel):
    kind: Literal["mcq"]
    text: str
    options: list[str]
    response: AssessmentAnswerOut | None
    # Only once the question has a response.
    correct: int | None
    explanation: str | None


class AssessmentOut(ApiModel):
    """A practice test as the student may see it now; also each item of a reply's
    `metadata.assessments`."""

    id: str  # "<message id>:<position>"
    position: int
    schema_version: int
    kind: Literal["test"]
    title: str | None
    hash: str
    locator: str  # sha256 of the reply's block, trimmed: which card this is
    state: Literal["not_started", "active", "completed"]
    answerable: bool
    total: int
    answered: int
    current: int | None  # the waiting question; null once completed
    earned: int
    possible: int
    questions: list[AssessmentQuestionOut]
