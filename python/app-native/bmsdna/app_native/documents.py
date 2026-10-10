"""Router for file uploads from the app (e.g. document scans via VisionKit,
and the photos, scans and signatures of native forms).

Separate from `router.py`, because file uploads (multipart/form-data) need a
different FastAPI mechanism than the JSON endpoints for devices/locations —
the same principle in substance: no storage of its own, everything goes
unchanged to your callback.

Native forms (`showForm`, see `surfaces.py`) upload their media here
**before** the form result reaches the page, with `kind="form"`. The page only
gets a small reference per file (`NativeFileRef`) and sends it to your backend
with its normal request; `resolve_file_refs` turns the references back into
what you stored. Details: `docs/native-surfaces-guide.md`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .widgets import WidgetRequestContext

#: Default upload limit of `create_document_router`.
DEFAULT_MAX_DOCUMENT_BYTES = 25 * 1024 * 1024


class DocumentMetadata(BaseModel):
    device_id: str
    user_email: str | None = None
    # Free-form distinguishing attribute, e.g. "scan", "signature", "receipt".
    # Native forms send "form".
    kind: str | None = None
    #: Native forms only: a UUID the app generates per file. The app sends the
    #: same `upload_id` again after a failed attempt, so store by it: a second
    #: upload with the same `upload_id` must not create a second file.
    upload_id: str | None = None
    #: Native forms only: `id` of the form (`NativeForm.id`) and of the field
    #: (`photo`, `scan`, `signature`) the file belongs to.
    form_id: str | None = None
    field_id: str | None = None
    #: Native forms only: the `context` object of the form definition, the
    #: same as `WidgetOptionsRequest.context`. Client input.
    context: dict[str, Any] | None = None


class NativeFileRef(BaseModel):
    """A file of a native form as the page delivers it to your backend, in
    place of the file content: `{name, mime, size, ref}`. `ref` is what your
    `on_document_received` returned, otherwise the `upload_id`. Use it as the
    type of the field in the request body of your own endpoint and resolve it
    with `resolve_file_refs`."""

    name: str
    mime: str
    size: int = Field(ge=0)
    ref: str = Field(min_length=1)


@dataclass
class ReceivedDocument:
    metadata: DocumentMetadata
    #: Base name only, without any directory part (`../x` becomes `x`).
    filename: str
    content_type: str
    data: bytes


DocumentReference = str | int | Mapping[str, Any]
"""What `on_document_received` may return: a reference (`str` or `int`) or a
dict with an `"id"`."""

DocumentCallback = Callable[
    [ReceivedDocument, WidgetRequestContext], Awaitable[DocumentReference | None]
]


def _safe_filename(name: str | None) -> str:
    # Clients can send `../../x` or a Windows path. Keep the last part only.
    base = PurePosixPath((name or "").replace("\\", "/")).name
    return base if base not in ("", ".", "..") else "upload"


def _reference(result: DocumentReference | None) -> str | int | None:
    # The reference of the stored file: a string/int, or the "id" of a dict.
    # Anything else (including None, "" and bool) means: no reference.
    value = result.get("id") if isinstance(result, Mapping) else result
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return value if value != "" else None


def _parse_context(text: str | None) -> dict[str, Any] | None:
    if text is None or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="`context` must be a JSON object")
    return parsed


def create_document_router(
    *,
    on_document_received: DocumentCallback,
    auth_dependency: Callable[..., Any],
    max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES,
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/documents` (multipart/form-data:
    `device_id`, optionally `user_email`/`kind`, plus `file`; for native forms
    also `upload_id`, `form_id`, `field_id` and `context`).

    Stores nothing itself — `on_document_received` gets the raw bytes
    + metadata + request context and decides where they go (blob storage,
    database, forwarding to another service, ...). Uploads larger than
    `max_bytes` are rejected with 413 before they are held in memory.
    `content_type` is whatever the client claims: do not trust it.

    The callback may return a reference to the stored file (a `str` or `int`,
    or a dict with an `"id"`); the response is then `{"ok": true, "id":
    <reference>}`, and for `kind="form"` the page receives that reference.
    Without a return value the response is `{"ok": true}` and the page
    receives the `upload_id`, so your storage has to find the file under it.
    The app repeats an upload with the same `upload_id` after a failed
    attempt: make the callback idempotent per `upload_id`.
    """
    router = APIRouter()

    @router.post("/documents")
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        device_id: str = Form(...),
        user_email: str | None = Form(None),
        kind: str | None = Form(None),
        upload_id: str | None = Form(None),
        form_id: str | None = Form(None),
        field_id: str | None = Form(None),
        context: str | None = Form(None),
        user: Any = Depends(auth_dependency),
    ) -> dict[str, Any]:
        parsed_context = _parse_context(context)
        chunks: list[bytes] = []
        size = 0
        while chunk := await file.read(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="Document too large")
            chunks.append(chunk)
        result = await on_document_received(
            ReceivedDocument(
                metadata=DocumentMetadata(
                    device_id=device_id,
                    user_email=user_email,
                    kind=kind,
                    upload_id=upload_id,
                    form_id=form_id,
                    field_id=field_id,
                    context=parsed_context,
                ),
                filename=_safe_filename(file.filename),
                content_type=file.content_type or "application/octet-stream",
                data=b"".join(chunks),
            ),
            WidgetRequestContext(device_id=device_id, user=user, request=request),
        )
        reference = _reference(result)
        return {"ok": True} if reference is None else {"ok": True, "id": reference}

    return router


async def resolve_file_refs[T](
    refs: Iterable[NativeFileRef | str],
    lookup: Callable[[str], Awaitable[T | None]],
) -> list[T]:
    """Turns the references of a native form back into what you stored, in
    the POST handler of your own endpoint that the page sends them to.

    `lookup(ref)` returns the stored file (or whatever you keep) for one
    reference, or `None` if there is none — also if it belongs to another
    user: check the owner in `lookup` (take it from your `auth_dependency`),
    because the page, and so the reference, is client input. The result has
    one entry per reference, in the same order. If any reference is unknown or
    expired, nothing is returned and the request fails with 422 naming them,
    so the page can ask the user to add the file again.

        async def create_customer(body: NewCustomer, user: User = Depends(auth)):
            cards = await resolve_file_refs(
                body.card, lambda ref: uploads.get(owner=user.id, ref=ref)
            )
    """
    found: dict[str, T] = {}
    missing: list[str] = []
    ordered: list[str] = []
    for item in refs:
        ref = item if isinstance(item, str) else item.ref
        ordered.append(ref)
        if ref in found or ref in missing:
            continue
        stored = await lookup(ref)
        if stored is None:
            missing.append(ref)
        else:
            found[ref] = stored
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Unknown or expired upload reference", "refs": missing},
        )
    return [found[ref] for ref in ordered]
