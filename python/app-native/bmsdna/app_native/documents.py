"""Router for file uploads from the app (e.g. document scans via VisionKit).

Separate from `router.py`, because file uploads (multipart/form-data) need a
different FastAPI mechanism than the JSON endpoints for devices/locations —
the same principle in substance: no storage of its own, everything goes
unchanged to your callback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .widgets import WidgetRequestContext

#: Default upload limit of `create_document_router`.
DEFAULT_MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


class DocumentMetadata(BaseModel):
    device_id: str
    user_email: str | None = None
    # Free-form distinguishing attribute, e.g. "scan", "signature", "receipt".
    kind: str | None = None


@dataclass
class ReceivedDocument:
    metadata: DocumentMetadata
    #: Base name only, without any directory part (`../x` becomes `x`).
    filename: str
    content_type: str
    data: bytes


DocumentCallback = Callable[[ReceivedDocument, WidgetRequestContext], Awaitable[None]]


def _safe_filename(name: str | None) -> str:
    # Clients can send `../../x` or a Windows path. Keep the last part only.
    base = PurePosixPath((name or "").replace("\\", "/")).name
    return base if base not in ("", ".", "..") else "upload"


def create_document_router(
    *,
    on_document_received: DocumentCallback,
    auth_dependency: Callable[..., Any],
    max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES,
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/documents` (multipart/form-data:
    `device_id`, optionally `user_email`/`kind`, plus `file`).

    Stores nothing itself — `on_document_received` gets the raw bytes
    + metadata + request context and decides where they go (blob storage,
    database, forwarding to another service, ...). Uploads larger than
    `max_bytes` are rejected with 413 before they are held in memory.
    `content_type` is whatever the client claims: do not trust it.
    """
    router = APIRouter()

    @router.post("/documents")
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        device_id: str = Form(...),
        user_email: str | None = Form(None),
        kind: str | None = Form(None),
        user: Any = Depends(auth_dependency),
    ) -> dict[str, bool]:
        chunks: list[bytes] = []
        size = 0
        while chunk := await file.read(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="Document too large")
            chunks.append(chunk)
        await on_document_received(
            ReceivedDocument(
                metadata=DocumentMetadata(device_id=device_id, user_email=user_email, kind=kind),
                filename=_safe_filename(file.filename),
                content_type=file.content_type or "application/octet-stream",
                data=b"".join(chunks),
            ),
            WidgetRequestContext(device_id=device_id, user=user, request=request),
        )
        return {"ok": True}

    return router
