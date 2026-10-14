"""Turning uploaded files into text the tutor can use: one background worker in the API process.

    upload (status processing) ──► FileWorker claims it ──► sandboxed extractor (app/files/extract.py)
        ──► LangChain Documents ──► RecursiveCharacterTextSplitter.split_documents ──► Embeddings
        ──► file_chunks (pgvector) ──► status ready

State lives in PostgreSQL (user_files), so nothing is lost on a restart or deploy: a claim is a
lease (processing_started_at) plus a counter (attempts, at most MAX_ATTEMPTS). On start-up the
worker first recovers (kills leftover extractor units, fails files out of attempts, releases
leases, flags files embedded with another model), then tests its own sandbox; files are available
only if that test passes. One file is processed at a time, fairly across students.

Untrusted bytes are parsed only by the extractor, never in this process: in production a systemd
transient unit (SANDBOX_PROPERTIES: a throwaway user, no network, no secrets, read-only files, its
own memory and time limits); elsewhere a plain child process with an empty environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import and_, delete, func, insert, select, text, update
from sqlalchemy.orm import aliased

from app.db.models import FileChunk, UserFile, UserFileBlob
from app.db.session import Database
from app.files.service import DB_CEILING_BYTES, MAX_ATTEMPTS, OWN_DATA_BYTES
from app.logging import get_logger
from app.rag.embeddings import embedding_model_id, is_configured
from app.rag.errors import EmbeddingError
from app.settings import Settings

log = get_logger("app.files")

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEPLOY_MARKER = Path("/run/aichat-deploying")  # written by deploy/server/update.sh while it runs
DEPLOY_MARKER_MAX_AGE_S = 3600
LEASE_S = 15 * 60
JOB_TIMEOUT_S = 900
EXTRACT_TIMEOUT_S = 290  # below the unit's RuntimeMaxSec, so the parent decides "timeout"
SELF_TEST_TIMEOUT_S = 30
TICK_S = 15
ENVIRONMENT_PAUSE_S = 60
MAX_STDOUT = 8 * 1024 * 1024
MAX_STDERR = 4096
MAX_FILE_CHUNKS = 2_000
MAX_USER_CHUNKS = 20_000
EMBED_BATCH = 64
EMBED_RETRY_DELAYS_S = (1, 2, 4)
OCR_LANGS = "eng+hin"
EXTRACT_CODES = frozenset(
    {
        "corrupt",
        "encrypted",
        "no_text",
        "unreadable_text",
        "invalid_encoding",
        "too_many_pages",
        "too_many_scanned_pages",
        "too_many_rows",
        "content_too_large",
    }
)

# The production sandbox for the extractor, one systemd-run property each. Checked on the host with
# backend/scripts/sandbox_probe.py and `systemd-analyze security` (exposure 1.1, "OK").
SANDBOX_PROPERTIES = (
    "DynamicUser=yes",
    "PrivateNetwork=yes",
    "IPAddressDeny=any",
    "RestrictAddressFamilies=AF_UNIX",
    "ProtectSystem=strict",
    "ProtectHome=yes",
    "PrivateTmp=yes",
    "PrivateDevices=yes",
    "ProtectProc=invisible",
    "ProcSubset=pid",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectControlGroups=yes",
    "RestrictNamespaces=yes",
    "LockPersonality=yes",
    "NoNewPrivileges=yes",
    "CapabilityBoundingSet=",
    "SystemCallFilter=@system-service",
    "SystemCallErrorNumber=EPERM",
    "TemporaryFileSystem=/opt/aichat:ro",
    f"BindReadOnlyPaths={BACKEND_DIR}",
    "InaccessiblePaths=-/etc/aichat -/etc/cloudflared -/var/lib/docker -/var/backups -/run/dbus",
    "MemoryMax=512M",
    "MemorySwapMax=0",
    "RuntimeMaxSec=300",
    "TimeoutStopSec=3",
    "CPUQuota=100%",
    "TasksMax=32",
    "LimitNOFILE=256",
    "UMask=0077",
    f"WorkingDirectory={BACKEND_DIR}",
    "Environment=PATH=/usr/bin:/bin HOME=/tmp OMP_THREAD_LIMIT=1 PYTHONDONTWRITEBYTECODE=1",
)


class FileGone(Exception):
    """The file was deleted while it was being processed: its work is discarded."""


@dataclass
class Extraction:
    pages: list[dict] = field(default_factory=list)
    code: str | None = None  # a failure of the file (FAILURE codes)
    environment_error: bool = False  # this machine cannot extract right now: try again later
    ocr_pages: int = 0


@dataclass
class Claim:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    attempt: int
    size_bytes: int

    @property
    def unit(self) -> str:
        return f"aichat-extract-{self.id}-{self.attempt}.service"


def parse_output(raw: bytes) -> Extraction:
    """The extractor's JSON, checked strictly: anything unexpected is an extractor failure."""
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict) or obj.get("protocol") != 1 or not isinstance(obj.get("ok"), bool):
        raise ValueError("protocol")
    if not obj["ok"]:
        if obj.get("code") not in EXTRACT_CODES:
            raise ValueError("code")
        return Extraction(code=obj["code"])
    pages = obj.get("pages")
    if not isinstance(pages, list) or len(pages) > 10_000:
        raise ValueError("pages")
    checked = []
    for page in pages:
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("text"), str)
            or not isinstance(page.get("meta"), dict)
        ):
            raise ValueError("page")
        meta = page["meta"]
        if set(meta) - {"page", "slide", "sheet"}:
            raise ValueError("meta")
        for key in ("page", "slide"):
            if key in meta and not (isinstance(meta[key], int) and 1 <= meta[key] <= 10_000):
                raise ValueError("meta")
        if "sheet" in meta and not (isinstance(meta["sheet"], str) and len(meta["sheet"]) <= 100):
            raise ValueError("meta")
        checked.append({"text": page["text"], "meta": dict(meta)})
    ocr_pages = obj.get("ocrPages") if isinstance(obj.get("ocrPages"), int) else 0
    return Extraction(pages=checked, ocr_pages=ocr_pages)


async def _systemctl(*args: str) -> None:
    with contextlib.suppress(OSError):
        process = await asyncio.create_subprocess_exec(
            "systemctl", *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), 10)


def _extractor_command(runner: str, unit: str, kind: str) -> tuple[list[str], dict | None]:
    module = [sys.executable, "-m", "app.files.extract", "--kind", kind, "--ocr-langs", OCR_LANGS]
    if runner == "systemd":
        properties = [arg for prop in SANDBOX_PROPERTIES for arg in ("-p", prop)]
        return ["systemd-run", "--quiet", "--pipe", "--wait", "--collect", f"--unit={unit}", *properties, *module], None
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "OMP_THREAD_LIMIT": "1"}
    if os.name == "nt":  # CPython needs these on Windows (development only)
        env.update({k: os.environ[k] for k in ("SYSTEMROOT", "TEMP", "TMP") if k in os.environ})
    return module, env


async def run_extractor(runner: str, unit: str, kind: str, chunks, timeout_s: float = EXTRACT_TIMEOUT_S) -> Extraction:
    """Run the extractor on the bytes `chunks` yields; never raises for a bad file."""
    argv, env = _extractor_command(runner, unit, kind)
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(BACKEND_DIR),
        env=env,
        start_new_session=os.name != "nt",  # a signal to the API does not reach the extractor directly
    )
    too_big = False

    async def feed() -> None:
        try:
            async for chunk in chunks:
                process.stdin.write(chunk)
                await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the extractor stopped reading (it failed early): its answer says why
        finally:
            with contextlib.suppress(Exception):
                process.stdin.close()
            with contextlib.suppress(Exception):
                await chunks.aclose()  # releases the database session that reads the bytes

    async def read(stream, limit: int) -> bytes:
        nonlocal too_big
        data = bytearray()
        while block := await stream.read(65536):
            if len(data) + len(block) > limit:
                if stream is process.stdout:
                    too_big = True
                    await _kill(process, runner, unit)  # closes both pipes: nothing waits for a timeout
                    return bytes(data)
                continue  # stderr past the limit is dropped
            data += block
        return bytes(data)

    try:
        _, stdout, _ = await asyncio.wait_for(
            asyncio.gather(feed(), read(process.stdout, MAX_STDOUT), read(process.stderr, MAX_STDERR)), timeout_s
        )
        if too_big:
            await _kill(process, runner, unit)
            return Extraction(code="content_too_large")
        await asyncio.wait_for(process.wait(), 10)
    except TimeoutError:
        await _kill(process, runner, unit)
        return Extraction(code="timeout")
    except BaseException:
        await _kill(process, runner, unit)
        raise
    if process.returncode == 3 or (process.returncode or 0) < 0:
        # 3: the extractor's machine problem. Negative: the runner itself was signalled (the API
        # stopping): not the file's fault, so the claim is given back instead of failing the file.
        return Extraction(environment_error=True)
    if process.returncode != 0:
        return Extraction(code="extractor_failed")
    try:
        return parse_output(stdout)
    except (ValueError, UnicodeDecodeError):
        return Extraction(code="extractor_failed")


async def _kill(process, runner: str, unit: str) -> None:
    if runner == "systemd":
        await _systemctl("kill", "-s", "KILL", unit)
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.wait(), 5)


class FileWorker:
    def __init__(self, db: Database, settings: Settings, embeddings: Embeddings) -> None:
        self.db = db
        self.settings = settings
        self.embeddings = embeddings
        self.runner = settings.files_runner
        self.model = embedding_model_id(embeddings)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap
        )
        self.available = False
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._current: Claim | None = None
        self._released = False
        self._cancelled: set[uuid.UUID] = set()

    # ------------------------------------------------------------------ lifecycle
    def configured(self) -> bool:
        """Files can work here at all (before the sandbox self-test)."""
        return bool(self.settings.files_enabled and self.runner and is_configured(self.embeddings))

    async def start(self) -> None:
        """Recover and self-test in the background: never delays the API becoming ready."""
        self._task = asyncio.create_task(self._main())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(self._task, 10)

    def wake(self) -> None:
        self._wake.set()

    async def cancel(self, file_id: uuid.UUID) -> None:
        """The file was deleted: stop reading it now instead of finishing work for nothing."""
        claim = self._current
        if claim is not None and claim.id == file_id:
            self._cancelled.add(file_id)
            if self.runner == "systemd":
                await _systemctl("kill", "-s", "KILL", claim.unit)

    async def _main(self) -> None:
        # Until recovery and the sandbox self-test pass, files stay unavailable (the API keeps
        # serving); they are retried with backoff, so a start during a database restart heals itself.
        delay = 15
        while True:
            try:
                await self.recover(self_test=True)
            except Exception as error:  # noqa: BLE001
                log.error("files recovery failed", extra={"error_type": type(error).__name__})
                self.available = False
            if self.available or not self.configured():
                break
            await asyncio.sleep(delay)
            delay = min(300, delay * 2)
        failures = 0
        while True:
            try:
                worked = await self.run_once() if self.available else False
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - one bad iteration never stops the worker
                failures += 1
                worked = False
                log.error("files worker iteration failed", extra={"error_type": type(error).__name__})
                await asyncio.sleep(min(60, 2**failures))
            if not worked:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), TICK_S)

    async def recover(self, *, self_test: bool) -> None:
        """After a (re)start: nothing from a previous process is still running, so settle its work."""
        if self.runner == "systemd":
            await _systemctl("kill", "-s", "KILL", "aichat-extract-*.service")
            await _systemctl("reset-failed", "aichat-extract-*.service")
        async with self.db.sessionmaker() as session:
            await session.execute(
                update(UserFile)
                .where(UserFile.status == "processing", UserFile.attempts >= MAX_ATTEMPTS)
                .values(status="failed", error_code="processing_interrupted", updated_at=func.clock_timestamp())
            )
            await session.execute(
                update(UserFile).where(UserFile.status == "processing").values(processing_started_at=None)
            )
            stale = select(FileChunk.id).where(
                FileChunk.file_id == UserFile.id, FileChunk.embedding_model != self.model
            )
            flagged = await session.execute(
                update(UserFile)
                .where(UserFile.status == "ready", stale.exists())
                .values(status="failed", error_code="model_changed", attempts=0, updated_at=func.clock_timestamp())
            )
            if flagged.rowcount:
                log.warning("files embedded with another model need a retry", extra={"files": flagged.rowcount})
            await session.commit()
        available = self.configured()
        if available and self_test:
            available = await self._self_test()
        self.available = available
        async with self.db.sessionmaker() as session:
            await session.execute(
                update(UserFile)
                .where(UserFile.status == ("stored" if available else "processing"))
                .values(status="processing" if available else "stored", updated_at=func.clock_timestamp())
            )
            await session.commit()
        log.info("files worker ready", extra={"available": available, "runner": self.runner})

    async def _self_test(self) -> bool:
        async def sample():
            yield b"AI Tutor file self test: photosynthesis makes food in plants."

        try:
            result = await run_extractor(
                self.runner,
                f"aichat-extract-selftest-{uuid.uuid4().hex[:8]}.service",
                "txt",
                sample(),
                timeout_s=SELF_TEST_TIMEOUT_S,
            )
        except Exception as error:  # noqa: BLE001
            log.error("files self-test could not run", extra={"error_type": type(error).__name__})
            return False
        ok = (
            result.code is None
            and not result.environment_error
            and "self test" in "".join(p["text"] for p in result.pages)
        )
        if not ok:
            log.error(
                "files self-test failed",
                extra={"code": result.code, "environment_error": result.environment_error},
            )
        return ok

    # ------------------------------------------------------------------ one file
    def _deploying(self) -> bool:
        try:
            return time.time() - DEPLOY_MARKER.stat().st_mtime < DEPLOY_MARKER_MAX_AGE_S
        except OSError:
            return False

    async def _claim(self) -> Claim | None:
        # Fair across students: whoever was served longest ago goes first, then the oldest file.
        f = aliased(UserFile, name="f")
        p = aliased(UserFile, name="p")
        last_started = select(func.max(p.processing_started_at)).where(p.user_id == f.user_id).scalar_subquery()
        candidate = (
            select(f.id)
            .where(
                f.status == "processing",
                f.attempts < MAX_ATTEMPTS,
                (f.processing_started_at.is_(None))
                | (f.processing_started_at < func.clock_timestamp() - text(f"interval '{LEASE_S} seconds'")),
            )
            .order_by(last_started.asc().nulls_first(), f.updated_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        async with self.db.sessionmaker() as session:
            row = (
                await session.execute(
                    update(UserFile)
                    .where(UserFile.id == candidate)
                    .values(
                        processing_started_at=func.clock_timestamp(),
                        attempts=UserFile.attempts + 1,
                        updated_at=func.clock_timestamp(),
                    )
                    .returning(UserFile.id, UserFile.user_id, UserFile.kind, UserFile.attempts, UserFile.size_bytes)
                )
            ).first()
            await session.commit()
        return Claim(*row) if row else None

    async def run_once(self) -> bool:
        """Claim and process one file. False when there was nothing to do."""
        if self._deploying():
            return False
        claim = await self._claim()
        if claim is None:
            return False
        self._current = claim
        self._released = False
        started = time.perf_counter()
        outcome, code, stats = "failed", None, {}
        try:
            async with asyncio.timeout(JOB_TIMEOUT_S):
                outcome, code, stats = await self._process(claim)
        except TimeoutError:
            code = "timeout"
            await self._fail(claim, code)
        except FileGone:
            outcome = "deleted"
        except asyncio.CancelledError:
            if not self._released:
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._release(claim))
            raise
        except Exception as error:  # noqa: BLE001
            code = "extractor_failed"
            log.error("file processing crashed", extra={"file_id": str(claim.id), "error_type": type(error).__name__})
            with contextlib.suppress(Exception):
                await self._fail(claim, code)
        finally:
            self._current = None
            self._cancelled.discard(claim.id)
        log.info(
            "file processed",
            extra={
                "file_id": str(claim.id),
                "kind": claim.kind,
                "size": claim.size_bytes,
                "attempt": claim.attempt,
                "outcome": outcome,
                "code": code,
                "total_ms": int((time.perf_counter() - started) * 1000),
                **stats,
            },
        )
        if outcome == "requeued":
            await asyncio.sleep(ENVIRONMENT_PAUSE_S)  # this machine cannot extract right now
        return True

    async def _process(self, claim: Claim) -> tuple[str, str | None, dict]:
        async with self.db.sessionmaker() as session:
            await session.execute(delete(FileChunk).where(FileChunk.file_id == claim.id))
            await session.commit()
        started = time.perf_counter()
        extraction = await run_extractor(self.runner, claim.unit, claim.kind, self._blobs(claim.id))
        stats = {"extract_ms": int((time.perf_counter() - started) * 1000), "ocr_pages": extraction.ocr_pages}
        if claim.id in self._cancelled:
            raise FileGone
        if extraction.environment_error:
            # The attempt is given back, but the lease is kept: the file waits LEASE_S instead of
            # being claimed again at once (and its student moves back in the fair order).
            await self._release(claim, keep_lease=True)
            log.warning("file extractor environment error; retrying later", extra={"file_id": str(claim.id)})
            return "requeued", None, stats
        if extraction.code:
            await self._fail(claim, extraction.code)
            return "failed", extraction.code, stats

        documents = [Document(page_content=page["text"], metadata=page["meta"]) for page in extraction.pages]
        chunks = [
            c for c in await asyncio.to_thread(self.splitter.split_documents, documents) if c.page_content.strip()
        ]
        chars = sum(len(page["text"]) for page in extraction.pages)
        stats.update(pages=len(extraction.pages), chars=chars, chunks=len(chunks))
        code = await self._capacity_problem(claim, len(chunks))
        if code:
            await self._fail(claim, code)
            return "failed", code, stats

        started = time.perf_counter()
        try:
            for start in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[start : start + EMBED_BATCH]
                vectors = await self._embed([chunk.page_content for chunk in batch])
                if claim.id in self._cancelled:
                    raise FileGone
                async with self.db.sessionmaker() as session:
                    try:
                        await session.execute(
                            insert(FileChunk),
                            [
                                {
                                    "file_id": claim.id,
                                    "ordinal": start + offset,
                                    "content": chunk.page_content,
                                    "metadata_": chunk.metadata,
                                    "embedding": vector,
                                    "embedding_model": self.model,
                                }
                                for offset, (chunk, vector) in enumerate(zip(batch, vectors, strict=True))
                            ],
                        )
                        await session.commit()
                    except Exception as error:
                        await session.rollback()
                        if await self._gone(claim.id):
                            raise FileGone from error
                        raise
        except EmbeddingError as error:
            await self._fail(claim, "embedding_failed")
            log.warning("file embedding failed", extra={"file_id": str(claim.id), "reason": error.code})
            return "failed", "embedding_failed", stats
        stats["embed_ms"] = int((time.perf_counter() - started) * 1000)

        async with self.db.sessionmaker() as session:
            done = await session.scalar(
                update(UserFile)
                .where(UserFile.id == claim.id, UserFile.status == "processing")
                .values(
                    status="ready",
                    error_code=None,
                    char_count=chars,
                    chunk_count=len(chunks),
                    updated_at=func.clock_timestamp(),
                )
                .returning(UserFile.id)
            )
            await session.commit()
        if done is None:
            raise FileGone
        return "ready", None, stats

    async def _blobs(self, file_id: uuid.UUID):
        """The file's bytes, one 1 MiB row at a time; the session is closed before the result is awaited."""
        async with self.db.sessionmaker() as session:
            seq = 0
            while True:
                data = await session.scalar(
                    select(UserFileBlob.data).where(UserFileBlob.file_id == file_id, UserFileBlob.seq == seq)
                )
                if data is None:
                    break
                yield bytes(data)
                seq += 1

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        for attempt, delay in enumerate((*EMBED_RETRY_DELAYS_S, None)):
            try:
                return await self.embeddings.aembed_documents(texts)
            except EmbeddingError as error:
                if delay is None or error.code not in ("embedding_failed", "embedding_timeout"):
                    raise
                log.warning("embedding batch retry", extra={"attempt": attempt + 1, "reason": error.code})
                await asyncio.sleep(delay + random.random())  # noqa: S311 - jitter, not security
        raise EmbeddingError("embedding_failed", "retries exhausted")

    async def _capacity_problem(self, claim: Claim, chunks: int) -> str | None:
        if chunks == 0:
            return "no_text"
        if chunks > MAX_FILE_CHUNKS:
            return "content_too_large"
        async with self.db.sessionmaker() as session:
            held = await session.scalar(
                select(func.coalesce(func.sum(UserFile.chunk_count), 0)).where(
                    UserFile.user_id == claim.user_id, UserFile.status == "ready", UserFile.id != claim.id
                )
            )
            size = await session.scalar(OWN_DATA_BYTES)
        if int(held or 0) + chunks > MAX_USER_CHUNKS:
            return "chunk_limit_reached"
        if int(size or 0) >= DB_CEILING_BYTES:
            return "files_capacity_reached"
        return None

    async def _gone(self, file_id: uuid.UUID) -> bool:
        async with self.db.sessionmaker() as session:
            return await session.scalar(select(UserFile.id).where(UserFile.id == file_id)) is None

    async def _fail(self, claim: Claim, code: str) -> None:
        async with self.db.sessionmaker() as session:
            await session.execute(delete(FileChunk).where(FileChunk.file_id == claim.id))
            await session.execute(
                update(UserFile)
                .where(UserFile.id == claim.id, UserFile.status == "processing")
                .values(status="failed", error_code=code, updated_at=func.clock_timestamp())
            )
            await session.commit()

    async def _release(self, claim: Claim, *, keep_lease: bool = False) -> None:
        """Give the claim back (shutdown, or a machine problem): it does not count as an attempt."""
        self._released = True
        if self.runner == "systemd":
            await _systemctl("kill", "-s", "KILL", claim.unit)
        async with self.db.sessionmaker() as session:
            await session.execute(
                update(UserFile)
                .where(and_(UserFile.id == claim.id, UserFile.status == "processing"))
                .values(
                    processing_started_at=func.clock_timestamp() if keep_lease else None,
                    attempts=func.greatest(UserFile.attempts - 1, 0),
                )
            )
            await session.commit()
