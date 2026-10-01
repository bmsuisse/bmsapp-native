from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    Approval,
    ApprovalDecisionReceived,
    ApprovalDecisionResult,
    ApprovalDetail,
    WidgetRequestContext,
    build_approvals_update_message,
    create_approvals_router,
    insecure_no_auth,
)
from fastapi import FastAPI, HTTPException, Request


def _approval(**overrides: Any) -> Approval:
    fields: dict[str, Any] = {
        "id": "vac-17",
        "title": "Vacation request",
        "subtitle": "Anna Muster · November 3–7",
        "amount": "5 days",
        "due_at": datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        "details": [ApprovalDetail(label="Deputy", value="Beat Beispiel")],
        "reject_comment": "required",
        "biometric": True,
    }
    return Approval(**(fields | overrides))


async def _no_decision(body: ApprovalDecisionReceived, context: WidgetRequestContext) -> None:
    return None


@pytest.mark.asyncio
async def test_feed_serializes_by_alias_and_drops_none() -> None:
    seen: list[WidgetRequestContext] = []

    async def get_approvals(context: WidgetRequestContext) -> list[Approval]:
        seen.append(context)
        return [_approval()]

    app = FastAPI()
    app.include_router(
        create_approvals_router(
            get_approvals=get_approvals, on_decision=_no_decision, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/approvals", params={"device_id": "dev-1"})

    assert response.status_code == 200
    assert response.json() == {
        "approvals": [
            {
                "id": "vac-17",
                "title": "Vacation request",
                "subtitle": "Anna Muster · November 3–7",
                "amount": "5 days",
                "dueAt": "2026-10-01T12:00:00Z",
                "details": [{"label": "Deputy", "value": "Beat Beispiel"}],
                "rejectComment": "required",
                "biometric": True,
            }
        ]
    }
    assert seen[0].device_id == "dev-1"


@pytest.mark.asyncio
async def test_decision_forwards_payload_and_returns_result() -> None:
    received: list[ApprovalDecisionReceived] = []

    async def on_decision(
        body: ApprovalDecisionReceived, context: WidgetRequestContext
    ) -> ApprovalDecisionResult:
        received.append(body)
        return ApprovalDecisionResult(message="Rejected", approvals=[])

    async def get_approvals(context: WidgetRequestContext) -> list[Approval]:
        return []

    app = FastAPI()
    app.include_router(
        create_approvals_router(
            get_approvals=get_approvals, on_decision=on_decision, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/approval-decisions",
            json={
                "device_id": "dev-1",
                "approval_id": "vac-17",
                "decision": "reject",
                "comment": "Too short notice",
                "user_email": "manager@example.com",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Rejected", "approvals": []}
    assert received[0].decision == "reject"
    assert received[0].comment == "Too short notice"


@pytest.mark.asyncio
async def test_decision_without_result_is_plain_ok_and_rejects_unknown_decision() -> None:
    async def get_approvals(context: WidgetRequestContext) -> list[Approval]:
        return []

    app = FastAPI()
    app.include_router(
        create_approvals_router(
            get_approvals=get_approvals, on_decision=_no_decision, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post(
            "/api/approval-decisions",
            json={"device_id": "d", "approval_id": "a", "decision": "approve"},
        )
        invalid = await client.post(
            "/api/approval-decisions",
            json={"device_id": "d", "approval_id": "a", "decision": "maybe"},
        )

    assert ok.json() == {"ok": True}
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_router_respects_auth_dependency() -> None:
    async def require_user(request: Request) -> str:
        if request.headers.get("x-user") != "manager@example.com":
            raise HTTPException(status_code=401)
        return "manager@example.com"

    users: list[object] = []

    async def get_approvals(context: WidgetRequestContext) -> list[Approval]:
        users.append(context.user)
        return []

    app = FastAPI()
    app.include_router(
        create_approvals_router(
            get_approvals=get_approvals, on_decision=_no_decision, auth_dependency=require_user
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get("/api/approvals")
        allowed = await client.get("/api/approvals", headers={"x-user": "manager@example.com"})
        denied_decision = await client.post(
            "/api/approval-decisions",
            json={"device_id": "d", "approval_id": "a", "decision": "approve"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert denied_decision.status_code == 401
    assert users == ["manager@example.com"]


def test_approvals_update_message_is_silent_refresh() -> None:
    assert build_approvals_update_message(webapp_id="hr-tool") == {
        "aps": {"content-available": 1},
        "webapp_id": "hr-tool",
        "approvals_refresh": True,
    }
