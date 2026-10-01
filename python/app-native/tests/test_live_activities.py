from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    ATTRIBUTES_TYPE,
    LiveActivityAttributes,
    LiveActivityState,
    LiveActivityTokenReceived,
    WidgetRequestContext,
    build_live_activity_message,
    build_live_activity_start_message,
    create_live_activity_router,
    insecure_no_auth,
    live_activity_topic,
)
from fastapi import FastAPI
from pydantic import ValidationError

PICKUP = datetime(2026, 9, 27, 14, 30, tzinfo=UTC)


def _state(**overrides: Any) -> LiveActivityState:
    fields: dict[str, Any] = {
        "title": "Order is being packed",
        "subtitle": "Zürich branch",
        "steps": ["Ordered", "Packed", "Ready for pickup"],
        "current_step": 1,
        "timer_end": PICKUP,
    }
    return LiveActivityState(**(fields | overrides))


def test_state_payload_uses_app_keys_and_unix_seconds() -> None:
    assert _state().to_payload() == {
        "title": "Order is being packed",
        "subtitle": "Zürich branch",
        "steps": ["Ordered", "Packed", "Ready for pickup"],
        "currentStep": 1,
        "timerEnd": PICKUP.timestamp(),
    }


def test_state_rejects_step_outside_steps() -> None:
    with pytest.raises(ValidationError):
        _state(current_step=3)


def test_update_message() -> None:
    message = build_live_activity_message(
        event="update",
        state=_state(),
        alert_title="Ready for pickup",
        alert_body="Counter 3",
        stale_at=PICKUP,
        timestamp=100,
    )

    assert message == {
        "aps": {
            "timestamp": 100,
            "event": "update",
            "content-state": _state().to_payload(),
            "alert": {"title": "Ready for pickup", "body": "Counter 3"},
            "stale-date": int(PICKUP.timestamp()),
        }
    }


def test_update_without_state_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_live_activity_message(event="update")


def test_end_message_with_dismissal() -> None:
    message = build_live_activity_message(event="end", dismiss_at=PICKUP, timestamp=100)
    assert message == {
        "aps": {"timestamp": 100, "event": "end", "dismissal-date": int(PICKUP.timestamp())}
    }


def test_start_message_uses_swift_attribute_keys_and_default_alert() -> None:
    attributes = LiveActivityAttributes(
        webapp_id="partner-tool",
        activity_id="A-123",
        webapp_name="Partner-Tool",
        path="/orders/A-123",
    )
    message = build_live_activity_start_message(
        attributes=attributes, state=_state(), timestamp=100
    )

    aps = message["aps"]
    assert aps["event"] == "start"
    assert aps["attributes-type"] == ATTRIBUTES_TYPE == "WebAppActivityAttributes"
    assert aps["attributes"] == {
        "webAppID": "partner-tool",
        "activityID": "A-123",
        "webAppName": "Partner-Tool",
        "path": "/orders/A-123",
    }
    assert aps["alert"] == {"title": "Order is being packed", "body": "Zürich branch"}


def test_live_activity_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APNS_BUNDLE_ID", "ch.example.webappshell")
    assert live_activity_topic() == "ch.example.webappshell.push-type.liveactivity"


@pytest.mark.asyncio
async def test_router_forwards_tokens() -> None:
    received: list[tuple[LiveActivityTokenReceived, WidgetRequestContext]] = []

    async def on_token(body: LiveActivityTokenReceived, context: WidgetRequestContext) -> None:
        received.append((body, context))

    app = FastAPI()
    app.include_router(
        create_live_activity_router(on_token_received=on_token, auth_dependency=insecure_no_auth),
        prefix="/api",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/live-activities",
            json={
                "device_id": "dev-1",
                "event": "token",
                "activity_id": "A-123",
                "push_token": "abc",
            },
        )
        invalid = await client.post(
            "/api/live-activities", json={"device_id": "dev-1", "event": "bogus"}
        )

    assert response.status_code == 204
    assert invalid.status_code == 422
    [(body, context)] = received
    assert body.activity_id == "A-123"
    assert body.push_token == "abc"
    assert context.device_id == "dev-1"
