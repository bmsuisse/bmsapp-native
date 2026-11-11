"""Router for file uploads from the app (document scans via VisionKit, files
picked in the app, files shared into a web app from other apps, and the photos,
scans and signatures of native forms).

Separate from `router.py`, because file uploads (multipart/form-data) need a
different FastAPI mechanism than the JSON endpoints for devices/locations —
the same principle in substance: no storage of its own, everything goes
unchanged to your callback.

Native forms (`showForm`, see `surfaces.py`) upload their media here
**before** the form result reaches the page, with `kind="form"`. The page only
gets a small reference per file (`NativeFileRef`) and sends it to your backend
with its normal request; `resolve_file_refs` turns the references back into
what you stored. Details: `docs/native-surfaces-guide.md`.

The app sends a `kind` with every upload: `"scan"` (`scanDocument`), `"pick"`
(`pickFiles`), `"shared"` (files shared into the web app from other apps),
`"form"` (native forms), or the `kind` the web app asked for (`a-z0-9_-`, 1 to
32 characters). Every upload carries a fresh `upload_id` (UUID v4 per file), which
the app repeats when it retries after a network error or an HTTP 5xx.

**What the router answers reaches the page.** The app hands the JSON response to
the page verbatim as `NativeDocument.upload.body` (and the status as
`upload.status`) — also for error responses, so `{"detail": …}` of a 4xx/5xx
too. Anything the router or your callback puts into the response is visible to
the web app's JavaScript: no secrets, no signed URLs with tokens.

`NativeDocument` is what the page receives from `scanDocument`, `pickFiles` and
shared files; use it as the type in the request body of your own endpoint when the
page relays such a result to you. Details: `docs/documents-guide.md`.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from .widgets import WidgetRequestContext

#: Default upload limit of `create_document_router`.
DEFAULT_MAX_DOCUMENT_BYTES = 25 * 1024 * 1024

#: The limit of the contract: the app does not take or send more bytes per document.
MAX_NATIVE_DOCUMENT_BYTES = 25_000_000

#: Bytes of the `context` of `scanDocument` / `pickFiles`, serialized to JSON.
MAX_DOCUMENT_CONTEXT_BYTES = 4096

#: The `kind` the app sends on its own. A web app can ask for other kinds
#: (`kind` option of `scanDocument` / `pickFiles`), see `DocumentKind`.
DOCUMENT_KINDS = ("scan", "pick", "shared", "form")

#: `kind` as the contract allows it: 1 to 32 characters of `a-z0-9_-`.
DOCUMENT_KIND_PATTERN = r"^[a-z0-9_-]{1,32}$"

DocumentKind = Annotated[str, StringConstraints(pattern=DOCUMENT_KIND_PATTERN)]
"""A `kind` that the contract allows. The router itself accepts any string (older
senders used other names); use this type where you want to be as strict as the app."""


def check_document_context(value: dict[str, Any]) -> dict[str, Any]:
    """The `context` rule of `scanDocument` / `pickFiles`: at most 4096 bytes once
    serialized to JSON (compact, UTF-8, like `JSON.stringify`). Returns the value
    or raises `ValueError`."""
    size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
    if size > MAX_DOCUMENT_CONTEXT_BYTES:
        raise ValueError(
            f"context is {size} bytes serialized, at most {MAX_DOCUMENT_CONTEXT_BYTES} are allowed"
        )
    return value


NativeDocumentContext = Annotated[dict[str, Any], AfterValidator(check_document_context)]
"""A JSON object of at most 4096 bytes serialized: the type of the `context` that
a web app passes to `scanDocument` / `pickFiles`. Use it in the request body of
your own endpoint if the page relays a context to you; the app already enforced it."""

_UPLOAD_ID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class NativeDocumentUpload(BaseModel):
    """What the app saw when it uploaded a document to the document router."""

    #: The final HTTP status (after the app's one retry).
    status: int = Field(ge=100, le=599)
    #: The JSON response of the backend, verbatim; `None` if it was not JSON.
    body: dict[str, Any] | None


class NativeDocument(BaseModel):
    """A document as `scanDocument`, `pickFiles` and shared files deliver it to
    the page. For backends that receive such a result relayed by the page — it is
    client input, check it like any other request body.

    A document that failed has `error` (`"failed"` or `"tooLarge"`); `mime` and
    `size` may be missing then. Any other document has both. `data` (base64) comes
    with mode `"return"`, `upload` with mode `"upload"`. JSON uses camelCase
    (`uploadId`); dump with `by_alias=True`.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    #: File name including the extension. Client input: reduce it to a base name.
    name: str = Field(min_length=1)
    mime: str | None = Field(default=None, min_length=1)
    #: Bytes.
    size: int | None = Field(default=None, ge=0)
    #: Scans only.
    pages: int | None = Field(default=None, ge=1)
    #: A UUID v4 per file, the same one the app sent as `upload_id` and reuses on retry.
    upload_id: str = Field(pattern=_UPLOAD_ID_PATTERN)
    upload: NativeDocumentUpload | None = None
    #: Base64 file content.
    data: str | None = None
    error: Literal["failed", "tooLarge"] | None = None

    @model_validator(mode="after")
    def _complete(self) -> NativeDocument:
        if self.error is None:
            if self.mime is None or self.size is None:
                raise ValueError("mime and size are required unless the document has an error")
            if self.size > MAX_NATIVE_DOCUMENT_BYTES:
                raise ValueError(f"size is above {MAX_NATIVE_DOCUMENT_BYTES} bytes")
        if self.data is not None:
            try:
                base64.b64decode(self.data, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("data is not base64") from error
        return self

    def content(self) -> bytes | None:
        """The file content decoded from `data`, `None` without `data`."""
        return None if self.data is None else base64.b64decode(self.data, validate=True)


class DocumentMetadata(BaseModel):
    device_id: str
    user_email: str | None = None
    # Free-form distinguishing attribute. The app sends "scan" (`scanDocument`),
    # "pick" (`pickFiles`), "shared" (files shared into the web app), "form"
    # (native forms) or what the web app asked for, e.g. "signature", "receipt".
    kind: str | None = None
    #: A UUID the app generates per file, for every `kind` (older apps: native
    #: forms only). The app sends the same `upload_id` again after a network error
    #: or an HTTP 5xx, so store by it: a second upload with the same `upload_id`
    #: must not create a second file (or pass `upload_results` to the router).
    upload_id: str | None = None
    #: Native forms only: `id` of the form (`NativeForm.id`) and of the field
    #: (`photo`, `scan`, `signature`) the file belongs to.
    form_id: str | None = None
    field_id: str | None = None
    #: The `context` object of the form definition (the same as
    #: `WidgetOptionsRequest.context`) or of the `scanDocument` / `pickFiles`
    #: call (at most 4096 bytes, see `NativeDocumentContext`). Client input.
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


class UploadResultStore(Protocol):
    """Remembers what the router answered per `upload_id`, so that the app's retry
    of an upload (after a network error or an HTTP 5xx) gets the same answer and
    your callback runs once. Implement it on Redis or your database when you run
    more than one process; `InMemoryUploadResults` is for one process."""

    async def get(self, upload_id: str, context: WidgetRequestContext) -> dict[str, Any] | None: ...

    async def set(
        self, upload_id: str, response: dict[str, Any], context: WidgetRequestContext
    ) -> None: ...


class InMemoryUploadResults:
    """`UploadResultStore` in the memory of this process: the most recent
    `max_entries` answers, each for `ttl_seconds`. Keyed by device and
    `upload_id`. Gone on restart and not shared between workers."""

    def __init__(self, *, max_entries: int = 1000, ttl_seconds: float = 3600.0) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[str, str], tuple[float, dict[str, Any]]] = OrderedDict()

    async def get(self, upload_id: str, context: WidgetRequestContext) -> dict[str, Any] | None:
        key = (context.device_id or "", upload_id)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry[0] < time.monotonic():
            del self._entries[key]
            return None
        return dict(entry[1])

    async def set(
        self, upload_id: str, response: dict[str, Any], context: WidgetRequestContext
    ) -> None:
        key = (context.device_id or "", upload_id)
        self._entries.pop(key, None)
        self._entries[key] = (time.monotonic() + self._ttl_seconds, dict(response))
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


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
    upload_results: UploadResultStore | None = None,
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/documents` (multipart/form-data:
    `device_id`, optionally `user_email`/`kind`/`upload_id`/`context`, plus
    `file`; for native forms also `form_id` and `field_id`). The app uploads here
    for `scanDocument` (`kind="scan"`, or the `kind` asked for), `pickFiles`
    (`"pick"`), files shared into the web app (`"shared"`) and native forms
    (`"form"`).

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
    The app repeats an upload with the same `upload_id` after a network error
    or an HTTP 5xx, for every `kind`. Either make the callback idempotent per
    `upload_id`, or pass `upload_results` (for example `InMemoryUploadResults()`):
    the router then answers a repeated `upload_id` with the answer of the first
    time and does not call the callback again. Only successful answers are
    remembered, so a failed attempt runs again.

    The page receives the JSON response verbatim as `upload.body` of its
    `NativeDocument` (and the status as `upload.status`), also for errors: it
    must not contain secrets.
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
        request_context = WidgetRequestContext(device_id=device_id, user=user, request=request)
        if upload_results is not None and upload_id:
            remembered = await upload_results.get(upload_id, request_context)
            if remembered is not None:
                return remembered
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
            request_context,
        )
        reference = _reference(result)
        response: dict[str, Any] = (
            {"ok": True} if reference is None else {"ok": True, "id": reference}
        )
        if upload_results is not None and upload_id:
            await upload_results.set(upload_id, response, request_context)
        return response

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
