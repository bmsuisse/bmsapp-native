from __future__ import annotations

from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    DOCUMENT_KINDS,
    MAX_NATIVE_DOCUMENT_BYTES,
    InMemoryUploadResults,
    NativeDocument,
    NativeDocumentContext,
    NativeFileRef,
    ReceivedDocument,
    WidgetRequestContext,
    check_document_context,
    create_document_router,
    insecure_no_auth,
    resolve_file_refs,
)
from fastapi import FastAPI, HTTPException, Request
from pydantic import TypeAdapter, ValidationError


@pytest.mark.asyncio
async def test_document_upload_reaches_callback_unmodified() -> None:
    received: list[ReceivedDocument] = []

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
        received.append(doc)

    app = FastAPI()
    app.include_router(
        create_document_router(on_document_received=on_document, auth_dependency=insecure_no_auth),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/documents",
            data={"device_id": "abc", "kind": "scan"},
            files={"file": ("page1.jpg", b"\xff\xd8\xff\xe0fake-jpeg", "image/jpeg")},
        )

    assert response.status_code == 200
    assert len(received) == 1
    doc = received[0]
    assert doc.metadata.device_id == "abc"
    assert doc.metadata.kind == "scan"
    assert doc.metadata.user_email is None
    assert doc.filename == "page1.jpg"
    assert doc.content_type == "image/jpeg"
    assert doc.data == b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.mark.asyncio
async def test_document_filename_is_reduced_to_its_base_name() -> None:
    received: list[ReceivedDocument] = []

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
        received.append(doc)

    app = FastAPI()
    app.include_router(
        create_document_router(on_document_received=on_document, auth_dependency=insecure_no_auth),
        prefix="/api",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for name in ("../../etc/passwd", "C:\\temp\\scan.jpg", ".."):
            response = await client.post(
                "/api/documents",
                data={"device_id": "abc"},
                files={"file": (name, b"x", "image/jpeg")},
            )
            assert response.status_code == 200

    assert [doc.filename for doc in received] == ["passwd", "scan.jpg", "upload"]


@pytest.mark.asyncio
async def test_document_over_the_limit_is_rejected() -> None:
    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
        raise AssertionError("must not be called")

    app = FastAPI()
    app.include_router(
        create_document_router(
            on_document_received=on_document, auth_dependency=insecure_no_auth, max_bytes=1000
        ),
        prefix="/api",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/documents",
            data={"device_id": "abc"},
            files={"file": ("big.jpg", b"x" * 1001, "image/jpeg")},
        )

    assert response.status_code == 413


def _app(on_document: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_document_router(on_document_received=on_document, auth_dependency=insecure_no_auth),
        prefix="/api",
    )
    return app


async def _post(app: FastAPI, **data: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/api/documents",
            data={"device_id": "abc", **data},
            files={"file": ("card.jpg", b"\xff\xd8jpeg", "image/jpeg")},
        )


@pytest.mark.asyncio
async def test_form_upload_fields_reach_the_callback() -> None:
    received: list[ReceivedDocument] = []

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
        received.append(doc)

    response = await _post(
        _app(on_document),
        kind="form",
        upload_id="00000000-0000-4000-8000-000000000001",
        form_id="new-customer",
        field_id="card",
        context='{"source": "customer-list"}',
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    meta = received[0].metadata
    assert (meta.kind, meta.form_id, meta.field_id) == ("form", "new-customer", "card")
    assert meta.upload_id == "00000000-0000-4000-8000-000000000001"
    assert meta.context == {"source": "customer-list"}


@pytest.mark.asyncio
async def test_scan_uploads_without_the_new_fields_keep_working() -> None:
    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
        assert (doc.metadata.upload_id, doc.metadata.form_id) == (None, None)
        assert (doc.metadata.field_id, doc.metadata.context) == (None, None)

    response = await _post(_app(on_document), kind="scan")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("returned", "body"),
    [
        ("doc-17", {"ok": True, "id": "doc-17"}),
        (17, {"ok": True, "id": 17}),
        ({"id": "doc-17", "name": "ignored"}, {"ok": True, "id": "doc-17"}),
        ({"name": "no id"}, {"ok": True}),
        ("", {"ok": True}),
        (True, {"ok": True}),
        (None, {"ok": True}),
    ],
)
async def test_the_callback_may_return_a_reference(returned: Any, body: dict[str, Any]) -> None:
    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> Any:
        return returned

    response = await _post(_app(on_document), kind="form", upload_id="u-1")

    assert response.status_code == 200
    assert response.json() == body


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["not json", "[1, 2]", '"text"'])
async def test_a_context_that_is_not_a_json_object_is_422(context: str) -> None:
    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
        raise AssertionError("must not be called")

    response = await _post(_app(on_document), kind="form", context=context)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_retried_upload_reaches_the_callback_again_with_the_same_upload_id() -> None:
    # The router stores nothing: idempotency is the callback's job, keyed by
    # `upload_id`. This is the pattern from the guide.
    stored: dict[str, bytes] = {}
    calls = 0

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> str:
        nonlocal calls
        calls += 1
        upload_id = doc.metadata.upload_id or ""
        stored.setdefault(upload_id, doc.data)
        return upload_id

    app = _app(on_document)
    first = await _post(app, kind="form", upload_id="u-1")
    second = await _post(app, kind="form", upload_id="u-1")

    assert first.json() == second.json() == {"ok": True, "id": "u-1"}
    assert calls == 2
    assert list(stored) == ["u-1"]


@pytest.mark.asyncio
async def test_resolve_file_refs_returns_what_was_stored_in_order() -> None:
    uploads = {"u-1": b"card", "u-2": b"contract"}

    async def lookup(ref: str) -> bytes | None:
        return uploads.get(ref)

    refs = [
        NativeFileRef(name="card.jpg", mime="image/jpeg", size=4, ref="u-1"),
        "u-2",
        NativeFileRef(name="card.jpg", mime="image/jpeg", size=4, ref="u-1"),
    ]
    assert await resolve_file_refs(refs, lookup) == [b"card", b"contract", b"card"]
    assert await resolve_file_refs([], lookup) == []


@pytest.mark.asyncio
async def test_resolve_file_refs_names_unknown_references_with_422() -> None:
    looked_up: list[str] = []

    async def lookup(ref: str) -> bytes | None:
        looked_up.append(ref)
        return b"x" if ref == "u-1" else None

    with pytest.raises(HTTPException) as caught:
        await resolve_file_refs(["u-1", "gone", "gone", "other"], lookup)

    assert caught.value.status_code == 422
    assert caught.value.detail == {
        "message": "Unknown or expired upload reference",
        "refs": ["gone", "other"],
    }
    assert looked_up == ["u-1", "gone", "other"]  # each reference once


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["scan", "pick", "shared", "form", "supplier-offer"])
async def test_every_kind_of_the_app_reaches_the_callback_with_its_upload_id(kind: str) -> None:
    received: list[ReceivedDocument] = []

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> str:
        received.append(doc)
        return "doc-1"

    response = await _post(
        _app(on_document),
        kind=kind,
        upload_id="8c2f1a4e-5b0a-4f3e-9d57-2b6f1c9e7a10",
        context='{"offerId": "O-1"}',
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": "doc-1"}
    meta = received[0].metadata
    assert (meta.kind, meta.upload_id) == (kind, "8c2f1a4e-5b0a-4f3e-9d57-2b6f1c9e7a10")
    assert meta.context == {"offerId": "O-1"}
    assert set(DOCUMENT_KINDS) == {"scan", "pick", "shared", "form"}


def _app_with_results(on_document: Any, **options: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_document_router(
            on_document_received=on_document,
            auth_dependency=insecure_no_auth,
            upload_results=InMemoryUploadResults(**options),
        ),
        prefix="/api",
    )
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["scan", "pick", "shared", "form"])
async def test_upload_results_make_a_retry_idempotent_for_every_kind(kind: str) -> None:
    calls = 0

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> str:
        nonlocal calls
        calls += 1
        return f"doc-{calls}"

    app = _app_with_results(on_document)
    first = await _post(app, kind=kind, upload_id="u-1")
    retry = await _post(app, kind=kind, upload_id="u-1")
    other = await _post(app, kind=kind, upload_id="u-2")

    assert first.json() == retry.json() == {"ok": True, "id": "doc-1"}
    assert other.json() == {"ok": True, "id": "doc-2"}
    assert calls == 2


@pytest.mark.asyncio
async def test_upload_results_do_not_apply_without_an_upload_id_or_across_devices() -> None:
    calls = 0

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> str:
        nonlocal calls
        calls += 1
        return f"doc-{calls}"

    app = _app_with_results(on_document)
    await _post(app, kind="scan")
    await _post(app, kind="scan")
    assert calls == 2
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for device in ("a", "b"):
            await client.post(
                "/api/documents",
                data={"device_id": device, "upload_id": "same"},
                files={"file": ("a.pdf", b"x", "application/pdf")},
            )
    assert calls == 4


@pytest.mark.asyncio
async def test_a_failed_attempt_is_not_remembered() -> None:
    attempts = 0

    async def on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPException(status_code=503, detail="try again")
        return "doc-1"

    app = _app_with_results(on_document)
    first = await _post(app, kind="pick", upload_id="u-1")
    retry = await _post(app, kind="pick", upload_id="u-1")

    assert (first.status_code, retry.status_code) == (503, 200)
    assert retry.json() == {"ok": True, "id": "doc-1"}


@pytest.mark.asyncio
async def test_in_memory_upload_results_expire_and_stay_bounded(monkeypatch: Any) -> None:
    now = [1000.0]
    monkeypatch.setattr("bmsdna.app_native.documents.time.monotonic", lambda: now[0])
    store = InMemoryUploadResults(max_entries=2, ttl_seconds=10)
    context = WidgetRequestContext(
        device_id="d", user=None, request=Request({"type": "http", "headers": []})
    )

    await store.set("a", {"ok": True}, context)
    await store.set("b", {"ok": True}, context)
    await store.set("c", {"ok": True}, context)
    assert await store.get("a", context) is None  # the oldest was dropped
    assert await store.get("c", context) == {"ok": True}
    now[0] += 11
    assert await store.get("c", context) is None  # expired


UPLOAD_ID = "8c2f1a4e-5b0a-4f3e-9d57-2b6f1c9e7a10"


def test_native_document_needs_mime_and_size_unless_it_failed() -> None:
    ok = NativeDocument.model_validate(
        {"name": "a.pdf", "mime": "application/pdf", "size": 3, "uploadId": UPLOAD_ID}
    )
    assert ok.upload_id == UPLOAD_ID
    failed = NativeDocument.model_validate(
        {"name": "a.pdf", "uploadId": UPLOAD_ID, "error": "failed"}
    )
    assert failed.mime is None
    for bad in (
        {"name": "a.pdf", "uploadId": UPLOAD_ID},
        {"name": "a.pdf", "mime": "application/pdf", "uploadId": UPLOAD_ID},
        {"name": "", "mime": "x", "size": 1, "uploadId": UPLOAD_ID},
        {"name": "a", "mime": "x", "size": 1, "uploadId": "not-a-uuid"},
        {"name": "a", "mime": "x", "size": 1, "uploadId": "8c2f1a4e-5b0a-1f3e-9d57-2b6f1c9e7a10"},
        {"name": "a", "mime": "x", "size": -1, "uploadId": UPLOAD_ID},
        {"name": "a", "mime": "x", "size": 1, "uploadId": UPLOAD_ID, "pages": 0},
        {"name": "a", "mime": "x", "size": 1, "uploadId": UPLOAD_ID, "error": "boom"},
    ):
        with pytest.raises(ValidationError):
            NativeDocument.model_validate(bad)


def test_native_document_accepts_the_uppercase_uuid_of_ios() -> None:
    doc = NativeDocument.model_validate(
        {"name": "a", "mime": "x", "size": 1, "uploadId": UPLOAD_ID.upper()}
    )
    assert doc.upload_id == UPLOAD_ID.upper()


def test_native_document_size_limit_is_the_contract_limit() -> None:
    base = {"name": "a.pdf", "mime": "application/pdf", "uploadId": UPLOAD_ID}
    NativeDocument.model_validate({**base, "size": MAX_NATIVE_DOCUMENT_BYTES})
    with pytest.raises(ValidationError):
        NativeDocument.model_validate({**base, "size": MAX_NATIVE_DOCUMENT_BYTES + 1})
    too_large = NativeDocument.model_validate(
        {**base, "size": MAX_NATIVE_DOCUMENT_BYTES + 1, "error": "tooLarge"}
    )
    assert too_large.error == "tooLarge"


def test_native_document_data_is_base64_and_decodes() -> None:
    base = {"name": "a.txt", "mime": "text/plain", "size": 11, "uploadId": UPLOAD_ID}
    doc = NativeDocument.model_validate({**base, "data": "aGVsbG8gd29ybGQ="})
    assert doc.content() == b"hello world"
    assert NativeDocument.model_validate(base).content() is None
    with pytest.raises(ValidationError):
        NativeDocument.model_validate({**base, "data": "not base64!"})


def test_native_document_upload_keeps_a_null_body() -> None:
    doc = NativeDocument.model_validate(
        {
            "name": "a.pdf",
            "mime": "application/pdf",
            "size": 1,
            "uploadId": UPLOAD_ID,
            "upload": {"status": 200, "body": None},
        }
    )
    assert doc.upload is not None and doc.upload.body is None
    with pytest.raises(ValidationError):
        NativeDocument.model_validate(
            {"name": "a", "mime": "x", "size": 1, "uploadId": UPLOAD_ID, "upload": {"status": 200}}
        )


def test_native_document_works_as_a_request_body_type() -> None:
    adapter = TypeAdapter(list[NativeDocument])
    docs = adapter.validate_python(
        [{"name": "a.pdf", "mime": "application/pdf", "size": 1, "uploadId": UPLOAD_ID}]
    )
    assert adapter.dump_python(docs, mode="json", by_alias=True, exclude_unset=True) == [
        {"name": "a.pdf", "mime": "application/pdf", "size": 1, "uploadId": UPLOAD_ID}
    ]


def test_context_is_limited_to_4096_bytes_serialized() -> None:
    adapter = TypeAdapter(NativeDocumentContext)
    fits = {"t": "x" * (4096 - 8)}  # {"t":"…"} is 8 bytes around the text
    assert adapter.validate_python(fits) == fits
    with pytest.raises(ValidationError, match="4097 bytes"):
        adapter.validate_python({"t": "x" * (4096 - 7)})
    # Bytes, not characters: "ä" is two bytes.
    with pytest.raises(ValidationError):
        adapter.validate_python({"t": "ä" * 2045})
    with pytest.raises(ValidationError):
        adapter.validate_python(["not", "an", "object"])
    assert check_document_context({}) == {}
