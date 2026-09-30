"""/v1/files: the student's File Library (docs/api-contract.md, "Files").

Upload is one request: the raw file as the body, its name as `filename`. `GET /v1/files?sha256=`
first lets a client skip uploading bytes the library already has.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_auth_service, get_principal
from app.auth.service import AuthService
from app.db.session import get_session
from app.errors import ServiceUnavailable, UnsupportedMediaType, ValidationFailed
from app.files import service as files
from app.files.schemas import FileList, FileOut

router = APIRouter(prefix="/v1/files", tags=["files"])

UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        # The largest type limit; the web app's proxy caps uploads at this.
        "x-max-bytes": files.MAX_UPLOAD_BYTES,
    }
}
SHA256 = r"^[0-9a-f]{64}$"
BINARY = {"schema": {"type": "string", "format": "binary"}}
CONTENT_RESPONSE = {200: {"content": {media: BINARY for media in files.CONTENT_TYPES}}}


@router.get("", response_model=FileList, summary="The File Library, newest first, with storage used")
async def list_files(
    sha256: str | None = Query(None, pattern=SHA256, description="Only the file with these bytes, if any"),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    rows = await files.list_files(db, principal.user.id, sha256)
    return FileList(items=[files.file_out(f) for f in rows], usage=await files.usage(db, principal.user.id))


@router.post(
    "",
    response_model=FileOut,
    status_code=201,
    openapi_extra=UPLOAD_BODY,
    responses={200: {"model": FileOut, "description": "The same bytes are already in the library"}},
    summary="Upload a file (the raw bytes); it is then read in the background",
)
async def upload_file(
    request: Request,
    response: Response,
    filename: str = Query(..., min_length=1, max_length=1000),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    auth: AuthService = Depends(get_auth_service),
):
    """PDF, DOCX, PPTX (25 MB), XLSX, PNG, JPEG, WebP (10 MB), CSV, TXT, MD (2 MB). Counted
    against the 100 MB storage of the student. 201 = stored and queued; 200 = already there."""
    name = files.sanitize_filename(filename)
    if name is None:
        raise ValidationFailed("The file needs a name.", fields=[{"field": "filename", "reason": "invalid"}])
    file_type = files.file_type(name)
    if file_type is None:
        raise UnsupportedMediaType(
            "This file type isn't supported. Upload a PDF, Word, PowerPoint, Excel, CSV, text or image file.",
            code="unsupported_file_type",
        )
    worker = request.app.state.file_worker
    if not worker.available:
        raise ServiceUnavailable("Files can't be added right now. Please try again later.", code="files_unavailable")
    length = request.headers.get("content-length", "")
    declared = int(length) if length.isdigit() else None
    await auth.throttle_files(principal.user)  # commits
    await files.precheck_upload(db, principal.user.id, file_type, declared)
    await db.commit()  # no transaction (and no pooled connection) is held while the body arrives
    spool, size, sha256 = await files.receive(request.stream(), file_type)
    try:
        status = "processing" if worker.available else "stored"
        file, created = await files.store(db, principal.user.id, name, file_type, spool, size, sha256, status)
    finally:
        spool.close()
    if created:
        worker.wake()
    else:
        response.status_code = 200
    return files.file_out(file)


@router.get("/{file_id}", response_model=FileOut, summary="One file and its status")
async def get_file(
    file_id: uuid.UUID, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_session)
):
    return files.file_out(await files.get_file(db, principal.user.id, file_id))


@router.get(
    "/{file_id}/content",
    response_class=Response,
    responses=CONTENT_RESPONSE,
    summary="The file's original bytes (its owner only)",
)
async def file_content(
    file_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    """Streamed one stored row at a time. Bytes per id never change (a new upload is a new id), so a
    browser may keep them an hour; `Content-Length` makes a cut-short stream fail, not look whole."""
    file = await files.get_file(db, principal.user.id, file_id)
    return StreamingResponse(
        files.stream_blobs(request.app.state.db.sessionmaker, file.id),
        media_type=files.media_type(file),
        headers={
            "Content-Length": str(file.size_bytes),
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{file.sha256}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(file.filename, safe='')}",
        },
    )


@router.post("/{file_id}/retry", response_model=FileOut, summary="Read a failed file again (when that can help)")
async def retry_file(
    file_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
    auth: AuthService = Depends(get_auth_service),
):
    if not request.app.state.file_worker.available:
        raise ServiceUnavailable("Files can't be read right now. Please try again later.", code="files_unavailable")
    await auth.throttle_files(principal.user)
    file = await files.retry(db, principal.user.id, file_id)
    request.app.state.file_worker.wake()
    return files.file_out(file)


@router.delete("/{file_id}", status_code=204, summary="Delete a file (frees its storage)")
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    if await files.delete_file(db, principal.user.id, file_id) == "processing":
        await request.app.state.file_worker.cancel(file_id)
    return Response(status_code=204)
