from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessments import state as assessments
from app.auth.dependencies import Principal, get_principal
from app.chat.schemas import (
    AssessmentOut,
    AssessmentResponseRequest,
    CancelOut,
    ChatRequest,
    ChatResponse,
    FeedbackOut,
    FeedbackRequest,
)
from app.chat.service import ChatService, PreparedTurn, collect
from app.chat.streams import sse_body
from app.conversations.repository import ConversationRepository
from app.conversations.router import conversation_out, message_out
from app.conversations.schemas import ConversationOut, MessageOut
from app.db.models import MessageFeedback
from app.db.session import get_session
from app.errors import Conflict, NotFound, ValidationFailed, error_body
from app.logging import get_logger
from app.progress.learning import now

router = APIRouter(prefix="/v1", tags=["chat"])
log = get_logger("app.assessments")

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
ERROR_STATUS = {"llm_unavailable": 502, "llm_timeout": 504, "llm_bad_request": 422, "service_unavailable": 503}


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat


def _stream(chat: ChatService, turn: PreparedTurn, request: Request) -> StreamingResponse:
    generation = chat.start(turn)
    keepalive = request.app.state.settings.stream_keepalive_s
    return StreamingResponse(
        sse_body(turn.meta_event(), generation, keepalive), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/chat/stream", summary="Send a message and stream the reply (Server-Sent Events)")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    chat: ChatService = Depends(get_chat_service),
):
    turn = await chat.prepare_message(db, principal.user, body.conversation_id, body.message, body.attachment_ids)
    return _stream(chat, turn, request)


@router.post("/chat", response_model=ChatResponse, summary="Send a message and wait for the whole reply")
async def chat_complete(
    body: ChatRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    chat: ChatService = Depends(get_chat_service),
):
    turn = await chat.prepare_message(db, principal.user, body.conversation_id, body.message, body.attachment_ids)
    generation = chat.start(turn)
    final, _ = await collect(generation)
    if final.type == "error":
        code = final.data.get("code", "internal_error")
        return JSONResponse(
            status_code=ERROR_STATUS.get(code, 500),
            content=error_body(code, final.data.get("message", ""), messageId=final.data.get("messageId")),
        )
    return ChatResponse(
        conversation=ConversationOut.model_validate(final.data["conversation"]),
        user_message=message_out(turn.user_message, turn.user_attachments) if turn.user_message else None,
        message=MessageOut.model_validate(final.data["message"]),
    )


@router.post(
    "/conversations/{conversation_id}/regenerate/stream",
    summary="Replace the last reply with a new one (Server-Sent Events)",
)
async def regenerate_stream(
    conversation_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    chat: ChatService = Depends(get_chat_service),
):
    turn = await chat.prepare_regenerate(db, principal.user, conversation_id)
    return _stream(chat, turn, request)


@router.post("/messages/{message_id}/cancel", response_model=CancelOut, summary="Stop a reply being generated")
async def cancel_message(
    message_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    chat: ChatService = Depends(get_chat_service),
):
    return CancelOut(status=await chat.cancel(db, principal.user, message_id))


async def _owned_assistant_message(db: AsyncSession, user_id: uuid.UUID, message_id: uuid.UUID):
    message = await ConversationRepository(db).get_message(user_id, message_id)
    if message is None or message.role != "assistant":
        raise NotFound("Message not found.")
    return message


@router.put("/messages/{message_id}/feedback", response_model=FeedbackOut, tags=["feedback"])
async def put_feedback(
    message_id: uuid.UUID,
    body: FeedbackRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    await _owned_assistant_message(db, principal.user.id, message_id)
    rating = 1 if body.rating == "up" else -1
    comment = (body.comment or "").strip() or None
    statement = insert(MessageFeedback).values(
        message_id=message_id, user_id=principal.user.id, rating=rating, comment=comment
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["message_id", "user_id"],
            set_={"rating": rating, "comment": comment, "updated_at": statement.excluded.created_at},
        )
    )
    await db.commit()
    return FeedbackOut(message_id=message_id, rating=body.rating, comment=comment)


@router.get("/messages/{message_id}/feedback", response_model=FeedbackOut, tags=["feedback"])
async def get_feedback(
    message_id: uuid.UUID, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    await _owned_assistant_message(db, principal.user.id, message_id)
    row = await db.scalar(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id, MessageFeedback.user_id == principal.user.id
        )
    )
    if row is None:
        raise NotFound("No feedback for this message.")
    return FeedbackOut(message_id=message_id, rating="up" if row.rating > 0 else "down", comment=row.comment)


REFUSED = {
    "closed": "This test can no longer be answered.",
    "changed": "This test has changed. Reload to see it.",
    "corrupt": "This test can't be answered. Ask for a new one.",
    "unsupported": "This test can't be answered. Ask for a new one.",
    "answered": "This question already has an answer.",
    "out_of_order": "Answer the waiting question first.",
}


@router.post(
    "/messages/{message_id}/assessment-responses",
    response_model=AssessmentOut,
    tags=["assessments"],
    summary="Answer or skip the waiting question of a practice test in a reply",
)
async def respond_to_assessment(
    message_id: uuid.UUID,
    body: AssessmentResponseRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """Answers are final, in order and graded here. Sending the same response again returns the
    same test unchanged (a safe retry); any other response to an answered question, or to a
    question after the waiting one, is 409. The message row is locked while the response is
    recorded, so two tabs or a double tap record one response."""
    message = await ConversationRepository(db).get_message(principal.user.id, message_id, lock=True)
    if message is None or message.role != "assistant":
        raise NotFound("Message not found.")
    records = list((message.metadata_ or {}).get("assessments") or [])
    if body.position >= len(records):
        raise NotFound("This reply has no such test.")
    extra = {"message_id": str(message_id), "position": body.position, "question": body.question}
    try:
        record, changed = assessments.respond(
            records[body.position],
            status=message.status,
            client_hash=body.hash,
            question=body.question,
            action=body.action,
            value=body.value,
            at=now().isoformat(),
        )
    except assessments.Refused as refused:
        log.warning(
            "assessment hash mismatch" if refused.reason == "corrupt" else "assessment conflict",
            extra={**extra, "reason": refused.reason},
        )
        raise Conflict(REFUSED[refused.reason], code=f"assessment_{refused.reason}") from None
    except assessments.Invalid as invalid:
        log.info("assessment invalid", extra={**extra, "reason": str(invalid)})
        raise ValidationFailed("This test has no such question or option.") from None
    if changed:
        records[body.position] = record
        message.metadata_ = {**message.metadata_, "assessments": records}
        await db.commit()
        latest = record["responses"][-1]
        log.info("assessment response", extra={**extra, "status": latest["status"], "earned": latest["earned"]})
        if assessments.state_of(record) == "completed":
            earned = sum(response["earned"] for response in record["responses"])
            log.info("assessment completed", extra={**extra, "earned": earned, "possible": record["total"]})
    return assessments.public(record, message.id, message.status)


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT, tags=["feedback"])
async def delete_feedback(
    message_id: uuid.UUID, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    await _owned_assistant_message(db, principal.user.id, message_id)
    await db.execute(
        delete(MessageFeedback).where(
            MessageFeedback.message_id == message_id, MessageFeedback.user_id == principal.user.id
        )
    )
    await db.commit()
    return Response(status_code=204)


__all__ = ["router", "conversation_out"]
