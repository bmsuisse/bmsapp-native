"""Router for interactive push actions (buttons in the notifications tab of
the iOS app, e.g. "Accept"/"Decline" — see
`send_push(data={"actions": [...]})` in `apns.py`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .widgets import WidgetRequestContext


class NotificationActionReceived(BaseModel):
    device_id: str
    # The action the user tapped — the `id` from the `"actions"` entry that
    # `send_push(data={"actions": [...]})` sent along, e.g.
    # "confirm"/"reject".
    action: str
    # The custom data from the original push (e.g. an order ID), so you know
    # what the action refers to.
    data: dict[str, Any] | None = None


NotificationActionCallback = Callable[
    [NotificationActionReceived, WidgetRequestContext], Awaitable[None]
]


def create_notification_action_router(
    *,
    on_action_received: NotificationActionCallback,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/notification-actions`.

    Same as for devices/locations/documents: no storage of its own, the
    action goes unchanged to your callback with the request context — e.g. to
    mark an order as accepted. Check that `context.user` may act on what the
    action refers to: `data` comes from the device.
    """
    router = APIRouter()

    @router.post("/notification-actions")
    async def receive_action(
        body: NotificationActionReceived, request: Request, user: Any = Depends(auth_dependency)
    ) -> dict[str, bool]:
        await on_action_received(
            body, WidgetRequestContext(device_id=body.device_id, user=user, request=request)
        )
        return {"ok": True}

    return router
