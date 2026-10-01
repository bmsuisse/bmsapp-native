"""Live Activities: ongoing processes live on the Lock Screen and in the
Dynamic Island, e.g. "Order is being packed" with progress or
"Ready for pickup from 14:30" with a countdown.

The layout is native and the same for all web apps; you only supply the data
(`LiveActivityState`). Flow:

1. **Start**: from the open web app via
   `BMSNative.call('startLiveActivity', {id, state})`, or from iOS 17.2 on
   entirely without the app via `send_live_activity_start()` with the
   push-to-start token.
2. **Token**: The app reports a separate push token for each activity to
   `POST <prefix>/live-activities` (`create_live_activity_router`), plus
   the push-to-start token once per device. You have to store them yourself.
3. **Update/end**: `send_live_activity_update()` or
   `send_live_activity_end()` with the activity's token.

Details and limits (active for at most 8 hours, approx. 4 KB per update) are
in `docs/live-activities-guide.md`.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from aioapns import NotificationRequest
from aioapns.common import PushType
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
from pydantic.alias_generators import to_camel

from .widgets import WidgetRequestContext

#: Name of the activity's Swift type in the app — required for push-to-start.
ATTRIBUTES_TYPE = "WebAppActivityAttributes"


class LiveActivityState(BaseModel):
    """The current state of a Live Activity (`content-state`).

    Only `title` is required. Progress either as `progress` (0…1) or as
    named `steps` with `current_step`.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    #: Main line, e.g. "Order is being packed".
    title: str = Field(min_length=1)
    #: Second line, e.g. "Zürich branch · Counter 3".
    subtitle: str | None = None
    #: Short status for the compact Dynamic Island, e.g. "Ready" —
    #: there is only room for a few characters there.
    status: str | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    #: Named steps, e.g. ["Ordered", "Packed", "Ready for pickup"].
    steps: list[str] | None = Field(default=None, max_length=5)
    #: Index into `steps`, 0-based.
    current_step: int | None = Field(default=None, ge=0)
    #: Shows a countdown to this point in time.
    timer_end: datetime | None = None
    #: SF Symbol and hex color for this state only, e.g. a green
    #: checkmark as soon as something is ready.
    icon: str | None = None
    tint: str | None = None

    @model_validator(mode="after")
    def _check_step(self) -> LiveActivityState:
        if self.current_step is not None and self.steps and self.current_step >= len(self.steps):
            raise ValueError("current_step is outside of steps")
        return self

    @field_serializer("timer_end")
    def _serialize_timer_end(self, value: datetime | None) -> float | None:
        # The app expects Unix seconds (see WebAppActivityAttributes).
        return value.timestamp() if value is not None else None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class LiveActivityAttributes(BaseModel):
    """The fixed details of an activity — only for
    `send_live_activity_start()`. When starting via the bridge, the app sets
    them itself."""

    #: `id` of your web app in the app.
    webapp_id: str = Field(serialization_alias="webAppID")
    #: Your `id` for the activity, e.g. the order number.
    activity_id: str = Field(serialization_alias="activityID", min_length=1)
    #: Display name above the title, normally the name of your web app.
    webapp_name: str = Field(serialization_alias="webAppName")
    icon: str | None = None
    tint: str | None = None
    #: Tapping the activity opens your web app at this path.
    path: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class LiveActivityTokenReceived(BaseModel):
    """Payload of `POST <prefix>/live-activities`."""

    device_id: str
    #: - `token`: push token of an activity (`activity_id`), for
    #:   `send_live_activity_update`/`_end`. Can change while the activity
    #:   is running, always use the most recently reported one.
    #: - `push_to_start_token`: the device's token for
    #:   `send_live_activity_start` (from iOS 17.2 on), without `activity_id`.
    #: - `ended`: The activity is over (swiped away by the user or
    #:   ended) — you can delete its token.
    event: Literal["token", "push_to_start_token", "ended"]
    activity_id: str | None = None
    push_token: str | None = None
    #: See `WidgetActionReceived.user_email`.
    user_email: str | None = None


LiveActivityCallback = Callable[[LiveActivityTokenReceived, WidgetRequestContext], Awaitable[None]]


def create_live_activity_router(
    *,
    on_token_received: LiveActivityCallback,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/live-activities`.

    As with the other routers there is no storage of its own: keep track of
    the tokens in your callback, e.g. per `(device_id, activity_id)`.
    """
    router = APIRouter()
    auth = auth_dependency

    @router.post("/live-activities", status_code=204)
    async def receive_token(
        body: LiveActivityTokenReceived, request: Request, user: Any = Depends(auth)
    ) -> None:
        await on_token_received(
            body, WidgetRequestContext(device_id=body.device_id, user=user, request=request)
        )

    return router


# --- Payloads --------------------------------------------------------------


def _alert(title: str, body: str | None) -> dict[str, Any]:
    return {"title": title, "body": body or ""}


def build_live_activity_message(
    *,
    event: Literal["update", "end"],
    state: LiveActivityState | None = None,
    alert_title: str | None = None,
    alert_body: str | None = None,
    stale_at: datetime | None = None,
    dismiss_at: datetime | None = None,
    timestamp: int | None = None,
) -> dict[str, Any]:
    """Pure payload construction for update/end, testable without APNs
    credentials."""
    if event == "update" and state is None:
        raise ValueError("An update needs a state")
    aps: dict[str, Any] = {"timestamp": timestamp or int(time.time()), "event": event}
    if state is not None:
        aps["content-state"] = state.to_payload()
    if alert_title:
        aps["alert"] = _alert(alert_title, alert_body)
    if stale_at is not None:
        aps["stale-date"] = int(stale_at.timestamp())
    if dismiss_at is not None:
        aps["dismissal-date"] = int(dismiss_at.timestamp())
    return {"aps": aps}


def build_live_activity_start_message(
    *,
    attributes: LiveActivityAttributes,
    state: LiveActivityState,
    alert_title: str | None = None,
    alert_body: str | None = None,
    stale_at: datetime | None = None,
    timestamp: int | None = None,
) -> dict[str, Any]:
    """Pure payload construction for push-to-start. According to Apple, a
    start always needs an `alert` — without one of your own, the toolkit
    uses the state's title and subtitle."""
    aps: dict[str, Any] = {
        "timestamp": timestamp or int(time.time()),
        "event": "start",
        "content-state": state.to_payload(),
        "attributes-type": ATTRIBUTES_TYPE,
        "attributes": attributes.to_payload(),
        "alert": _alert(alert_title or state.title, alert_body if alert_title else state.subtitle),
    }
    if stale_at is not None:
        aps["stale-date"] = int(stale_at.timestamp())
    return {"aps": aps}


# --- Delivery --------------------------------------------------------------


async def _send(push_token: str, message: dict[str, Any], priority: int) -> tuple[bool, str | None]:
    from .apns import _get_client, live_activity_topic

    client = _get_client()
    request = NotificationRequest(
        device_token=push_token,
        message=message,
        push_type=PushType.LIVEACTIVITY,
        priority=priority,
        apns_topic=live_activity_topic(),
    )
    response = await client.send_notification(request)
    return response.is_successful, getattr(response, "description", None)


async def send_live_activity_update(
    *,
    push_token: str,
    state: LiveActivityState,
    alert_title: str | None = None,
    alert_body: str | None = None,
    stale_at: datetime | None = None,
    priority: Literal[5, 10] = 10,
) -> tuple[bool, str | None]:
    """New state for a running activity (`push_token` from the activity's
    `token` event).

    With `alert_title` the activity lights up briefly (sound, the Dynamic
    Island expands) — only use it for important changes. `priority=5`
    for unimportant intermediate states: otherwise iOS will eventually
    throttle updates with priority 10. `stale_at`: from then on the state
    counts as outdated.

    Return value as for `send_push`. On `sent=False` with a reason from
    `PERMANENTLY_INVALID_TOKEN_REASONS`, the activity is over.
    """
    message = build_live_activity_message(
        event="update",
        state=state,
        alert_title=alert_title,
        alert_body=alert_body,
        stale_at=stale_at,
    )
    return await _send(push_token, message, priority)


async def send_live_activity_end(
    *,
    push_token: str,
    state: LiveActivityState | None = None,
    dismiss_at: datetime | None = None,
) -> tuple[bool, str | None]:
    """Ends an activity. With `state` it shows the final state until it
    disappears (e.g. "Picked up"). Without `dismiss_at` iOS keeps it on the
    Lock Screen for up to 4 more hours; with a point in time in the past it
    disappears immediately."""
    message = build_live_activity_message(event="end", state=state, dismiss_at=dismiss_at)
    return await _send(push_token, message, 10)


async def send_live_activity_start(
    *,
    push_to_start_token: str,
    attributes: LiveActivityAttributes,
    state: LiveActivityState,
    alert_title: str | None = None,
    alert_body: str | None = None,
    stale_at: datetime | None = None,
) -> tuple[bool, str | None]:
    """Starts an activity entirely without the app (from iOS 17.2 on, with
    the token from the `push_to_start_token` event). Afterwards the app
    reports the new activity's token as a `token` event as usual — only
    then do updates work."""
    message = build_live_activity_start_message(
        attributes=attributes,
        state=state,
        alert_title=alert_title,
        alert_body=alert_body,
        stale_at=stale_at,
    )
    return await _send(push_to_start_token, message, 10)
