from __future__ import annotations

from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    NativeFileRef,
    ReceivedDocument,
    WidgetRequestContext,
    create_document_router,
    insecure_no_auth,
    resolve_file_refs,
)
from fastapi import FastAPI, HTTPException


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
