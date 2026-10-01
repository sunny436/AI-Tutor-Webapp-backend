from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessments import state as assessments
from app.auth.dependencies import Principal, get_principal
from app.conversations.repository import ConversationRepository
from app.conversations.schemas import (
    ConversationOut,
    ConversationPage,
    CreateConversationRequest,
    MessageAttachmentOut,
    MessageOut,
    MessagePage,
    RenameConversationRequest,
)
from app.db.models import Conversation, Message
from app.db.session import get_session
from app.errors import NotFound

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def conversation_out(c: Conversation) -> ConversationOut:
    return ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)


def message_out(m: Message, attachments=()) -> MessageOut:
    return MessageOut(
        id=m.id,
        conversation_id=m.conversation_id,
        role=m.role,
        content=m.content,
        status=m.status,
        created_at=m.created_at,
        metadata=public_metadata(m.metadata_, m.id, m.status, m.content if m.role == "assistant" else ""),
        attachments=[MessageAttachmentOut(file_id=a.file_id, filename=a.filename) for a in attachments],
    )


def public_metadata(
    metadata: dict | None, message_id: uuid.UUID | None = None, status: str | None = None, content: str = ""
) -> dict:
    # Only fields a client may rely on; internal diagnostics stay server-side.
    allowed = ("model", "errorCode", "finishReason", "citations", "assessmentError")
    public = {k: v for k, v in (metadata or {}).items() if k in allowed}
    # A practice test or exercise as the student may see it now (app/assessments/state.py): the
    # answers of questions not yet answered stay server-side. A reply saved before its kind of block
    # was recorded gets its record from its text (answerable; stored on the first answer).
    records = assessments.records_for(metadata, content, status or "") if message_id is not None else []
    if records:
        tests = [assessments.public(record, message_id, status or "") for record in records]
        public["assessments"] = [test for test in tests if test is not None]
    return public


async def owned_conversation(repo: ConversationRepository, user_id: uuid.UUID, conversation_id: uuid.UUID):
    conversation = await repo.get(user_id, conversation_id)
    if conversation is None:
        raise NotFound("Conversation not found.")
    return conversation


@router.get("", response_model=ConversationPage)
async def list_conversations(
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    rows, next_cursor = await ConversationRepository(db).list(principal.user.id, limit, cursor)
    return ConversationPage(items=[conversation_out(c) for c in rows], next_cursor=next_cursor)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: CreateConversationRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    conversation = await ConversationRepository(db).create(principal.user.id, body.title)
    await db.commit()
    return conversation_out(conversation)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    return conversation_out(await owned_conversation(ConversationRepository(db), principal.user.id, conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: RenameConversationRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(db)
    conversation = await owned_conversation(repo, principal.user.id, conversation_id)
    await repo.rename(conversation, body.title)
    await db.commit()
    await db.refresh(conversation)
    return conversation_out(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    if not await ConversationRepository(db).delete(principal.user.id, conversation_id):
        raise NotFound("Conversation not found.")
    await db.commit()
    return Response(status_code=204)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None, max_length=200),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(db)
    await owned_conversation(repo, principal.user.id, conversation_id)
    rows, older = await repo.messages_page(conversation_id, limit, before)
    attachments = await repo.attachments([m.id for m in rows if m.role == "user"])
    return MessagePage(items=[message_out(m, attachments.get(m.id, ())) for m in rows], next_cursor=older)
