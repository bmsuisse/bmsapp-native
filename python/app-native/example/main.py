"""Minimal example: shows how `bmsdna.app_native` is built into your own
FastAPI backend. Runs without Postgres/Docker — storage here is deliberately
in-memory only; in a real app you replace it with your own database.

Run:
    uv run --group dev granian --interface asgi example.main:app --port 8000 --reload

Try it:
    curl -X POST http://localhost:8000/api/devices \\
      -H "Content-Type: application/json" \\
      -d '{"device_id": "abc", "push_token": "<real-apns-token>"}'

    curl -X POST "http://localhost:8000/api/notify/abc?title=Hello&body=Test"

    # Dashboard widgets (feed + action), see docs/dashboard-widgets-guide.md:
    curl "http://localhost:8000/api/widgets?device_id=abc"
    curl -X POST http://localhost:8000/api/widget-actions \\
      -H "Content-Type: application/json" \\
      -d '{"device_id": "abc", "widget_id": "approvals", "action_id": "approve", "item_id": "A-1001"}'
    curl -X POST http://localhost:8000/api/widget-options \\
      -H "Content-Type: application/json" \\
      -d '{"device_id": "abc", "widget_id": "new-visit", "field_id": "customer", "query": "mus"}'

    # Live Activities, see docs/live-activities-guide.md: the app reports an
    # activity's token, then each call moves it one step further.
    curl -X POST http://localhost:8000/api/live-activities \\
      -H "Content-Type: application/json" \\
      -d '{"device_id": "abc", "event": "token", "activity_id": "A-123", "push_token": "<real-token>"}'
    curl -X POST "http://localhost:8000/api/orders/A-123/advance"
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from bmsdna.app_native import (
    ActionButton,
    ActionCondition,
    ActionData,
    ActionField,
    ActionOption,
    ActionPage,
    ActionWidget,
    ChartData,
    ChartPoint,
    ChartSeries,
    ChartWidget,
    DeviceRegistration,
    EntraTokenVerifier,
    EntraUser,
    KpiData,
    KpiWidget,
    ListData,
    ListItem,
    ListWidget,
    LiveActivityState,
    LiveActivityTokenReceived,
    LocationUpdate,
    NotificationActionReceived,
    ProgressData,
    ProgressWidget,
    ReceivedDocument,
    SignedSessionCookie,
    Trend,
    Widget,
    WidgetActionReceived,
    WidgetActionResult,
    WidgetOptionsRequest,
    WidgetRequestContext,
    create_document_router,
    create_entra_auth_dependency,
    create_ingest_router,
    create_live_activity_router,
    create_notification_action_router,
    create_widget_action_router,
    create_widget_feed_router,
    create_widget_options_router,
    insecure_no_auth,
    send_live_activity_end,
    send_live_activity_update,
    send_push,
    send_silent_push,
    send_widget_update,
)
from fastapi import FastAPI


@dataclass
class _Device:
    push_token: str | None = None
    user_email: str | None = None


# In a real app: replace with your own database.
_devices: dict[str, _Device] = {}
_locations: list[dict[str, Any]] = []


async def _on_device_registered(body: DeviceRegistration, context: WidgetRequestContext) -> None:
    device = _devices.setdefault(body.device_id, _Device())
    provided = body.model_fields_set
    if "push_token" in provided:
        device.push_token = body.push_token
    # Who it is comes from the verified token (`context.user`), never from
    # `body.user_email`: that is client input and anyone can send any address.
    if isinstance(context.user, EntraUser):
        device.user_email = context.user.email


async def _on_location_received(body: LocationUpdate, context: WidgetRequestContext) -> None:
    # Process it live here (e.g. compute "customers nearby", pass it on to
    # another system) or store it in your own DB — both are the job of your
    # app, not of the toolkit.
    _locations.append(body.model_dump())


async def _on_document_received(doc: ReceivedDocument, context: WidgetRequestContext) -> None:
    # In a real app: store in blob storage/DB. Only logged here.
    print(f"Document received: {doc.filename} ({len(doc.data)} bytes, kind={doc.metadata.kind})")


async def _on_notification_action(
    action: NotificationActionReceived, context: WidgetRequestContext
) -> None:
    # e.g. mark the referenced order as accepted/declined here.
    print(f"Notification action: {action.action} (data={action.data})")


# --- Dashboard widgets -----------------------------------------------------

# Pending approvals, in a real app from your database.
_approvals: dict[str, tuple[str, str]] = {
    "A-1001": ("Expenses M. Keller", "CHF 240"),
    "A-1002": ("Vacation request S. Frei", "Oct 12–16"),
}


def _approvals_widget() -> ListWidget:
    return ListWidget(
        id="approvals",
        title="Approvals",
        icon="checkmark.seal",
        path="/approvals",
        data=ListData(
            empty_text="All done",
            items=[
                ListItem(
                    id=approval_id,
                    title=title,
                    trailing=detail,
                    icon="doc.text",
                    path=f"/approvals/{approval_id}",
                    actions=[
                        ActionButton(id="approve", label="Approve"),
                        ActionButton(
                            id="reject",
                            label="Reject",
                            style="destructive",
                            confirm="Really reject?",
                        ),
                    ],
                )
                for approval_id, (title, detail) in _approvals.items()
            ],
        ),
    )


def _widgets() -> list[Widget]:
    now = datetime.now(UTC)
    return [
        KpiWidget(
            id="open-orders",
            title="Open orders",
            icon="shippingbox",
            required=True,  # mandatory widget: the user cannot hide it
            path="/orders",
            updated_at=now,
            expires_at=now + timedelta(hours=4),
            data=KpiData(
                value=12, unit="pcs", trend=Trend(direction="up", text="+3", positive=False)
            ),
        ),
        ProgressWidget(
            id="target",
            title="Monthly target",
            icon="target",
            data=ProgressData(value=68_000, total=100_000, caption="CHF revenue", style="ring"),
        ),
        ChartWidget(
            id="revenue",
            size="large",
            title="Revenue per month",
            data=ChartData(
                unit="CHF k",
                series=[
                    ChartSeries(
                        name="2026",
                        points=[
                            ChartPoint(x=m, y=y)
                            for m, y in [("Jan", 42), ("Feb", 51), ("Mar", 47), ("Apr", 63)]
                        ],
                    )
                ],
            ),
        ),
        _approvals_widget(),
        ActionWidget(
            id="quick-order",
            title="Quick order",
            icon="bolt",
            default_enabled=False,  # only visible once the user enables it
            data=ActionData(
                fields=[
                    ActionField(
                        id="article",
                        type="select",
                        label="Article",
                        required=True,
                        options=[
                            ActionOption(value="A1", label="M6 screws"),
                            ActionOption(value="A2", label="8 mm wall plugs"),
                        ],
                    ),
                    ActionField(id="qty", type="number", label="Quantity", required=True),
                ],
                buttons=[ActionButton(id="order", label="Order", icon="paperplane")],
            ),
        ),
        # Multi-page form with a search field and a lazily loaded select; the
        # options come from `_on_widget_options`.
        ActionWidget(
            id="new-visit",
            title="Log visit",
            icon="person.crop.circle.badge.plus",
            data=ActionData(
                text="Log a customer visit in three steps.",
                pages=[
                    ActionPage(
                        title="Customer",
                        fields=[
                            ActionField(
                                id="customer",
                                type="search",
                                label="Customer",
                                placeholder="Name or city",
                                required=True,
                            )
                        ],
                    ),
                    ActionPage(
                        title="Contact person",
                        text="Contacts of the selected customer.",
                        fields=[
                            ActionField(
                                id="contact",
                                type="select",
                                label="Contact",
                                remote=True,
                                required=True,
                            )
                        ],
                    ),
                    ActionPage(
                        title="Details",
                        fields=[
                            ActionField(id="date", type="date", label="Date"),
                            ActionField(id="note", type="text", label="Note"),
                            ActionField(id="followup", type="toggle", label="Follow-up"),
                            # Only visible when "Follow-up" is switched on.
                            ActionField(
                                id="followup_date",
                                type="date",
                                label="Follow-up on",
                                visible_if=ActionCondition(field="followup", equals=True),
                            ),
                        ],
                    ),
                ],
                buttons=[ActionButton(id="save", label="Save", icon="checkmark")],
            ),
        ),
    ]


async def _get_widgets(context: WidgetRequestContext) -> list[Widget]:
    # `context.user` would be the logged-in user from your auth_dependency
    # here, e.g. to return only their approvals.
    return _widgets()


# In a real app: Meilisearch, SQL full-text search or similar.
_customers = {
    "K-1": ("Muster AG", "Zürich", ["Anna Muster", "Beat Keller"]),
    "K-2": ("Beispiel GmbH", "Bern", ["Claudia Frei"]),
    "K-3": ("Holz & Co.", "Luzern", ["Daniel Holz", "Eva Meier"]),
}


async def _on_widget_options(
    req: WidgetOptionsRequest, context: WidgetRequestContext
) -> list[ActionOption]:
    if req.field_id == "customer":
        query = req.query.casefold()
        return [
            ActionOption(value=cid, label=name, subtitle=city)
            for cid, (name, city, _) in _customers.items()
            if query in name.casefold() or query in city.casefold()
        ]
    if req.field_id == "contact":
        # Depends on the customer selected on page 1.
        _, _, contacts = _customers.get(str(req.values.get("customer")), ("", "", []))
        return [ActionOption(value=name) for name in contacts]
    return []


async def _on_widget_action(
    action: WidgetActionReceived, context: WidgetRequestContext
) -> WidgetActionResult | None:
    if action.widget_id == "approvals" and action.item_id in _approvals:
        title, _ = _approvals.pop(action.item_id)
        verb = "approved" if action.action_id == "approve" else "rejected"
        # Only send the list again, the entry disappears immediately.
        return WidgetActionResult(message=f"{title} {verb}", widget=_approvals_widget())
    if action.widget_id == "new-visit":
        return WidgetActionResult(message=f"Visit with {action.values.get('contact')} saved")
    if action.widget_id == "quick-order":
        return WidgetActionResult(
            message=f"Ordered: {action.values.get('qty')} × {action.values.get('article')}"
        )
    return WidgetActionResult(ok=False, message="Unknown action")


# --- Live Activities -------------------------------------------------------

# Push token per activity (here: per order), in a real app in your
# database, e.g. per (device_id, activity_id).
_activity_tokens: dict[str, str] = {}
_order_steps = ["Ordered", "Packed", "Ready for pickup"]
_order_progress: dict[str, int] = {}


async def _on_live_activity_token(
    body: LiveActivityTokenReceived, context: WidgetRequestContext
) -> None:
    if body.event == "token" and body.activity_id and body.push_token:
        _activity_tokens[body.activity_id] = body.push_token
    elif body.event == "ended" and body.activity_id:
        _activity_tokens.pop(body.activity_id, None)


def _create_auth() -> Any:
    # Without configuration the example runs without login so you can try it
    # with curl. With ENTRA_TENANT_ID, ENTRA_AUDIENCE and SESSION_SECRET it
    # checks the Entra token of the app and exchanges it for a session cookie,
    # see docs/entra-token-guide.md. In a real backend you pass your own
    # check if you prefer: a FastAPI dependency that raises 401/403 or returns
    # the user.
    if not os.environ.get("ENTRA_TENANT_ID"):
        return insecure_no_auth
    return create_entra_auth_dependency(
        EntraTokenVerifier.from_env(),
        session=SignedSessionCookie(secret=os.environ["SESSION_SECRET"]),
    )


_auth = _create_auth()

app = FastAPI(title="bmsdna-app-native example")
app.include_router(
    create_ingest_router(
        on_device_registered=_on_device_registered,
        on_location_received=_on_location_received,
        auth_dependency=_auth,
    ),
    prefix="/api",
)
app.include_router(
    create_document_router(on_document_received=_on_document_received, auth_dependency=_auth),
    prefix="/api",
)
app.include_router(
    create_notification_action_router(
        on_action_received=_on_notification_action, auth_dependency=_auth
    ),
    prefix="/api",
)
app.include_router(
    create_widget_feed_router(get_widgets=_get_widgets, auth_dependency=_auth),
    prefix="/api",
)
app.include_router(
    create_widget_action_router(on_action_received=_on_widget_action, auth_dependency=_auth),
    prefix="/api",
)
app.include_router(
    create_widget_options_router(on_options_requested=_on_widget_options, auth_dependency=_auth),
    prefix="/api",
)


app.include_router(
    create_live_activity_router(on_token_received=_on_live_activity_token, auth_dependency=_auth),
    prefix="/api",
)


@app.post("/api/orders/{order_id}/advance")
async def advance_order(order_id: str) -> dict[str, Any]:
    token = _activity_tokens.get(order_id)
    if token is None:
        return {"sent": False, "detail": "No Live Activity for this order"}
    step = min(_order_progress.get(order_id, 0) + 1, len(_order_steps) - 1)
    _order_progress[order_id] = step
    state = LiveActivityState(
        title="Ready for pickup" if step == len(_order_steps) - 1 else "Order is being packed",
        subtitle="Zürich branch · Counter 3",
        status=_order_steps[step],
        steps=_order_steps,
        current_step=step,
        icon="checkmark.circle.fill" if step == len(_order_steps) - 1 else None,
        tint="#2e7d32" if step == len(_order_steps) - 1 else None,
    )
    if step == len(_order_steps) - 1:
        # Last step: update with an alert, gone after 30 minutes.
        sent, detail = await send_live_activity_update(
            push_token=token, state=state, alert_title=state.title
        )
        await send_live_activity_end(
            push_token=token, state=state, dismiss_at=datetime.now(UTC) + timedelta(minutes=30)
        )
    else:
        sent, detail = await send_live_activity_update(push_token=token, state=state)
    return {"sent": sent, "detail": detail}


@app.get("/api/livez")
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/notify/{device_id}")
async def notify(device_id: str, title: str, body: str) -> dict[str, Any]:
    """Shows the one-call push: `send_push()` directly from your own code."""
    device = _devices.get(device_id)
    if device is None or not device.push_token:
        return {"sent": False, "detail": "unknown device or no push token yet"}
    try:
        sent, detail = await send_push(device_token=device.push_token, title=title, body=body)
    except RuntimeError as e:
        # e.g. APNS_KEY not set yet — only logged in this example; in a
        # real app you would leave this to your own error handling.
        return {"sent": False, "detail": str(e)}
    return {"sent": sent, "detail": detail}


@app.post("/api/notify/{device_id}/order-request")
async def notify_order_request(device_id: str, order_id: str) -> dict[str, Any]:
    """Shows a push with buttons in the notifications tab of the iOS app —
    defined entirely via `data={"actions": [...]}`, no app-side
    configuration needed."""
    device = _devices.get(device_id)
    if device is None or not device.push_token:
        return {"sent": False, "detail": "unknown device or no push token yet"}
    try:
        sent, detail = await send_push(
            device_token=device.push_token,
            title="New order",
            body=f"Order {order_id} is awaiting confirmation",
            data={
                "order_id": order_id,
                "actions": [
                    {"id": "confirm", "title": "Accept"},
                    {"id": "reject", "title": "Decline"},
                ],
            },
        )
    except RuntimeError as e:
        return {"sent": False, "detail": str(e)}
    return {"sent": sent, "detail": detail}


@app.post("/api/notify/{device_id}/refresh")
async def notify_refresh(device_id: str) -> dict[str, Any]:
    """Shows the silent push: triggers a WebView reload in the app without
    the user seeing anything. The app additionally throttles the actual
    processing itself (default at most every 15 minutes)."""
    device = _devices.get(device_id)
    if device is None or not device.push_token:
        return {"sent": False, "detail": "unknown device or no push token yet"}
    try:
        sent, detail = await send_silent_push(device_token=device.push_token)
    except RuntimeError as e:
        return {"sent": False, "detail": str(e)}
    return {"sent": sent, "detail": detail}


@app.post("/api/notify/{device_id}/widgets")
async def notify_widgets(device_id: str) -> dict[str, Any]:
    """Shows `send_widget_update()`: updates the dashboard on the device via
    silent push, without the user opening the web app. `webapp_id` must
    match the `id` of this web app in the app."""
    device = _devices.get(device_id)
    if device is None or not device.push_token:
        return {"sent": False, "detail": "unknown device or no push token yet"}
    try:
        sent, detail = await send_widget_update(
            device_token=device.push_token, webapp_id="partner-tool", widgets=_widgets()
        )
    except RuntimeError as e:
        return {"sent": False, "detail": str(e)}
    return {"sent": sent, "detail": detail}
