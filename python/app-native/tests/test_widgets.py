from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    MAX_INLINE_WIDGETS_BYTES,
    ActionButton,
    ActionCondition,
    ActionData,
    ActionField,
    ActionOption,
    ActionPage,
    KpiData,
    KpiWidget,
    ListData,
    ListItem,
    ListWidget,
    NewsData,
    NewsItem,
    NewsWidget,
    Trend,
    Widget,
    WidgetActionReceived,
    WidgetActionResult,
    WidgetFeed,
    WidgetOptionsRequest,
    WidgetOptionsResult,
    WidgetRequestContext,
    build_widget_update_message,
    create_widget_action_router,
    create_widget_feed_router,
    create_widget_options_router,
    dump_widgets,
    insecure_no_auth,
)
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError


def _kpi(**overrides: Any) -> KpiWidget:
    fields: dict[str, Any] = {
        "id": "open-orders",
        "title": "Open orders",
        "default_enabled": False,
        "updated_at": datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
        "data": KpiData(value=12, unit="pcs", trend=Trend(direction="up", text="+3")),
    }
    return KpiWidget(**(fields | overrides))


def test_dump_widgets_uses_camel_case_and_drops_none() -> None:
    [payload] = dump_widgets([_kpi(required=True)])

    assert payload == {
        "id": "open-orders",
        "kind": "kpi",
        "title": "Open orders",
        "required": True,
        "defaultEnabled": False,
        "updatedAt": "2026-09-24T08:00:00Z",
        "data": {"value": 12, "unit": "pcs", "trend": {"direction": "up", "text": "+3"}},
    }


def test_feed_parses_app_format_with_discriminator() -> None:
    feed = WidgetFeed.model_validate(
        {
            "schema": 1,
            "widgets": [
                {"id": "a", "kind": "kpi", "data": {"value": "CHF 1'200"}},
                {
                    "id": "b",
                    "kind": "list",
                    "data": {"maxVisible": 3, "items": [{"id": "1", "title": "Entry"}]},
                },
            ],
        }
    )

    assert isinstance(feed.widgets[0], KpiWidget)
    assert isinstance(feed.widgets[1], ListWidget)
    assert feed.widgets[1].data.max_visible == 3


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WidgetFeed.model_validate({"widgets": [{"id": "a", "kind": "gauge", "data": {}}]})


def test_news_widget_serializes_in_app_format() -> None:
    widget = NewsWidget(
        id="intranet-news",
        size="xlarge",
        title="News",
        data=NewsData(
            items=[
                NewsItem(
                    id="42",
                    title="New location",
                    text="Now also in Winterthur from October.",
                    image_url="/SiteAssets/location.jpg",
                    path="/SitePages/New-Location.aspx",
                    date=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
                    channels=["HR"],
                )
            ]
        ),
    )

    [payload] = dump_widgets([widget])

    assert payload["kind"] == "news"
    assert payload["size"] == "xlarge"
    assert payload["data"] == {
        "items": [
            {
                "id": "42",
                "title": "New location",
                "text": "Now also in Winterthur from October.",
                "imageUrl": "/SiteAssets/location.jpg",
                "path": "/SitePages/New-Location.aspx",
                "date": "2026-09-20T08:00:00Z",
                "channels": ["HR"],
            }
        ]
    }


def test_feed_parses_news_widget() -> None:
    feed = WidgetFeed.model_validate(
        {
            "widgets": [
                {
                    "id": "n",
                    "kind": "news",
                    "data": {"items": [{"id": "1", "title": "Hello", "imageUrl": "x.jpg"}]},
                }
            ]
        }
    )

    [widget] = feed.widgets
    assert isinstance(widget, NewsWidget)
    assert widget.data.items[0].image_url == "x.jpg"


def test_news_item_requires_title() -> None:
    with pytest.raises(ValidationError):
        NewsItem(id="1", title="")


def test_widget_id_must_not_contain_slash() -> None:
    # The app namespaces widgets as "<webappId>/<id>".
    with pytest.raises(ValidationError):
        _kpi(id="a/b")


def test_widget_update_message_inlines_small_payload() -> None:
    message = build_widget_update_message(webapp_id="partner-tool", widgets=[_kpi()])

    assert message["aps"] == {"content-available": 1}
    assert message["webapp_id"] == "partner-tool"
    assert message["widgets"][0]["id"] == "open-orders"
    assert "widgets_refresh" not in message


def test_widget_update_message_falls_back_to_refresh_when_too_large() -> None:
    items = [ListItem(id=str(i), title="x" * 50) for i in range(200)]
    big = ListWidget(id="big", data=ListData(items=items))

    message = build_widget_update_message(webapp_id="partner-tool", widgets=[big])

    assert "widgets" not in message
    assert message["widgets_refresh"] is True
    assert MAX_INLINE_WIDGETS_BYTES < 4096


def test_widget_update_message_without_widgets_requests_refresh() -> None:
    message = build_widget_update_message(webapp_id="partner-tool")
    assert message == {
        "aps": {"content-available": 1},
        "webapp_id": "partner-tool",
        "widgets_refresh": True,
    }


@pytest.mark.asyncio
async def test_feed_router_passes_context_and_serializes_by_alias() -> None:
    seen: list[WidgetRequestContext] = []

    async def get_widgets(context: WidgetRequestContext) -> list[Widget]:
        seen.append(context)
        return [_kpi()]

    async def auth(request: Request) -> str:
        return "anna@example.com"

    app = FastAPI()
    app.include_router(
        create_widget_feed_router(get_widgets=get_widgets, auth_dependency=auth), prefix="/api"
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/widgets", params={"device_id": "abc"})

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == 1
    assert body["widgets"][0]["defaultEnabled"] is False
    assert "path" not in body["widgets"][0]
    assert seen[0].device_id == "abc"
    assert seen[0].user == "anna@example.com"


@pytest.mark.asyncio
async def test_feed_router_respects_auth_dependency() -> None:
    async def get_widgets(context: WidgetRequestContext) -> list[Widget]:
        return []

    async def auth() -> None:
        raise HTTPException(status_code=401)

    app = FastAPI()
    app.include_router(
        create_widget_feed_router(get_widgets=get_widgets, auth_dependency=auth), prefix="/api"
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/widgets")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_action_router_forwards_and_returns_result() -> None:
    received: list[WidgetActionReceived] = []

    async def on_action(
        action: WidgetActionReceived, context: WidgetRequestContext
    ) -> WidgetActionResult:
        received.append(action)
        return WidgetActionResult(
            message="Approved",
            open_path="/approvals",
            widget=ListWidget(id="approvals", data=ListData(items=[])),
        )

    app = FastAPI()
    app.include_router(
        create_widget_action_router(on_action_received=on_action, auth_dependency=insecure_no_auth),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/widget-actions",
            json={
                "device_id": "abc",
                "widget_id": "approvals",
                "action_id": "approve",
                "item_id": "A-1001",
                "values": {"qty": 3, "express": True},
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "message": "Approved",
        "widget": {
            "id": "approvals",
            "kind": "list",
            "title": "",
            "required": False,
            "defaultEnabled": True,
            "data": {"items": []},
        },
        "openPath": "/approvals",
    }
    assert received[0].item_id == "A-1001"
    assert received[0].values == {"qty": 3, "express": True}


@pytest.mark.asyncio
async def test_action_router_defaults_to_ok_when_callback_returns_none() -> None:
    async def on_action(action: WidgetActionReceived, context: WidgetRequestContext) -> None:
        return None

    app = FastAPI()
    app.include_router(
        create_widget_action_router(on_action_received=on_action, auth_dependency=insecure_no_auth),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/widget-actions",
            json={"device_id": "abc", "widget_id": "quick-order", "action_id": "order"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_action_widget_requires_a_button() -> None:
    with pytest.raises(ValidationError):
        ActionData(buttons=[])
    assert ActionData(buttons=[ActionButton(id="go", label="Go")]).buttons[0].style == "primary"


def test_action_pages_serialize_in_app_format() -> None:
    data = ActionData(
        pages=[
            ActionPage(
                title="Customer",
                fields=[ActionField(id="customer", type="search", label="Customer", required=True)],
            ),
            ActionPage(
                title="Details",
                fields=[
                    ActionField(
                        id="contact",
                        type="select",
                        remote=True,
                        min_query_length=0,
                        value_label="—",
                    )
                ],
            ),
        ],
        buttons=[ActionButton(id="create", label="Create")],
    )

    dumped = data.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert dumped["pages"][0]["fields"][0]["type"] == "search"
    assert dumped["pages"][1]["fields"][0]["minQueryLength"] == 0
    assert dumped["pages"][1]["fields"][0]["valueLabel"] == "—"
    assert "fields" not in dumped


def test_action_data_rejects_fields_and_pages_together() -> None:
    field = ActionField(id="a")
    with pytest.raises(ValidationError):
        ActionData(
            fields=[field],
            pages=[ActionPage(fields=[ActionField(id="b")])],
            buttons=[ActionButton(id="go", label="Go")],
        )


def test_action_data_rejects_duplicate_field_ids_across_pages() -> None:
    with pytest.raises(ValidationError):
        ActionData(
            pages=[
                ActionPage(fields=[ActionField(id="a")]),
                ActionPage(fields=[ActionField(id="a")]),
            ],
            buttons=[ActionButton(id="go", label="Go")],
        )


@pytest.mark.asyncio
async def test_options_router_forwards_request_and_accepts_plain_list() -> None:
    received: list[WidgetOptionsRequest] = []

    async def on_options(
        req: WidgetOptionsRequest, context: WidgetRequestContext
    ) -> list[ActionOption]:
        received.append(req)
        return [ActionOption(value="K-1", label="Muster AG", subtitle="Zürich")]

    app = FastAPI()
    app.include_router(
        create_widget_options_router(
            on_options_requested=on_options, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/widget-options",
            json={
                "device_id": "abc",
                "widget_id": "new-offer",
                "field_id": "customer",
                "query": "mus",
                "values": {"express": True},
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "options": [{"value": "K-1", "label": "Muster AG", "subtitle": "Zürich"}]
    }
    assert received[0].query == "mus"
    assert received[0].values == {"express": True}


@pytest.mark.asyncio
async def test_options_router_passes_result_through() -> None:
    async def on_options(
        req: WidgetOptionsRequest, context: WidgetRequestContext
    ) -> WidgetOptionsResult:
        return WidgetOptionsResult(empty_text="No customer found")

    app = FastAPI()
    app.include_router(
        create_widget_options_router(
            on_options_requested=on_options, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/widget-options",
            json={"device_id": "abc", "widget_id": "new-offer", "field_id": "customer"},
        )

    assert response.json() == {"options": [], "emptyText": "No customer found"}


def test_action_field_omits_defaults_to_keep_push_small() -> None:
    data = ActionData(
        fields=[ActionField(id="qty", type="number")], buttons=[ActionButton(id="go", label="Go")]
    )

    dumped = data.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert dumped["fields"] == [{"id": "qty", "type": "number"}]
    assert dumped["buttons"] == [{"id": "go", "label": "Go", "style": "primary"}]


def test_visible_if_serializes_and_must_reference_another_field() -> None:
    data = ActionData(
        fields=[
            ActionField(id="express", type="toggle"),
            ActionField(id="reason", visible_if=ActionCondition(field="express", equals=True)),
            ActionField(
                id="article",
                type="select",
                visible_if=ActionCondition(field="express", equals=["A1", "A2"]),
            ),
        ],
        buttons=[ActionButton(id="go", label="Go")],
    )
    dumped = data.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["fields"][1]["visibleIf"] == {"field": "express", "equals": True}
    assert dumped["fields"][2]["visibleIf"]["equals"] == ["A1", "A2"]

    with pytest.raises(ValidationError):
        ActionData(
            fields=[ActionField(id="reason", visible_if=ActionCondition(field="missing"))],
            buttons=[ActionButton(id="go", label="Go")],
        )
    with pytest.raises(ValidationError):
        ActionData(
            fields=[ActionField(id="reason", visible_if=ActionCondition(field="reason"))],
            buttons=[ActionButton(id="go", label="Go")],
        )
