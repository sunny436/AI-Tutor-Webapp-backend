from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.conversations.schemas import ConversationOut, MessageOut
from app.schemas import ApiModel, RequestModel


class ChatRequest(RequestModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=16_000)
    # Ready files from the student's File Library to attach to this message (app/files).
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)
    # "voice": the message was spoken in voice mode (app/voice) and the reply will be read aloud; for a student
    # voice mode is not for, it is a typed message.
    mode: Literal["text", "voice"] = "text"
    # Voice turns: the audio the browser decodes, for the reply's first words when the server speaks them
    # (VOICE_SERVER_SPEECH); ignored otherwise.
    speech_format: Literal["mp3", "opus", "aac"] | None = None

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


BlankText = Annotated[str, Field(max_length=200)]


class AssessmentResponseRequest(RequestModel):
    """Answer or skip the waiting question of a practice test or exercise in a reply. Only which
    question and what was chosen or typed: the questions and the grading come from the reply the
    server saved."""

    position: int = Field(ge=0, le=9, description="Which block of the reply (0: replies hold one).")
    hash: str = Field(pattern=r"^[0-9a-f]{64}$", description="The record's `hash`, as it was shown.")
    question: int = Field(ge=0, lt=30, description="0-based; must be the waiting question.")
    action: Literal["answer", "skip"]
    value: Annotated[int, Field(ge=0, lt=8)] | Annotated[list[BlankText], Field(max_length=20)] | None = Field(
        default=None,
        description="Answers only: the chosen option (0-based) of a multiple-choice question, or one text "
        "per blank of a fill-in-the-blanks exercise.",
    )

    @model_validator(mode="after")
    def _value_only_to_answer(self) -> AssessmentResponseRequest:
        if (self.action == "answer") != (self.value is not None):
            raise ValueError("value is required to answer, and only then")
        return self


class AssessmentAnswerOut(ApiModel):
    status: Literal["answered", "skipped"]
    value: int | list[str] | None
    earned: int
    possible: int
    at: str
    marks: list[bool] | None  # fill-in-the-blanks: whether each blank was right


class AssessmentQuestionOut(ApiModel):
    """One question. A multiple-choice question has `text` and `options`; a fill-in-the-blanks
    exercise has `segments` (the text around the blanks) and `blanks`. The rest are null."""

    kind: Literal["mcq", "fill_blank"]
    text: str | None
    options: list[str] | None
    segments: list[str] | None
    blanks: int | None
    response: AssessmentAnswerOut | None
    # Only once the question has a response.
    correct: int | None  # multiple choice: the right option
    answers: list[list[str]] | None  # fill-in-the-blanks: the accepted answers of each blank
    explanation: str | None


class AssessmentOut(ApiModel):
    """A practice test or exercise as the student may see it now; also each item of a reply's
    `metadata.assessments`."""

    id: str  # "<message id>:<position>"
    position: int
    schema_version: int
    kind: Literal["test", "exercise"]
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


class LearningEventOut(ApiModel):
    """What an answer did to the learning streak: the chat's `done.learning` values."""

    event: Literal["started", "extended", "milestone"]
    streak: int


class AssessmentResponseOut(AssessmentOut):
    """The test as recorded after a response, and `learning` (additive): what this answer did to the
    streak, as the chat's `done.learning` says it, when this answer to a question-bank test made its
    India day a learning day (every 5th of the day; app/progress/learning.py); null otherwise, and
    always on a replayed response."""

    learning: LearningEventOut | None
