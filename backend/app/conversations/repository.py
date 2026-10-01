"""Conversation and message queries. EVERY query is scoped by the owning user id.

A resource owned by someone else is indistinguishable from one that does not
exist (both are `None` here and 404 at the API).
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, MessageAttachment
from app.errors import ValidationFailed

DEFAULT_TITLE = "New chat"
# Messages that belong to the visible transcript. `superseded` replies were
# replaced by a regeneration and are kept only for feedback analysis.
VISIBLE_STATUSES = ("complete", "streaming", "cancelled", "error")


def encode_cursor(ts: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), uuid.UUID(row_id)
    except Exception as error:  # noqa: BLE001
        raise ValidationFailed("Invalid cursor.") from error


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, lock: bool = False) -> Conversation | None:
        query = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        if lock:
            query = query.with_for_update()
        return await self.db.scalar(query)

    async def list(self, user_id: uuid.UUID, limit: int, cursor: str | None) -> tuple[list[Conversation], str | None]:
        query = select(Conversation).where(Conversation.user_id == user_id)
        if cursor:
            ts, row_id = decode_cursor(cursor)
            query = query.where(
                or_(Conversation.updated_at < ts, and_(Conversation.updated_at == ts, Conversation.id < row_id))
            )
        rows = list(
            await self.db.scalars(
                query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1)
            )
        )
        next_cursor = encode_cursor(rows[limit - 1].updated_at, rows[limit - 1].id) if len(rows) > limit else None
        return rows[:limit], next_cursor

    async def create(self, user_id: uuid.UUID, title: str | None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=(title or "").strip() or DEFAULT_TITLE)
        self.db.add(conversation)
        await self.db.flush()
        await self.db.refresh(conversation)
        return conversation

    async def rename(self, conversation: Conversation, title: str) -> None:
        conversation.title = title
        await self.touch(conversation.id)

    async def touch(self, conversation_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(updated_at=func.clock_timestamp())
        )

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            delete(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        return result.rowcount > 0

    async def messages_page(
        self, conversation_id: uuid.UUID, limit: int, before: str | None
    ) -> tuple[list[Message], str | None]:
        query = select(Message).where(Message.conversation_id == conversation_id, Message.status.in_(VISIBLE_STATUSES))
        if before:
            ts, row_id = decode_cursor(before)
            query = query.where(or_(Message.created_at < ts, and_(Message.created_at == ts, Message.id < row_id)))
        rows = list(
            await self.db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1))
        )
        older = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
        page = rows[:limit]
        page.reverse()  # oldest first, for display
        return page, older

    async def attachments(self, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[MessageAttachment]]:
        """Files attached to these messages (already scoped by the caller's conversation), in order."""
        found: dict[uuid.UUID, list[MessageAttachment]] = {}
        if not message_ids:
            return found
        rows = await self.db.scalars(
            select(MessageAttachment)
            .where(MessageAttachment.message_id.in_(message_ids))
            .order_by(MessageAttachment.message_id, MessageAttachment.position)
        )
        for row in rows:
            found.setdefault(row.message_id, []).append(row)
        return found

    async def get_message(self, user_id: uuid.UUID, message_id: uuid.UUID, *, lock: bool = False) -> Message | None:
        query = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Conversation.user_id == user_id)
        )
        if lock:  # the message row only: writes to it wait for this transaction
            query = query.with_for_update(of=Message)
        return await self.db.scalar(query)
