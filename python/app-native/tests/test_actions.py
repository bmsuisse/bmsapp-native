from __future__ import annotations

import httpx
import pytest
from bmsdna.app_native import (
    NotificationActionReceived,
    WidgetRequestContext,
    build_alert_message,
    build_critical_alert_message,
    create_notification_action_router,
    insecure_no_auth,
)
from fastapi import FastAPI


def test_build_alert_message_includes_custom_data_and_actions() -> None:
    message = build_alert_message(
        title="New order",
        body="...",
        data={
            "path": "/orders/123",
            "order_id": "123",
            "actions": [
                {"id": "confirm", "title": "Confirm"},
                {"id": "reject", "title": "Decline"},
            ],
        },
    )

    assert message["aps"]["alert"] == {"title": "New order", "body": "..."}
    assert message["path"] == "/orders/123"
    assert message["order_id"] == "123"
    assert message["actions"] == [
        {"id": "confirm", "title": "Confirm"},
        {"id": "reject", "title": "Decline"},
    ]


def test_build_alert_message_without_data() -> None:
    message = build_alert_message(title="Hello", body="Test")
    assert message == {"aps": {"alert": {"title": "Hello", "body": "Test"}, "sound": "default"}}


@pytest.mark.asyncio
async def test_notification_action_router_forwards_to_callback() -> None:
    received: list[NotificationActionReceived] = []

    async def on_action(body: NotificationActionReceived, context: WidgetRequestContext) -> None:
        received.append(body)

    app = FastAPI()
    app.include_router(
        create_notification_action_router(
            on_action_received=on_action, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/notification-actions",
            json={
                "device_id": "abc",
                "action": "confirm",
                "data": {"order_id": "123"},
            },
        )

    assert response.status_code == 200
    assert received[0].action == "confirm"
    assert received[0].data == {"order_id": "123"}


def test_build_alert_message_time_sensitive_keeps_normal_sound() -> None:
    message = build_alert_message(
        title="Delivery", body="Driver is waiting", interruption_level="time-sensitive"
    )
    assert message["aps"]["interruption-level"] == "time-sensitive"
    assert message["aps"]["sound"] == "default"


def test_build_critical_alert_message_sets_critical_sound_and_ack() -> None:
    message = build_critical_alert_message(
        webapp_id="safety",
        title="Evacuation",
        body="Please leave building A immediately.",
        acknowledge_label="I am safe",
        volume=2.0,
        data={"alert_id": "evac-1"},
    )

    assert message["aps"]["interruption-level"] == "critical"
    # Volume is clamped to 0.0 to 1.0.
    assert message["aps"]["sound"] == {"critical": 1, "name": "default", "volume": 1.0}
    assert message["webapp_id"] == "safety"
    assert message["ack_label"] == "I am safe"
    assert message["alert_id"] == "evac-1"


def test_build_critical_alert_message_without_ack_button() -> None:
    message = build_critical_alert_message(
        webapp_id="safety", title="Test", body="-", acknowledge_label=None
    )
    assert "ack_label" not in message
