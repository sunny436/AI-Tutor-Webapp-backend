"""The chat core.

prepare (request transaction)                      generate (independent task)
───────────────────────────────                    ────────────────────────────────────
load / create conversation (owned)                 load the conversation from PostgreSQL
sweep stale `streaming` rows, 409 if one is live   run the LangGraph turn graph (retrieve ->
per-user quota (usage_events)                        assemble -> generate), push token events
insert user message + assistant placeholder        stop on cancel (event or DB flag)
commit                                             persist content + status + retrieval summary

The browser only ever sends a conversation id and the new text. History, identity
and message persistence are owned here, in PostgreSQL. Retrieval and prompt assembly
belong to the graph (app/rag/graph.py); this layer never touches embeddings or pgvector.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.assistant import AssistantConfig, resolve_assistant_config
from app.chat.streams import ActiveGenerations, ChatEvent, Generation
from app.conversations.repository import DEFAULT_TITLE, ConversationRepository
from app.conversations.router import conversation_out, message_out
from app.db.models import Conversation, Message, UsageEvent, User
from app.db.session import Database
from app.errors import Conflict, NotFound, RateLimited, ValidationFailed
from app.learning.context import read_student_context
from app.llm.base import ChatMessage, GenerationOptions, LLMError
from app.logging import get_logger, request_id_var
from app.progress.activity import record_question
from app.progress.learning import is_meaningful, now, record_learning
from app.settings import Settings

log = get_logger("app.chat")

TITLE_CHARS = 60

PUBLIC_ERRORS = {
    "llm_unavailable": ("The AI service is temporarily unavailable. Please try again.", True),
    "llm_rate_limited": ("The AI service is busy right now. Please try again in a moment.", True),
    "llm_timeout": ("The AI service took too long to respond. Please try again.", True),
    "llm_bad_request": (
        "The AI model could not process this request. Try a shorter message or a new conversation.",
        False,
    ),
    "service_unavailable": ("The service is temporarily unavailable. Please try again.", True),
    "internal_error": ("Something went wrong while generating the reply.", True),
}


def public_error(code: str) -> dict:
    # Rate limits and outages are the same thing to a user: try again shortly.
    public_code = "llm_unavailable" if code == "llm_rate_limited" else code
    message, retryable = PUBLIC_ERRORS.get(code, PUBLIC_ERRORS["internal_error"])
    return {
        "code": public_code if public_code in PUBLIC_ERRORS else "internal_error",
        "message": message,
        "retryable": retryable,
    }


def make_title(text: str) -> str:
    title = " ".join(text.split())
    return (title[: TITLE_CHARS - 1].rstrip() + "…") if len(title) > TITLE_CHARS else title or DEFAULT_TITLE


@dataclass
class PreparedTurn:
    user: User
    conversation: Conversation
    user_message: Message | None  # None for a regeneration
    assistant_id: uuid.UUID
    config: AssistantConfig
    replaces_message_id: uuid.UUID | None = None

    def meta_event(self) -> ChatEvent:
        return ChatEvent(
            "meta",
            {
                "conversationId": str(self.conversation.id),
                "conversation": conversation_out(self.conversation).model_dump(mode="json", by_alias=True),
                "userMessage": message_out(self.user_message).model_dump(mode="json", by_alias=True)
                if self.user_message
                else None,
                "assistantMessageId": str(self.assistant_id),
                "replacesMessageId": str(self.replaces_message_id) if self.replaces_message_id else None,
            },
        )


class ChatService:
    def __init__(self, db: Database, settings: Settings, rag_graph, generations: ActiveGenerations) -> None:
        self.db = db
        self.settings = settings
        self.rag_graph = rag_graph  # compiled LangGraph graph (app.rag.graph.build_rag_graph)
        self.generations = generations

    # ------------------------------------------------------------------ prepare
    async def _sweep_stale(self, session: AsyncSession, conversation_id: uuid.UUID | None = None) -> None:
        """Mark `streaming` rows that can no longer be alive as interrupted."""
        cutoff = func.clock_timestamp() - timedelta(seconds=self.settings.stream_stale_after_s)
        query = update(Message).where(Message.status == "streaming", Message.created_at < cutoff)
        if conversation_id is not None:
            query = query.where(Message.conversation_id == conversation_id)
        await session.execute(
            query.values(
                status="error",
                metadata_=Message.metadata_.op("||")(func.jsonb_build_object("errorCode", "interrupted")),
            )
        )

    async def sweep_all_stale(self) -> None:
        async with self.db.sessionmaker() as session:
            await self._sweep_stale(session)
            await session.commit()

    async def _check_turn_allowed(self, session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        await self._sweep_stale(session, conversation_id)
        live = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "streaming")
        )
        if live:
            raise Conflict("A reply is already being generated in this conversation.")
        now = func.clock_timestamp()
        counts = (
            await session.execute(
                select(
                    func.count().filter(UsageEvent.created_at > now - timedelta(minutes=1)),
                    func.count().filter(UsageEvent.created_at > now - timedelta(days=1)),
                ).where(UsageEvent.user_id == user_id, UsageEvent.created_at > now - timedelta(days=1))
            )
        ).one()
        if (
            counts[0] >= self.settings.chat_generations_per_minute
            or counts[1] >= self.settings.chat_generations_per_day
        ):
            raise RateLimited("You have reached the message limit. Please try again later.")

    async def _add_placeholder(self, session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Message:
        assistant = Message(conversation_id=conversation_id, role="assistant", content="", status="streaming")
        session.add(assistant)
        await session.flush()
        # Recorded now, not at the end, so concurrent requests count toward the quota.
        session.add(
            UsageEvent(user_id=user_id, conversation_id=conversation_id, message_id=assistant.id, outcome="streaming")
        )
        return assistant

    async def prepare_message(
        self, session: AsyncSession, user: User, conversation_id: uuid.UUID | None, text: str
    ) -> PreparedTurn:
        if len(text) > self.settings.chat_max_message_chars:
            raise ValidationFailed("The message is too long.")
        repo = ConversationRepository(session)
        if conversation_id is None:
            conversation = await repo.create(user.id, make_title(text))
        else:
            conversation = await repo.get(user.id, conversation_id, lock=True)
            if conversation is None:
                raise NotFound("Conversation not found.")
        await self._check_turn_allowed(session, user.id, conversation.id)

        if conversation.title == DEFAULT_TITLE:
            has_user_messages = await session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation.id, Message.role == "user")
            )
            if not has_user_messages:
                conversation.title = make_title(text)

        user_message = Message(conversation_id=conversation.id, role="user", content=text, status="complete")
        session.add(user_message)
        await session.flush()
        await record_question(session, user.id, user.timezone, self.settings.default_timezone)
        assistant = await self._add_placeholder(session, user.id, conversation.id)
        await repo.touch(conversation.id)
        student = await read_student_context(session, user.id)
        await session.commit()
        await session.refresh(conversation)
        await session.refresh(user_message)
        return PreparedTurn(
            user, conversation, user_message, assistant.id, resolve_assistant_config(user, conversation, student)
        )

    async def prepare_regenerate(self, session: AsyncSession, user: User, conversation_id: uuid.UUID) -> PreparedTurn:
        repo = ConversationRepository(session)
        conversation = await repo.get(user.id, conversation_id, lock=True)
        if conversation is None:
            raise NotFound("Conversation not found.")
        await self._check_turn_allowed(session, user.id, conversation.id)
        last = await session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.status.in_(("complete", "cancelled", "error")))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        if last is None or last.role != "assistant":
            raise Conflict("There is no reply to regenerate.")
        last.status = "superseded"
        assistant = await self._add_placeholder(session, user.id, conversation.id)
        await repo.touch(conversation.id)
        student = await read_student_context(session, user.id)
        await session.commit()
        await session.refresh(conversation)
        return PreparedTurn(
            user,
            conversation,
            None,
            assistant.id,
            resolve_assistant_config(user, conversation, student),
            replaces_message_id=last.id,
        )

    # ----------------------------------------------------------------- generate
    def start(self, turn: PreparedTurn) -> Generation:
        generation = Generation(message_id=turn.assistant_id, queue=asyncio.Queue())
        self.generations.add(generation)
        generation.task = asyncio.create_task(self._generate(turn, generation))
        return generation

    async def _conversation(self, session: AsyncSession, conversation_id: uuid.UUID) -> list[ChatMessage]:
        """The last CHAT_HISTORY_MAX_MESSAGES usable messages, oldest first.

        No size trimming here: the graph's context budget (app/rag/context.py) decides
        what fits, so there is exactly one owner of the prompt size.
        """
        rows = list(
            await session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role.in_(("user", "assistant")),
                    Message.status.in_(("complete", "cancelled")),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(self.settings.chat_history_max_messages)
            )
        )
        return [ChatMessage(role=row.role, content=row.content) for row in reversed(rows) if row.content]

    async def _cancel_requested(self, message_id: uuid.UUID) -> bool:
        try:
            async with self.db.sessionmaker() as session:
                status = await session.scalar(select(Message.status).where(Message.id == message_id))
            return status == "cancelled"
        except Exception:  # noqa: BLE001 - a failed poll must not stop a healthy stream
            return False

    async def _wait(self, awaitable, generation: Generation):
        """Await `awaitable`, but return (False, None) if the generation is cancelled first.

        The in-process event reacts at once. The database flag (set by a cancel request
        that reached another instance) is re-checked at most every `stream_cancel_poll_s`.
        """
        now = time.monotonic()
        if now - generation.last_db_check >= self.settings.stream_cancel_poll_s:
            generation.last_db_check = now
            if await self._cancel_requested(generation.message_id):
                generation.cancel.set()
        if generation.cancel.is_set():
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            return False, None
        task = asyncio.ensure_future(awaitable)
        while True:
            waiter = asyncio.ensure_future(generation.cancel.wait())
            done, _ = await asyncio.wait(
                {task, waiter}, timeout=self.settings.stream_cancel_poll_s, return_when=asyncio.FIRST_COMPLETED
            )
            waiter.cancel()
            if task in done:
                return True, task.result()
            if generation.cancel.is_set() or await self._cancel_requested(generation.message_id):
                generation.cancel.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return False, None

    async def _generate(self, turn: PreparedTurn, generation: Generation) -> None:
        try:
            await self._run(turn, generation)
        finally:
            await generation.queue.put(None)  # end of stream, always
            self.generations.remove(turn.assistant_id)

    async def _run(self, turn: PreparedTurn, generation: Generation) -> None:
        started = time.monotonic()
        pieces: list[str] = []
        ttft_ms: int | None = None
        usage = None
        finish_reason = None
        status = "complete"
        error_code: str | None = None
        provider = model = None
        retrieval_summary: dict | None = None
        options = GenerationOptions(
            model=turn.config.model,
            temperature=turn.config.temperature
            if turn.config.temperature is not None
            else self.settings.llm_temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
        )
        try:
            async with self.db.sessionmaker() as session:
                conversation = await self._conversation(session, turn.conversation.id)
            state = {
                "user_id": turn.user.id,
                "conversation": conversation,
                "system_prompt": turn.config.system_prompt,
                "retrieval": turn.config.retrieval,
                "generation": options,
            }
            events = self.rag_graph.astream(state, stream_mode="custom").__aiter__()
            try:
                while True:
                    ok, event = await self._wait(_next(events), generation)
                    if not ok:
                        status = "cancelled"  # cancelling the pending step cancelled the running node
                        break
                    if event is None:
                        break
                    kind = event.get("event")
                    if kind == "token":
                        if ttft_ms is None:
                            ttft_ms = int((time.monotonic() - started) * 1000)
                        pieces.append(event["text"])
                        await generation.queue.put(ChatEvent("token", {"text": event["text"]}))
                    elif kind == "llm_started":
                        provider, model = event["provider"], event["model"]
                    elif kind == "llm_finished":
                        usage, finish_reason = event.get("usage"), event.get("finish_reason")
                    elif kind == "retrieval":
                        retrieval_summary = event["summary"]
            finally:
                await events.aclose()
        except LLMError as error:
            status, error_code = "error", error.code
            log.warning(
                "llm generation failed",
                extra={"error_code": error.code, "error_type": type(error).__name__, "detail": str(error)[:300]},
            )
        except Exception:  # noqa: BLE001
            status, error_code = "error", "internal_error"
            log.exception("generation crashed")

        latency_ms = int((time.monotonic() - started) * 1000)
        content = "".join(pieces)
        metadata = {
            "provider": provider,
            "model": model,
            "latencyMs": latency_ms,
            "ttftMs": ttft_ms,
            "inputTokens": usage.input_tokens if usage else None,
            "outputTokens": usage.output_tokens if usage else None,
            "finishReason": finish_reason,
            "errorCode": error_code,
            # Internal (not in the public allowlist): status, reason, sources in [n] order, timings.
            "retrieval": retrieval_summary,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        log.info(
            "generation finished",
            extra={
                "status": status,
                "provider": provider,
                "model": model,
                "latency_ms": latency_ms,
                "ttft_ms": ttft_ms,
                "output_tokens": metadata.get("outputTokens"),
                "retrieval_status": (retrieval_summary or {}).get("status"),
                "message_id": str(turn.assistant_id),
            },
        )
        try:
            message, conversation = await self._finalize(turn, content, status, metadata, latency_ms, ttft_ms, usage)
            if message.status == "error":
                event = ChatEvent(
                    "error", {**public_error(error_code or "internal_error"), "messageId": str(message.id)}
                )
            else:
                event = ChatEvent(
                    "done",
                    {
                        "message": message_out(message).model_dump(mode="json", by_alias=True),
                        "conversation": conversation_out(conversation).model_dump(mode="json", by_alias=True),
                    },
                )
        except Exception as error:  # noqa: BLE001 - the database is down; tell the client, keep the row for the sweep
            log.error(
                "could not persist generation",
                extra={"error_type": type(error).__name__, "message_id": str(turn.assistant_id)},
            )
            event = ChatEvent("error", {**public_error("service_unavailable"), "messageId": str(turn.assistant_id)})
        event.data["requestId"] = request_id_var.get()
        await generation.queue.put(event)

    async def _finalize(self, turn, content, status, metadata, latency_ms, ttft_ms, usage):
        async with self.db.sessionmaker() as session:
            # A cancel written by the cancel endpoint wins over "complete".
            final_status = await session.scalar(
                update(Message)
                .where(Message.id == turn.assistant_id)
                .values(
                    content=content,
                    status=case((Message.status == "cancelled", "cancelled"), else_=status),
                    metadata_=metadata,
                )
                .returning(Message.status)
            )
            # A fully answered, meaningful question makes today a learning day (app/progress/learning.py).
            if (
                final_status == "complete"
                and turn.user_message is not None
                and is_meaningful(turn.user_message.content)
            ):
                await record_learning(session, turn.user.id, now())
            await session.execute(
                update(UsageEvent)
                .where(UsageEvent.message_id == turn.assistant_id)
                .values(
                    provider=metadata.get("provider"),
                    model=metadata.get("model"),
                    input_tokens=usage.input_tokens if usage else None,
                    output_tokens=usage.output_tokens if usage else None,
                    latency_ms=latency_ms,
                    ttft_ms=ttft_ms,
                    outcome=status,
                )
            )
            await ConversationRepository(session).touch(turn.conversation.id)
            await session.commit()
            message = await session.get(Message, turn.assistant_id)
            conversation = await session.get(Conversation, turn.conversation.id)
            return message, conversation

    # ------------------------------------------------------------------- cancel
    async def cancel(self, session: AsyncSession, user: User, message_id: uuid.UUID) -> str:
        message = await ConversationRepository(session).get_message(user.id, message_id)
        if message is None or message.role != "assistant":
            raise NotFound("Message not found.")
        if message.status == "streaming":
            await session.execute(
                update(Message)
                .where(Message.id == message_id, Message.status == "streaming")
                .values(status="cancelled")
            )
            await session.commit()
            self.generations.cancel(message_id)
            return "cancelled"
        return message.status


async def _next(iterator):
    try:
        return await iterator.__anext__()
    except StopAsyncIteration:
        return None


async def collect(generation: Generation) -> tuple[ChatEvent, list[str]]:
    """Consume a generation to the end (non-streaming endpoint)."""
    tokens: list[str] = []
    final = ChatEvent("error", public_error("internal_error"))
    while True:
        event = await generation.queue.get()
        if event is None:
            return final, tokens
        if event.type == "token":
            tokens.append(event.data["text"])
        else:
            final = event
