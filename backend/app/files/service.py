"""File Library rules: what may be uploaded, how much, by whom, and what chat may attach.

No LangChain and no app.rag here: reading files and embedding their text belong to
app/files/processing.py. Every query is scoped by the owning user: another user's file is a
404, exactly like a missing one.

Upload (one request, docs/api-contract.md "Files"): everything that can be checked from the
name and the declared size is checked before a byte is read; the body is streamed to a private
temporary file while it is hashed and counted; then one transaction, under a lock on the
student's user row, stores it (or returns the same bytes already in the library).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import unicodedata
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FILE_BLOB_BYTES, Message, MessageAttachment, User, UserFile, UserFileBlob
from app.errors import (
    Conflict,
    NotFound,
    PayloadTooLarge,
    RateLimited,
    ServiceUnavailable,
    UnsupportedMediaType,
    ValidationFailed,
)
from app.files.schemas import FileOut, FileUsage

MiB = 1024 * 1024
QUOTA_BYTES = 100 * MiB  # per student, every file whatever its state (shown as "100 MB")
MAX_UPLOAD_BYTES = 25 * MiB  # the largest type limit: the route's body limit
MAX_FILES = 500
MAX_PENDING = 5  # files a student may have waiting to be read at once
MAX_ATTEMPTS = 3  # processing claims per file, retries included
MAX_ATTACHMENTS = 5  # per message
SCOPE_FILES = 5  # a turn uses the most recently attached files of its conversation...
SCOPE_CHUNKS = 4_000  # ...up to this many chunks in total (exact search stays cheap)
DB_CEILING_BYTES = 3 * 1024**3  # physical guard for the shared disk and its backups
MIN_FREE_DISK_BYTES = 5 * 10**9
# What DB_CEILING_BYTES limits: this app's own tables (schema public), indexes and TOAST included. The
# database is shared: the NCERT knowledge service keeps its own, much larger schema in it, which must not
# stop students' uploads (the disk itself stays guarded by MIN_FREE_DISK_BYTES).
OWN_DATA_BYTES = text(
    "SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')"
)
# Failures a retry can fix. Everything else is a property of the file itself.
RETRYABLE = frozenset(
    {"embedding_failed", "extractor_failed", "chunk_limit_reached", "files_capacity_reached", "model_changed"}
)


@dataclass(frozen=True)
class FileType:
    kind: str
    max_bytes: int
    magic: str  # how the first bytes are checked: pdf, zip, png, jpeg, webp or text


TYPES: dict[str, FileType] = {
    ".pdf": FileType("pdf", 25 * MiB, "pdf"),
    ".docx": FileType("docx", 25 * MiB, "zip"),
    ".pptx": FileType("pptx", 25 * MiB, "zip"),
    ".xlsx": FileType("xlsx", 10 * MiB, "zip"),
    ".csv": FileType("csv", 2 * MiB, "text"),
    ".txt": FileType("txt", 2 * MiB, "text"),
    ".md": FileType("md", 2 * MiB, "text"),
    ".markdown": FileType("md", 2 * MiB, "text"),
    ".png": FileType("image", 10 * MiB, "png"),
    ".jpg": FileType("image", 10 * MiB, "jpeg"),
    ".jpeg": FileType("image", 10 * MiB, "jpeg"),
    ".webp": FileType("image", 10 * MiB, "webp"),
}

# Invisible or direction-changing characters that could disguise a name ("gpj.exe"), and C0/C1
# controls. Path separators are handled before this.
_HIDDEN = re.compile("[\x00-\x1f\x7f-\x9f؜​-‏ -‮⁠-⁩﻿]")


def sanitize_filename(raw: str) -> str | None:
    """A display name: the last path part, visible characters only, at most 255 UTF-8 bytes.

    None when nothing usable is left (no name before the extension). The name is only ever
    shown or quoted; it is never a path and never reaches a parser."""
    name = unicodedata.normalize("NFC", raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = " ".join(_HIDDEN.sub("", name).split())
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem.strip(" .") or len(extension.encode("utf-8")) > 16:
        return None  # no supported extension is longer than 9 characters
    extension = "." + extension
    while stem and len((stem + extension).encode("utf-8")) > 255:
        stem = stem[:-1]
    if not stem.strip(" ."):
        return None
    return stem.rstrip() + extension


# What GET /v1/files/{id}/content answers with, per kind; images by the format the upload verified.
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
    "md": "text/markdown",
}
IMAGE_MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
CONTENT_TYPES = (*MEDIA_TYPES.values(), *IMAGE_MEDIA_TYPES.values())


def media_type(file: UserFile) -> str:
    if file.kind == "image":
        declared = file_type(file.filename)
        return IMAGE_MEDIA_TYPES[declared.magic if declared and declared.magic in IMAGE_MEDIA_TYPES else "png"]
    return MEDIA_TYPES[file.kind]


async def stream_blobs(sessionmaker, file_id: uuid.UUID):
    """The file's bytes, one 1 MiB row per query (never the whole file in memory)."""
    seq = 0
    while True:
        async with sessionmaker() as session:
            data = await session.scalar(
                select(UserFileBlob.data).where(UserFileBlob.file_id == file_id, UserFileBlob.seq == seq)
            )
        if data is None:
            return
        yield bytes(data)
        seq += 1


def file_type(name: str) -> FileType | None:
    return TYPES.get("." + name.rsplit(".", 1)[-1].lower())


def sniff(file_type_: FileType, head: bytes) -> bool:
    """Do the first bytes look like the declared type? (The sandbox checks the whole structure.)"""
    magic = file_type_.magic
    if magic == "pdf":
        return b"%PDF-" in head[:1024]
    if magic == "zip":
        return head.startswith(b"PK\x03\x04")
    if magic == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if magic == "jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if magic == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    # Text: never binary. UTF-16 has NUL bytes, so it must say so with a byte-order mark.
    return head[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" not in head


def is_retryable(file: UserFile) -> bool:
    return file.status == "failed" and file.error_code in RETRYABLE and file.attempts < MAX_ATTEMPTS


def file_out(file: UserFile) -> FileOut:
    return FileOut(
        id=file.id,
        filename=file.filename,
        kind=file.kind,
        size_bytes=file.size_bytes,
        status=file.status,
        error_code=file.error_code,
        retryable=is_retryable(file),
        created_at=file.created_at,
        updated_at=file.updated_at,
    )


# ------------------------------------------------------------------------------ reads
async def _used_bytes(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(select(func.coalesce(func.sum(UserFile.size_bytes), 0)).where(UserFile.user_id == user_id))
        or 0
    )


async def usage(session: AsyncSession, user_id: uuid.UUID) -> FileUsage:
    used = await _used_bytes(session, user_id)
    return FileUsage(used_bytes=used, quota_bytes=QUOTA_BYTES, remaining_bytes=max(0, QUOTA_BYTES - used))


async def list_files(session: AsyncSession, user_id: uuid.UUID, sha256: str | None = None) -> list[UserFile]:
    query = select(UserFile).where(UserFile.user_id == user_id)
    if sha256 is not None:
        query = query.where(UserFile.sha256 == sha256)
    return list(await session.scalars(query.order_by(UserFile.created_at.desc(), UserFile.id.desc())))


async def get_file(session: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> UserFile:
    file = await session.scalar(select(UserFile).where(UserFile.id == file_id, UserFile.user_id == user_id))
    if file is None:
        raise NotFound("File not found.")
    return file


# ------------------------------------------------------------------------------ upload
async def check_capacity(session: AsyncSession) -> None:
    """The shared disk (database, dumps) is never filled by uploads."""
    try:
        free = shutil.disk_usage("/").free
    except OSError:
        free = MIN_FREE_DISK_BYTES
    size = int(await session.scalar(OWN_DATA_BYTES) or 0)
    if free < MIN_FREE_DISK_BYTES or size >= DB_CEILING_BYTES:
        raise ServiceUnavailable(
            "File storage is full right now. Please try again later.", code="files_capacity_reached"
        )


async def _check_counts(session: AsyncSession, user_id: uuid.UUID) -> None:
    total, pending = (
        await session.execute(
            select(func.count(), func.count().filter(UserFile.status == "processing")).where(
                UserFile.user_id == user_id
            )
        )
    ).one()
    if total >= MAX_FILES:
        raise Conflict(f"Your File Library already holds {MAX_FILES} files.", code="too_many_files")
    if pending >= MAX_PENDING:
        raise RateLimited(
            "Some of your files are still being read. Wait for them before adding more.",
            code="too_many_pending_files",
        )


def _quota_exceeded() -> Conflict:
    return Conflict("Storage full. Free up storage to upload another file.", code="storage_quota_exceeded")


async def precheck_upload(
    session: AsyncSession, user_id: uuid.UUID, file_type_: FileType, declared_size: int | None
) -> None:
    """Everything that can be refused before the body is read."""
    if declared_size is not None and declared_size > file_type_.max_bytes:
        raise PayloadTooLarge(too_large_message(file_type_), code="file_too_large")
    await check_capacity(session)
    if await _used_bytes(session, user_id) + (declared_size or 0) > QUOTA_BYTES:
        raise _quota_exceeded()
    await _check_counts(session, user_id)


def too_large_message(file_type_: FileType) -> str:
    return f"This file is too large. The limit for this type is {file_type_.max_bytes // MiB} MB."


async def receive(chunks: AsyncIterator[bytes], file_type_: FileType) -> tuple[BinaryIO, int, str]:
    """Stream the body into an anonymous temporary file (gone when closed, even after a crash),
    counting and hashing it. Refused as soon as it passes the type's limit."""
    spool = tempfile.TemporaryFile()
    try:
        digest = hashlib.sha256()
        size = 0
        head = bytearray()
        async for chunk in chunks:
            if not chunk:
                continue
            size += len(chunk)
            if size > file_type_.max_bytes:
                raise PayloadTooLarge(too_large_message(file_type_), code="file_too_large")
            if len(head) < 8192:
                head += chunk[: 8192 - len(head)]
            digest.update(chunk)
            spool.write(chunk)
        if size == 0:
            raise ValidationFailed("The file is empty.", fields=[{"field": "body", "reason": "empty"}])
        if not sniff(file_type_, bytes(head)):
            raise UnsupportedMediaType("This file's contents do not match its type.", code="type_mismatch")
        spool.seek(0)
        return spool, size, digest.hexdigest()
    except BaseException:
        spool.close()
        raise


async def store(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    file_type_: FileType,
    spool: BinaryIO,
    size: int,
    sha256: str,
    status: str,
) -> tuple[UserFile, bool]:
    """(file, created). The same bytes already in the library are returned instead, unchanged."""
    # Serialises this student's uploads (quota, duplicates) without blocking foreign-key inserts.
    await session.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    existing = await session.scalar(select(UserFile).where(UserFile.user_id == user_id, UserFile.sha256 == sha256))
    if existing is not None:
        await session.commit()
        return existing, False
    if await _used_bytes(session, user_id) + size > QUOTA_BYTES:
        raise _quota_exceeded()
    await _check_counts(session, user_id)
    file = UserFile(user_id=user_id, filename=name, kind=file_type_.kind, size_bytes=size, sha256=sha256, status=status)
    session.add(file)
    await session.flush()
    seq = 0
    while block := spool.read(FILE_BLOB_BYTES):
        await session.execute(insert(UserFileBlob).values(file_id=file.id, seq=seq, data=block))
        seq += 1
    await session.commit()
    await session.refresh(file)
    return file, True


# ------------------------------------------------------------------------------ changes
async def retry(session: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> UserFile:
    """Queue a failed file again, if its failure can be fixed by trying again. One request wins."""
    claimed = await session.scalar(
        update(UserFile)
        .where(
            UserFile.id == file_id,
            UserFile.user_id == user_id,
            UserFile.status == "failed",
            UserFile.error_code.in_(RETRYABLE),
            UserFile.attempts < MAX_ATTEMPTS,
        )
        .values(status="processing", error_code=None, processing_started_at=None, updated_at=func.clock_timestamp())
        .returning(UserFile.id)
    )
    if claimed is None:
        await get_file(session, user_id, file_id)  # 404 when it is not this student's
        raise Conflict("This file cannot be retried. Delete it and upload it again.", code="retry_not_allowed")
    await session.commit()
    return await get_file(session, user_id, file_id)


async def delete_file(session: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> str:
    """Delete a file with its bytes and text; attachments keep only its name. Returns its status."""
    status = await session.scalar(
        delete(UserFile).where(UserFile.id == file_id, UserFile.user_id == user_id).returning(UserFile.status)
    )
    if status is None:
        raise NotFound("File not found.")
    await session.commit()
    return status


# ------------------------------------------------------------------------------ chat
async def resolve_attachments(session: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID]) -> list[UserFile]:
    """The files a message attaches: this student's, and ready. Locked (FOR KEY SHARE) until the
    message is saved, so a concurrent delete waits instead of breaking the insert."""
    if not ids:
        return []
    rows = {
        file.id: file
        for file in await session.scalars(
            select(UserFile)
            .where(UserFile.id.in_(ids), UserFile.user_id == user_id)
            .with_for_update(read=True, key_share=True)
        )
    }
    if any(file_id not in rows for file_id in ids):
        raise ValidationFailed(
            "An attached file is no longer in your library.", fields=[{"field": "attachmentIds", "reason": "not_found"}]
        )
    if any(rows[file_id].status != "ready" for file_id in ids):
        raise ValidationFailed(
            "Wait until every attached file is ready.", fields=[{"field": "attachmentIds", "reason": "not_ready"}]
        )
    return [rows[file_id] for file_id in ids]


async def add_attachments(session: AsyncSession, message_id: uuid.UUID, files: list[UserFile]) -> None:
    for position, file in enumerate(files):
        session.add(
            MessageAttachment(message_id=message_id, file_id=file.id, filename=file.filename, position=position)
        )


async def conversation_files(session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID) -> list[dict]:
    """What a turn may read: the most recently attached ready files of the conversation."""
    latest = (
        select(MessageAttachment.file_id, func.max(Message.created_at).label("attached_at"))
        .join(Message, Message.id == MessageAttachment.message_id)
        .where(Message.conversation_id == conversation_id, MessageAttachment.file_id.is_not(None))
        .group_by(MessageAttachment.file_id)
        .subquery()
    )
    rows = await session.execute(
        select(UserFile.id, UserFile.filename, UserFile.char_count, UserFile.chunk_count)
        .join(latest, latest.c.file_id == UserFile.id)
        .where(UserFile.user_id == user_id, UserFile.status == "ready")
        .order_by(latest.c.attached_at.desc())
        .limit(SCOPE_FILES)
    )
    files: list[dict] = []
    chunks = 0
    for row in rows:
        if files and chunks + (row.chunk_count or 0) > SCOPE_CHUNKS:
            break
        chunks += row.chunk_count or 0
        files.append(
            {
                "id": row.id,
                "filename": row.filename,
                "char_count": row.char_count or 0,
                "chunk_count": row.chunk_count or 0,
            }
        )
    return files
