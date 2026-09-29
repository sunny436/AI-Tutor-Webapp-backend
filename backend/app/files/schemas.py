from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from app.schemas import ApiModel


class FileOut(ApiModel):
    id: uuid.UUID
    filename: str
    kind: Literal["pdf", "docx", "pptx", "xlsx", "csv", "txt", "md", "image"]
    size_bytes: int
    # processing: being read; ready: the tutor can use it; failed: see error_code;
    # stored: kept, but files cannot be processed right now.
    status: Literal["processing", "ready", "failed", "stored"]
    error_code: str | None
    retryable: bool
    created_at: datetime
    updated_at: datetime


class FileUsage(ApiModel):
    used_bytes: int
    quota_bytes: int
    remaining_bytes: int


class FileList(ApiModel):
    items: list[FileOut]  # newest first
    usage: FileUsage
