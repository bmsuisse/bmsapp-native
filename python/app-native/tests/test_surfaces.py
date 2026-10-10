from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    MAX_BLOCK_NESTING,
    MAX_CONTENT_BLOCKS,
    MAX_FIELD_OPTIONS,
    MAX_FORM_FIELDS,
    MAX_FORM_PAGES,
    MAX_INLINE_IMAGE_BYTES,
    MAX_SURFACE_DEFINITION_BYTES,
    ActionField,
    ActionOption,
    ActionPage,
    ButtonsBlock,
    CardBlock,
    CloseStep,
    CopyStep,
    DeviceStep,
    DividerBlock,
    HeadingBlock,
    ImageBlock,
    NativeAction,
    NativeContent,
    NativeForm,
    NativeFormSubmit,
    OpenUrlStep,
    ShowContentStep,
    ShowFormStep,
    TableBlock,
    TextBlock,
    dump_native_content,
    dump_native_form,
)
from fastapi import FastAPI
from pydantic import ValidationError


def _field(i: int, **overrides: Any) -> ActionField:
    return ActionField(id=f"f{i}", **overrides)


def _nested_cards(depth: int) -> dict[str, Any]:
    """A card inside a card inside ... `depth` cards deep, with a divider inside."""
    block: dict[str, Any] = {"type": "divider"}
    for _ in range(depth):
        block = {"type": "card", "blocks": [block]}
    return block


# --- forms ---------------------------------------------------------------


def test_form_serializes_in_app_format() -> None:
    form = NativeForm(
        id="new-customer",
        title="New customer",
        size="large",
        tint="#2e4a62",
        context={"source": "customer-list"},
        fields=[
            ActionField(id="name", label="Name", required=True, min_length=2, max_length=80),
            ActionField(id="notes", type="textarea", help="Visible to the team"),
            ActionField(id="seats", type="stepper", min=1, max=20, step=1),
            ActionField(id="card", type="photo", max=1, source="camera", max_dimension=2048),
        ],
        submit=NativeFormSubmit(label="Create", wait=True),
    )

    assert dump_native_form(form) == {
        "id": "new-customer",
        "title": "New customer",
        "size": "large",
        "tint": "#2e4a62",
        "context": {"source": "customer-list"},
        "fields": [
            {"id": "name", "type": "text", "label": "Name", "required": True,
             "minLength": 2, "maxLength": 80},
            {"id": "notes", "type": "textarea", "help": "Visible to the team"},
            {"id": "seats", "type": "stepper", "min": 1, "max": 20, "step": 1},
            {"id": "card", "type": "photo", "max": 1, "source": "camera", "maxDimension": 2048},
        ],
        "submit": {"label": "Create", "wait": True},
    }  # fmt: skip


def test_form_parses_the_app_format_and_keeps_integers_integers() -> None:
    form = NativeForm.model_validate(
        {"fields": [{"id": "seats", "type": "stepper", "min": 1, "max": 20, "step": 1}]}
    )
    dumped = dump_native_form(form)
    assert dumped["fields"][0]["max"] == 20
    assert isinstance(dumped["fields"][0]["max"], int)


def test_form_rejects_fields_and_pages_together() -> None:
    with pytest.raises(ValidationError):
        NativeForm(fields=[_field(1)], pages=[ActionPage(fields=[_field(2)])])


def test_form_without_fields_is_a_confirmation() -> None:
    form = NativeForm(text="Delete this customer?", submit=NativeFormSubmit(style="destructive"))
    assert dump_native_form(form) == {
        "text": "Delete this customer?",
        "submit": {"style": "destructive"},
    }


def test_form_rejects_duplicate_ids_and_unknown_visible_if_across_pages() -> None:
    with pytest.raises(ValidationError):
        NativeForm(pages=[ActionPage(fields=[_field(1)]), ActionPage(fields=[_field(1)])])
    with pytest.raises(ValidationError):
        NativeForm.model_validate(
            {"fields": [{"id": "a", "visibleIf": {"field": "missing", "equals": True}}]}
        )


def test_form_tint_must_be_a_hex_color() -> None:
    with pytest.raises(ValidationError):
        NativeForm(tint="blue", fields=[_field(1)])


def test_form_limits() -> None:
    pages = [ActionPage(fields=[_field(i)]) for i in range(MAX_FORM_PAGES)]
    NativeForm(pages=pages)  # at the limit
    with pytest.raises(ValidationError, match="pages"):
        NativeForm(pages=[*pages, ActionPage(fields=[_field(99)])])

    NativeForm(fields=[_field(i) for i in range(MAX_FORM_FIELDS)])
    with pytest.raises(ValidationError, match="fields"):
        NativeForm(fields=[_field(i) for i in range(MAX_FORM_FIELDS + 1)])

    options = [ActionOption(value=str(i)) for i in range(MAX_FIELD_OPTIONS + 1)]
    with pytest.raises(ValidationError, match="options"):
        NativeForm(fields=[_field(1, type="select", options=options)])

    with pytest.raises(ValidationError, match="bytes"):
        NativeForm(text="x" * (MAX_SURFACE_DEFINITION_BYTES + 1))


def test_repeat_group_rules() -> None:
    inner = [ActionField(id="qty", type="stepper"), ActionField(id="note", type="textarea")]
    field = ActionField(id="lines", type="repeat", fields=inner, min=1, max=50, add_label="Add")
    assert field.fields is not None and len(field.fields) == 2

    with pytest.raises(ValidationError, match="needs `fields`"):
        ActionField(id="lines", type="repeat")
    with pytest.raises(ValidationError, match="cannot contain"):
        ActionField(id="lines", type="repeat", fields=[ActionField(id="p", type="photo")])
    with pytest.raises(ValidationError, match="cannot contain"):  # no nesting
        ActionField(
            id="lines",
            type="repeat",
            fields=[ActionField(id="inner", type="repeat", fields=inner)],
        )
    with pytest.raises(ValidationError, match="at most 50"):
        ActionField(id="lines", type="repeat", fields=inner, max=51)
    with pytest.raises(ValidationError, match="only belongs"):
        ActionField(id="name", fields=inner)


def test_repeat_prefill_is_limited_to_50_rows() -> None:
    inner = [ActionField(id="qty", type="stepper")]
    with pytest.raises(ValidationError, match="rows"):
        NativeForm(
            fields=[ActionField(id="lines", type="repeat", fields=inner)],
            values={"lines": [{"qty": 1}] * 51},
        )


def test_media_and_choice_field_rules() -> None:
    with pytest.raises(ValidationError):
        ActionField(id="card", type="photo", max=11)
    with pytest.raises(ValidationError):
        ActionField(id="card", type="photo", max_dimension=5000)
    with pytest.raises(ValidationError, match="needs `options`"):
        ActionField(id="tags", type="multiselect")
    with pytest.raises(ValidationError, match="needs `options`"):
        ActionField(id="kind", type="segmented")
    with pytest.raises(ValidationError, match="`min` is greater"):
        ActionField(id="seats", type="stepper", min=5, max=1)
    with pytest.raises(ValidationError):
        ActionField.model_validate({"id": "x", "type": "password"})  # there is none


# --- content -------------------------------------------------------------


def test_content_serializes_in_app_format() -> None:
    content = NativeContent(
        title="Miller Ltd",
        size="medium",
        blocks=[
            HeadingBlock(text="Overview", level=2),
            TextBlock(markdown="Prefers **Tuesdays**"),
            DividerBlock(),
        ],
        actions=[NativeAction(id="new-order", label="New order", style="primary", wait=True)],
    )

    assert dump_native_content(content) == {
        "title": "Miller Ltd",
        "size": "medium",
        "blocks": [
            {"type": "heading", "text": "Overview", "level": 2},
            {"type": "text", "markdown": "Prefers **Tuesdays**"},
            {"type": "divider"},
        ],
        "actions": [{"id": "new-order", "label": "New order", "style": "primary", "wait": True}],
    }


def test_content_parses_blocks_by_type() -> None:
    content = NativeContent.model_validate(
        {
            "blocks": [
                {"type": "kpi", "data": {"value": 12, "unit": "pcs"}},
                {"type": "card", "blocks": [{"type": "row", "blocks": [{"type": "divider"}]}]},
            ]
        }
    )
    assert content.blocks[0].type == "kpi"
    card = content.blocks[1]
    assert isinstance(card, CardBlock)
    assert card.blocks[0].type == "row"


def test_content_rejects_an_unknown_block_type() -> None:
    with pytest.raises(ValidationError):
        NativeContent.model_validate({"blocks": [{"type": "iframe", "url": "https://example.com"}]})


def test_content_limits() -> None:
    NativeContent.model_validate({"blocks": [_nested_cards(MAX_BLOCK_NESTING)]})
    with pytest.raises(ValidationError, match="nested"):
        NativeContent.model_validate({"blocks": [_nested_cards(MAX_BLOCK_NESTING + 1)]})

    NativeContent(blocks=[DividerBlock()] * MAX_CONTENT_BLOCKS)
    with pytest.raises(ValidationError, match="blocks"):
        NativeContent(blocks=[DividerBlock()] * (MAX_CONTENT_BLOCKS + 1))

    actions = [NativeAction(id=f"a{i}", label="A") for i in range(5)]
    NativeContent(blocks=[], actions=actions[:4])
    with pytest.raises(ValidationError, match="footer"):
        NativeContent(blocks=[], actions=actions)


def test_nested_blocks_count_towards_the_block_limit() -> None:
    card = {"type": "card", "blocks": [{"type": "divider"}] * MAX_CONTENT_BLOCKS}
    with pytest.raises(ValidationError, match="blocks"):
        NativeContent.model_validate({"blocks": [card]})  # 100 + the card itself


def _data_uri(size: int) -> str:
    return "data:image/png;base64," + base64.b64encode(b"\0" * size).decode()


def test_inline_images_are_limited() -> None:
    ImageBlock(data=_data_uri(1000))
    with pytest.raises(ValidationError, match="inline image"):
        ImageBlock(data=_data_uri(MAX_INLINE_IMAGE_BYTES + 1))
    # 1 MB each is fine, but not five of them (4 MB in total).
    five = [ImageBlock(data=_data_uri(MAX_INLINE_IMAGE_BYTES - 10)) for _ in range(5)]
    with pytest.raises(ValidationError, match="add up"):
        NativeContent(blocks=five)
    with pytest.raises(ValidationError, match="needs `url` or `data`"):
        ImageBlock()
    with pytest.raises(ValidationError, match="data:image"):
        ImageBlock(data="data:text/html;base64,PGI+")


def test_urls_must_be_https() -> None:
    with pytest.raises(ValidationError, match="https"):
        ImageBlock(url="http://example.com/a.png")
    with pytest.raises(ValidationError, match="https"):
        NativeContent.model_validate({"blocks": [{"type": "file", "url": "javascript:alert(1)"}]})
    with pytest.raises(ValidationError, match="https"):
        NativeContent.model_validate(
            {"blocks": [{"type": "video", "url": "https://example.com/a.mp4", "poster": "ftp://x"}]}
        )


def test_table_column_keys_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        TableBlock.model_validate(
            {"columns": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}], "rows": []}
        )


def test_follow_up_steps() -> None:
    action = NativeAction.model_validate(
        {
            "id": "go",
            "label": "Go",
            "then": [
                {"openPath": "/orders/1"},
                {"openUrl": "https://example.com"},
                {"openUrl": "tel:+41440000000"},
                {"copy": "123"},
                {"share": {"text": "Hi"}},
                {"close": True},
                {"device": {"action": "callPhone", "number": "+41 44 000 00 00"}},
                {"showForm": {"fields": [{"id": "reason"}]}},
                {"showContent": {"blocks": []}},
            ],
        }
    )
    steps = action.then or []
    assert isinstance(steps[2], OpenUrlStep)
    assert isinstance(steps[3], CopyStep) and steps[3].text == "123"
    assert isinstance(steps[5], CloseStep)
    assert isinstance(steps[6], DeviceStep)
    assert isinstance(steps[7], ShowFormStep)
    assert isinstance(steps[8], ShowContentStep)
    # And back to the app format.
    dumped = NativeContent(blocks=[ButtonsBlock(items=[action])])
    assert dump_native_content(dumped)["blocks"][0]["items"][0]["then"][3] == {"copy": "123"}


@pytest.mark.parametrize(
    "step",
    [
        {"openUrl": "javascript:alert(1)"},
        {"openUrl": "http://example.com"},
        {"close": False},
        {"device": {"action": "calendar"}},
        {"openPath": "/x", "copy": "y"},  # exactly one key
        {"unknown": 1},
    ],
)
def test_follow_up_step_rejects(step: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NativeAction.model_validate({"id": "go", "label": "Go", "then": [step]})


def test_chain_depth_is_limited() -> None:
    def chain(length: int) -> dict[str, Any]:
        content: dict[str, Any] = {"blocks": []}
        for _ in range(length):
            content = {
                "blocks": [],
                "actions": [{"id": "n", "label": "Next", "then": [{"showContent": content}]}],
            }
        return content

    NativeContent.model_validate(chain(5))
    with pytest.raises(ValidationError, match="chained"):
        NativeContent.model_validate(chain(6))


# --- as an endpoint --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_form_can_be_served_from_an_endpoint_and_passed_on_unchanged() -> None:
    app = FastAPI()

    @app.get(
        "/api/forms/new-customer",
        response_model=NativeForm,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def new_customer() -> NativeForm:
        return NativeForm(
            id="new-customer",
            title="New customer",
            fields=[
                ActionField(id="name", required=True, max_length=80),
                ActionField(id="email", type="email"),
            ],
            submit=NativeFormSubmit(wait=True),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/forms/new-customer")

    assert response.json() == {
        "id": "new-customer",
        "title": "New customer",
        "fields": [
            {"id": "name", "type": "text", "required": True, "maxLength": 80},
            {"id": "email", "type": "email"},
        ],
        "submit": {"wait": True},
    }
