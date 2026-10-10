from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
from bmsdna.app_native import (
    MAX_BLOCK_NESTING,
    MAX_BUTTONS_PER_BLOCK,
    MAX_CHAIN_DEPTH,
    MAX_CONTENT_BLOCKS,
    MAX_CONTENT_FIELDS,
    MAX_FIELD_OPTIONS,
    MAX_FORM_FIELDS,
    MAX_FORM_PAGES,
    MAX_INLINE_IMAGE_BYTES,
    MAX_REPEAT_FIELDS,
    MAX_SURFACE_DEFINITION_BYTES,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_THEN_STEPS,
    ActionButton,
    ActionData,
    ActionField,
    ActionOption,
    ActionPage,
    BadgesBlock,
    ButtonsBlock,
    CardBlock,
    CloseStep,
    CopyStep,
    DeviceStep,
    DividerBlock,
    FactsBlock,
    FieldsBlock,
    HeadingBlock,
    ImageBlock,
    NativeAction,
    NativeContent,
    NativeForm,
    NativeFormSubmit,
    NativeListItem,
    OpenUrlStep,
    RowBlock,
    ShowContentStep,
    ShowFormStep,
    SurfaceLimitError,
    TableBlock,
    TextBlock,
    dump_native_content,
    dump_native_form,
)
from fastapi import FastAPI
from pydantic import ValidationError


def _field(i: int, **overrides: Any) -> ActionField:
    return ActionField(id=f"f{i}", **overrides)


def _leaf_at(level: int) -> dict[str, Any]:
    """A divider at `level`, the top level counting as 1: `level - 1` cards around it."""
    block: dict[str, Any] = {"type": "divider"}
    for _ in range(level - 1):
        block = {"type": "card", "blocks": [block]}
    return block


DIVIDER = {"type": "divider"}


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

    with pytest.raises(ValidationError, match="needs 1 to 10 `fields`"):
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
                {"type": "card", "blocks": [{"type": "row", "blocks": [DIVIDER, DIVIDER]}]},
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
    # card > card > divider is fine, card > card > card > divider is too deep.
    assert MAX_BLOCK_NESTING == 3
    NativeContent.model_validate({"blocks": [_leaf_at(MAX_BLOCK_NESTING)]})
    with pytest.raises(ValidationError, match="nested"):
        NativeContent.model_validate({"blocks": [_leaf_at(MAX_BLOCK_NESTING + 1)]})

    NativeContent(blocks=[DividerBlock()] * MAX_CONTENT_BLOCKS)
    with pytest.raises(ValidationError, match="blocks"):
        NativeContent(blocks=[DividerBlock()] * (MAX_CONTENT_BLOCKS + 1))

    actions = [NativeAction(id=f"a{i}", label="A") for i in range(5)]
    NativeContent(blocks=[DividerBlock()], actions=actions[:4])
    with pytest.raises(ValidationError, match="footer"):
        NativeContent(blocks=[DividerBlock()], actions=actions)


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
    first = NativeAction.model_validate(
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
            ],
        }
    )
    steps = first.then or []
    assert isinstance(steps[2], OpenUrlStep)
    assert isinstance(steps[3], CopyStep) and steps[3].text == "123"
    assert isinstance(steps[5], CloseStep)

    chained = NativeAction.model_validate(
        {
            "id": "next",
            "label": "Next",
            "then": [
                {"device": {"action": "callPhone", "number": "+41 44 000 00 00"}},
                {"showForm": {"fields": [{"id": "reason"}]}},
                {"showContent": {"blocks": [DIVIDER]}},
            ],
        }
    )
    steps = chained.then or []
    assert isinstance(steps[0], DeviceStep)
    assert isinstance(steps[1], ShowFormStep)
    assert isinstance(steps[2], ShowContentStep)

    # And back to the app format.
    dumped = NativeContent(blocks=[ButtonsBlock(items=[first, chained])])
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
    def chain(chained: int) -> dict[str, Any]:
        """`chained` surfaces after the first one."""
        content: dict[str, Any] = {"blocks": [DIVIDER]}
        for _ in range(chained):
            content = {
                "blocks": [DIVIDER],
                "actions": [{"id": "n", "label": "Next", "then": [{"showContent": content}]}],
            }
        return content

    # At most 5 screens in a flow: the first and 4 chained ones.
    assert MAX_CHAIN_DEPTH == 4
    NativeContent.model_validate(chain(4))
    with pytest.raises(ValidationError, match="chained"):
        NativeContent.model_validate(chain(5))


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


# --- what the app rejects with `invalid` --------------------------------------


def test_text_align_can_be_trailing() -> None:
    block = TextBlock(markdown="Total", align="trailing")
    assert block.model_dump(mode="json", by_alias=True, exclude_none=True)["align"] == "trailing"
    with pytest.raises(ValidationError):
        TextBlock.model_validate({"markdown": "x", "align": "justify"})


def test_list_item_images_are_https_urls() -> None:
    NativeListItem(title="Beat", image="https://example.com/beat.jpg")
    with pytest.raises(ValidationError, match="https"):
        NativeListItem(title="Beat", image="data:image/png;base64,iVBORw0KGgo=")
    with pytest.raises(ValidationError, match="https"):
        NativeListItem(title="Beat", image="http://example.com/beat.jpg")


def test_item_lists_are_not_empty() -> None:
    for block in ({"type": "facts"}, {"type": "list"}, {"type": "badges"}, {"type": "buttons"}):
        with pytest.raises(ValidationError):
            NativeContent.model_validate({"blocks": [{**block, "items": []}]})
    FactsBlock.model_validate({"items": [{"label": "A", "value": "B"}]})
    BadgesBlock.model_validate({"items": [{"text": "A"}]})


def test_buttons_block_has_at_most_6_items() -> None:
    def items(n: int) -> list[dict[str, str]]:
        return [{"id": f"b{i}", "label": "B"} for i in range(n)]

    assert MAX_BUTTONS_PER_BLOCK == 6
    ButtonsBlock.model_validate({"items": items(6)})
    with pytest.raises(ValidationError):
        ButtonsBlock.model_validate({"items": items(7)})


def test_row_has_two_or_three_blocks_and_card_at_least_one() -> None:
    for count, valid in ((1, False), (2, True), (3, True), (4, False)):
        blocks = [DIVIDER] * count
        if valid:
            RowBlock.model_validate({"blocks": blocks})
        else:
            with pytest.raises(ValidationError):
                RowBlock.model_validate({"blocks": blocks})
    CardBlock.model_validate({"blocks": [DIVIDER]})
    with pytest.raises(ValidationError):
        CardBlock.model_validate({"blocks": []})


def test_content_needs_at_least_one_block() -> None:
    with pytest.raises(ValidationError):
        NativeContent(blocks=[])
    with pytest.raises(ValidationError):  # also a chained one
        NativeContent.model_validate(
            {
                "blocks": [DIVIDER],
                "actions": [{"id": "a", "label": "A", "then": [{"showContent": {"blocks": []}}]}],
            }
        )


def test_table_has_at_most_20_columns_and_200_rows() -> None:
    def table(columns: int, rows: int) -> dict[str, Any]:
        return {
            "columns": [{"key": f"c{i}", "label": "C"} for i in range(columns)],
            "rows": [{"c0": 1}] * rows,
        }

    assert (MAX_TABLE_COLUMNS, MAX_TABLE_ROWS) == (20, 200)
    TableBlock.model_validate(table(20, 200))
    with pytest.raises(ValidationError):
        TableBlock.model_validate(table(21, 1))
    with pytest.raises(ValidationError):
        TableBlock.model_validate(table(1, 201))


def test_fields_blocks_have_at_most_60_fields_together() -> None:
    def fields(start: int, count: int) -> dict[str, Any]:
        return {
            "type": "fields",
            "fields": [{"id": f"f{start + i}"} for i in range(count)],
        }

    assert MAX_CONTENT_FIELDS == 60
    NativeContent.model_validate({"blocks": [fields(0, 30), fields(30, 30)]})
    with pytest.raises(ValidationError, match="together"):
        NativeContent.model_validate(
            {"blocks": [fields(0, 30), {"type": "card", "blocks": [fields(30, 31)]}]}
        )
    assert FieldsBlock.model_validate(fields(0, 1)).fields[0].id == "f0"


def test_photo_dimension_is_256_to_4096_and_the_default_count_is_the_apps() -> None:
    ActionField(id="card", type="photo", max_dimension=256)
    ActionField(id="card", type="photo", max_dimension=4096)
    for outside in (255, 4097):
        with pytest.raises(ValidationError):
            ActionField(id="card", type="photo", max_dimension=outside)


def test_scan_has_1_to_20_pages() -> None:
    field = ActionField(id="doc", type="scan", format="pdf", max=20)
    assert field.max == 20
    for outside in (0, 21):
        with pytest.raises(ValidationError, match="1 to 20"):
            ActionField(id="doc", type="scan", max=outside)


def test_barcode_symbologies_are_the_scanners_names() -> None:
    names = [
        "aztec", "codabar", "code39", "code93", "code128", "dataMatrix", "ean8", "ean13",
        "i2of5", "itf14", "pdf417", "qr", "upce",
    ]  # fmt: skip
    field = ActionField.model_validate({"id": "gln", "type": "barcode", "symbologies": names})
    assert field.symbologies == names
    with pytest.raises(ValidationError):
        ActionField.model_validate({"id": "gln", "type": "barcode", "symbologies": ["ean-13"]})


def test_repeat_rows_cannot_be_conditional() -> None:
    inner = ActionField.model_validate(
        {"id": "reason", "visibleIf": {"field": "express", "equals": True}}
    )
    with pytest.raises(ValidationError, match="visible_if"):
        ActionField(id="lines", type="repeat", fields=[inner])


def test_select_needs_options_or_remote_in_a_native_form() -> None:
    NativeForm(fields=[ActionField(id="kind", type="select", options=[ActionOption(value="a")])])
    NativeForm(fields=[ActionField(id="owner", type="select", remote=True)])
    with pytest.raises(ValidationError, match="needs `options`"):
        NativeForm(fields=[ActionField(id="kind", type="select")])
    with pytest.raises(ValidationError, match="needs `options`"):  # also inside a repeat group
        NativeForm(
            fields=[
                ActionField(
                    id="lines", type="repeat", fields=[ActionField(id="kind", type="select")]
                )
            ]
        )
    with pytest.raises(ValidationError, match="needs `options`"):  # and in a fields block
        NativeContent(blocks=[FieldsBlock(fields=[ActionField(id="kind", type="select")])])
    # Widget forms keep accepting it: they are not native forms.
    assert ActionData(
        fields=[ActionField(id="kind", type="select")],
        buttons=[ActionButton(id="go", label="Go")],
    )


# --- repeat fields and then steps: the two limits the app enforces ------------


def _is_limit(error: ValidationError) -> bool:
    """What a backend answering like the app does: `tooLarge`, not `invalid`."""
    return any(isinstance(e.get("ctx", {}).get("error"), SurfaceLimitError) for e in error.errors())


def test_a_repeat_group_has_1_to_10_fields_and_that_is_invalid_not_too_large() -> None:
    def group(count: int) -> ActionField:
        inner = [ActionField(id=f"f{i}", type="text") for i in range(count)]
        return ActionField(id="lines", type="repeat", fields=inner)

    assert MAX_REPEAT_FIELDS == 10
    assert len(group(1).fields or []) == 1
    assert len(group(10).fields or []) == 10
    for count in (0, 11):
        with pytest.raises(ValidationError, match="1 to 10") as caught:
            group(count)
        assert not _is_limit(caught.value)  # the app answers `invalid`


def test_then_has_at_most_6_steps_and_that_is_too_large() -> None:
    def action(count: int) -> dict[str, Any]:
        return {"id": "go", "label": "Go", "then": [{"copy": str(i)} for i in range(count)]}

    assert MAX_THEN_STEPS == 6
    assert len(NativeAction.model_validate(action(6)).then or []) == 6
    with pytest.raises(ValidationError, match="at most 6") as caught:
        NativeAction.model_validate(action(7))
    assert _is_limit(caught.value)  # the app answers `tooLarge`


def test_then_steps_are_checked_in_a_chained_definition_too() -> None:
    too_long = {"id": "inner", "label": "Inner", "then": [{"close": True}] * 7}
    chained = {"blocks": [DIVIDER], "actions": [too_long]}
    with pytest.raises(ValidationError, match="at most 6"):
        NativeContent.model_validate(
            {
                "blocks": [DIVIDER],
                "actions": [
                    {"id": "outer", "label": "Outer", "then": [{"showContent": chained}]},
                ],
            }
        )


def test_limits_are_too_large_and_everything_else_is_invalid() -> None:
    def failure(build: Any) -> ValidationError:
        with pytest.raises(ValidationError) as caught:
            build()
        return caught.value

    fields = [ActionField(id=f"f{i}") for i in range(MAX_FORM_FIELDS + 1)]
    buttons = [{"id": f"b{i}", "label": "B"} for i in range(7)]
    columns = [{"key": f"c{i}", "label": "C"} for i in range(MAX_TABLE_COLUMNS + 1)]
    one_column = [{"key": "c", "label": "C"}]
    rows = [{"c": 1}] * (MAX_TABLE_ROWS + 1)

    # Beyond a limit: `tooLarge`.
    assert _is_limit(failure(lambda: NativeForm(fields=fields)))
    assert _is_limit(failure(lambda: NativeContent(blocks=[DividerBlock()] * 101)))
    assert _is_limit(failure(lambda: ButtonsBlock.model_validate({"items": buttons})))
    assert _is_limit(failure(lambda: TableBlock.model_validate({"columns": columns, "rows": []})))
    assert _is_limit(
        failure(lambda: TableBlock.model_validate({"columns": one_column, "rows": rows}))
    )
    assert _is_limit(failure(lambda: ImageBlock(data=_data_uri(MAX_INLINE_IMAGE_BYTES + 1))))
    assert _is_limit(failure(lambda: NativeContent.model_validate({"blocks": [_leaf_at(4)]})))

    # Anything else: `invalid`.
    assert not _is_limit(failure(lambda: ActionField(id="card", type="photo", max=11)))
    assert not _is_limit(failure(lambda: RowBlock.model_validate({"blocks": [DIVIDER] * 4})))
    assert not _is_limit(failure(lambda: NativeForm(tint="blue", fields=[ActionField(id="a")])))
    assert not _is_limit(failure(lambda: NativeContent(blocks=[])))
