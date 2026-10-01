from __future__ import annotations

import httpx
import pytest
from bmsdna.app_native import (
    ReceivedDocument,
    WidgetRequestContext,
    create_document_router,
    insecure_no_auth,
)
from fastapi import FastAPI


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
