"""Native forms and content that a web page opens as native iOS sheets.

The page calls `BMSNative.call("showForm" | "showContent", definition)`, the
app presents a native sheet and answers once the user is done. These models
describe the definition (`NativeForm`, `NativeContent`) so that a backend can
serve it from an endpoint of its own, and the page passes it to `showForm` /
`showContent` unchanged:

    @app.get("/api/forms/new-customer", response_model_by_alias=True,
             response_model_exclude_none=True)
    async def new_customer_form() -> NativeForm: ...

The form fields are the same as in dashboard widgets (`ActionField`). The
models validate the format and the limits of the app (`MAX_*` below), so
typos and oversized definitions show up in the backend rather than as an
`invalid` / `tooLarge` answer on the device.

The result of a form goes to the page, which posts the values to your
backend itself; the only calls the app makes on its own are the option
lookup (`create_widget_options_router`, with `form_id`) and the media upload
(`create_document_router`, with `kind="form"`).

Format and examples: `docs/native-surfaces-guide.md`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from .widgets import (
    MAX_REPEAT_ROWS,
    ActionField,
    ActionPage,
    ChartData,
    KpiData,
    ProgressData,
    StatsData,
    Value,
    _CamelModel,
    check_form_fields,
)

#: The whole definition as JSON, in bytes.
MAX_SURFACE_DEFINITION_BYTES = 256 * 1024
#: Pages of a form.
MAX_FORM_PAGES = 10
#: Fields of a form, all pages together (a `repeat` group counts as one).
MAX_FORM_FIELDS = 60
#: Inline `options` of one field.
MAX_FIELD_OPTIONS = 200
#: Blocks of a content definition, nested ones included.
MAX_CONTENT_BLOCKS = 100
#: How deep `card` and `row` may be nested.
MAX_BLOCK_NESTING = 3
#: Buttons in the footer of a content definition.
MAX_FOOTER_ACTIONS = 4
#: One inline `data:` image, decoded, in bytes.
MAX_INLINE_IMAGE_BYTES = 1024 * 1024
#: All inline images of a content definition, in bytes.
MAX_INLINE_IMAGES_BYTES = 4 * 1024 * 1024
#: Chained surfaces (`then: [{showForm}]`) after the first one.
MAX_CHAIN_DEPTH = 5

#: Hex color `#rrggbb`.
Tint = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]

SurfaceSize = Literal["full", "large", "medium", "fit"]
"""`full`: full-screen cover. `large` / `medium`: the standard iOS sheet
detents (`medium` can be pulled up). `fit`: a sheet as high as its content,
at most `large`. On iPad: a centered sheet."""


class _SurfaceBase(_CamelModel):
    #: Echoed in results and events; used by `closeSurface` and
    #: `surfaceResult` and sent as `form_id` with option lookups and uploads.
    #: The app generates one if missing.
    id: str | None = Field(default=None, min_length=1)
    #: Title in the navigation bar.
    title: str | None = None
    #: Default: `large` for forms, `medium` for content.
    size: SurfaceSize | None = None
    #: Accent color of the surface.
    tint: Tint | None = None
    #: Opaque to the app: echoed in results and events and sent along with
    #: option lookups (`WidgetOptionsRequest.context`) and uploads.
    context: dict[str, Any] | None = None


def _json_bytes(model: _CamelModel) -> int:
    dumped = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return len(json.dumps(dumped, ensure_ascii=False).encode())


def _check_definition_size(model: _CamelModel) -> None:
    size = _json_bytes(model)
    if size > MAX_SURFACE_DEFINITION_BYTES:
        raise ValueError(
            f"The definition is {size} bytes as JSON, the app takes at most "
            f"{MAX_SURFACE_DEFINITION_BYTES}."
        )


# --- Forms ----------------------------------------------------------------

NativeFormField = ActionField
"""A field of a native form: the same model as in dashboard widgets."""

NativeFormPage = ActionPage
"""One page of a multi-page native form."""


class NativeFormSubmit(_CamelModel):
    #: Label of the submit button.
    label: str | None = None
    #: Confirmation prompt before submitting.
    confirm: str | None = None
    #: Confirm with Face ID/Touch ID first. Only a UX confirmation on the
    #: device, not proof that can be verified on the server.
    biometric: bool | None = None
    style: Literal["primary", "destructive"] | None = None
    #: Round trip: keep the form open with a spinner until the page answers
    #: with `surfaceResult` (within 60 seconds).
    wait: bool | None = None


class NativeForm(_SurfaceBase):
    """Definition of a form for `showForm`."""

    #: Intro text on the first page.
    text: str | None = None
    #: Prefill by field id.
    values: dict[str, Any] | None = None
    #: Single-page form. For several pages use `pages` instead.
    fields: list[ActionField] | None = None
    pages: list[ActionPage] | None = Field(default=None, min_length=1)
    submit: NativeFormSubmit | None = None

    @model_validator(mode="after")
    def _check(self) -> NativeForm:
        if self.fields and self.pages:
            raise ValueError("Specify either `fields` or `pages`, not both.")
        check_form_fields(self.fields, self.pages)
        _check_form_limits(self)
        _check_definition_size(self)
        return self


def _form_fields(form: NativeForm) -> list[ActionField]:
    return [f for page in form.pages or [] for f in page.fields] + list(form.fields or [])


def _check_form_limits(form: NativeForm) -> None:
    pages = form.pages or []
    if len(pages) > MAX_FORM_PAGES:
        raise ValueError(f"{len(pages)} pages, the app takes at most {MAX_FORM_PAGES}.")
    fields = _form_fields(form)
    if len(fields) > MAX_FORM_FIELDS:
        raise ValueError(f"{len(fields)} fields, the app takes at most {MAX_FORM_FIELDS}.")
    for field in fields:
        _check_field_limits(field)
        rows = (form.values or {}).get(field.id)
        if field.type == "repeat" and isinstance(rows, list) and len(rows) > MAX_REPEAT_ROWS:
            raise ValueError(
                f"`values.{field.id}` has {len(rows)} rows, the app takes at most "
                f"{MAX_REPEAT_ROWS}."
            )


def _check_field_limits(field: ActionField) -> None:
    if field.options and len(field.options) > MAX_FIELD_OPTIONS:
        raise ValueError(
            f"`{field.id}` has {len(field.options)} options, the app takes at most "
            f"{MAX_FIELD_OPTIONS} inline. Use a search field or `remote=True`."
        )
    for inner in field.fields or []:
        _check_field_limits(inner)


# --- Content: actions and follow-ups ---------------------------------------


class NativeAction(_CamelModel):
    """A button of the content: in the footer, in a `buttons` block or on the
    row of a `list`."""

    #: Comes back as `action` in the result.
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    style: Literal["primary", "secondary", "destructive"] | None = None
    #: SF Symbol name.
    icon: str | None = None
    #: Confirmation prompt before running.
    confirm: str | None = None
    #: Confirm with Face ID/Touch ID first (UX only).
    biometric: bool | None = None
    #: Validate the `fields` blocks first and return their `values`.
    submit: bool | None = None
    #: Round trip: keep the surface open until the page answers with
    #: `surfaceResult`.
    wait: bool | None = None
    #: Steps that run in the app before the call resolves.
    then: list[NativeThen] | None = None


class _Step(_CamelModel):
    """One follow-up step: an object with exactly one known key."""

    model_config = ConfigDict(extra="forbid")


class OpenPathStep(_Step):
    #: Opens this path in the web app.
    open_path: str = Field(min_length=1)


class OpenUrlStep(_Step):
    #: Opens this URL outside the app. Schemes `https`, `tel` and `mailto`.
    open_url: str

    @model_validator(mode="after")
    def _scheme(self) -> OpenUrlStep:
        if not re.match(r"^(https://|tel:|mailto:)", self.open_url, re.IGNORECASE):
            raise ValueError("`openUrl` takes only the schemes https, tel and mailto.")
        return self


class CopyStep(_Step):
    #: Text for the clipboard. The JSON key is `copy`; in Python the field is
    #: `text`, because `copy` is a method of every Pydantic model.
    text: str = Field(alias="copy")


class ShareData(_CamelModel):
    text: str | None = None
    url: str | None = None


class ShareStep(_Step):
    share: ShareData


class CloseStep(_Step):
    close: Literal[True]


_DEVICE_ACTIONS = frozenset({"navigate", "callPhone", "saveContact", "addReminder"})


class DeviceStep(_Step):
    #: One of the device actions with the same payload as in
    #: `docs/device-actions-guide.md`, plus `action`:
    #: `{"action": "navigate", "destination": {...}}`. `saveContact` and
    #: `addReminder` also need the `deviceApps` capability.
    device: dict[str, Any]

    @model_validator(mode="after")
    def _action(self) -> DeviceStep:
        if self.device.get("action") not in _DEVICE_ACTIONS:
            raise ValueError(
                "`device.action` must be one of: " + ", ".join(sorted(_DEVICE_ACTIONS)) + "."
            )
        return self


class ShowFormStep(_Step):
    #: Chained flow: replaces the surface with this form.
    show_form: NativeForm


class ShowContentStep(_Step):
    #: Chained flow: replaces the surface with this content.
    show_content: NativeContent


NativeThen = (
    OpenPathStep
    | OpenUrlStep
    | CopyStep
    | ShareStep
    | CloseStep
    | DeviceStep
    | ShowFormStep
    | ShowContentStep
)
"""A follow-up step of an action (`NativeAction.then`)."""


# --- Content: blocks -------------------------------------------------------


class NativeFact(_CamelModel):
    label: str
    value: str
    #: Makes the row tappable: call, mail, route, open.
    kind: Literal["text", "phone", "email", "address", "url"] | None = None
    icon: str | None = None
    copyable: bool | None = None


class NativeListItem(_CamelModel):
    title: str
    subtitle: str | None = None
    trailing: Value | None = None
    icon: str | None = None
    #: `https` URL or `data:image/...`.
    image: str | None = None
    action: NativeAction | None = None


class NativeTableColumn(_CamelModel):
    key: str = Field(min_length=1)
    label: str
    align: Literal["leading", "center", "trailing"] | None = None


class NativeBadge(_CamelModel):
    text: str
    tint: Tint | None = None
    icon: str | None = None


class HeadingBlock(_CamelModel):
    type: Literal["heading"] = "heading"
    text: str
    level: Literal[1, 2, 3] | None = None
    icon: str | None = None


class TextBlock(_CamelModel):
    type: Literal["text"] = "text"
    #: Paragraphs, lists, quotes, tables, bold/italic/links. No HTML.
    markdown: str
    style: Literal["body", "caption", "footnote"] | None = None
    align: Literal["leading", "center"] | None = None


def _decoded_data_uri_bytes(uri: str) -> int:
    header, _, payload = uri.partition(",")
    if not header.lower().endswith(";base64"):
        return len(payload.encode())
    padding = len(payload) - len(payload.rstrip("="))
    return max(0, len(payload) * 3 // 4 - padding)


def _require_https(value: str | None, what: str) -> None:
    if value is not None and not value.lower().startswith("https://"):
        raise ValueError(f"{what} must be an https URL.")


class ImageBlock(_CamelModel):
    type: Literal["image"] = "image"
    #: `https` URL. URLs on the web app's own backend load with its token.
    url: str | None = None
    #: `data:image/...`, at most 1 MB.
    data: str | None = None
    #: Text for VoiceOver.
    alt: str | None = None
    caption: str | None = None
    height: float | None = Field(default=None, gt=0)
    fit: Literal["fit", "fill"] | None = None
    shape: Literal["rounded", "circle", "none"] | None = None
    tap_to_zoom: bool | None = None

    @model_validator(mode="after")
    def _source(self) -> ImageBlock:
        if self.url is None and self.data is None:
            raise ValueError("An `image` block needs `url` or `data`.")
        _require_https(self.url, "`url` of an `image` block")
        if self.data is not None:
            if not self.data.lower().startswith("data:image/"):
                raise ValueError("`data` of an `image` block must be a `data:image/...` URI.")
            size = _decoded_data_uri_bytes(self.data)
            if size > MAX_INLINE_IMAGE_BYTES:
                raise ValueError(
                    f"An inline image is {size} bytes, the app takes at most "
                    f"{MAX_INLINE_IMAGE_BYTES}. Use `url`."
                )
        return self


class FactsBlock(_CamelModel):
    type: Literal["facts"] = "facts"
    items: list[NativeFact]


class ListBlock(_CamelModel):
    type: Literal["list"] = "list"
    items: list[NativeListItem]


class TableBlock(_CamelModel):
    type: Literal["table"] = "table"
    columns: list[NativeTableColumn] = Field(min_length=1)
    #: One object per row, keyed by the column `key`.
    rows: list[dict[str, str | int | float]]
    caption: str | None = None

    @model_validator(mode="after")
    def _unique_keys(self) -> TableBlock:
        keys = [c.key for c in self.columns]
        if len(keys) != len(set(keys)):
            raise ValueError("The column `key`s of a `table` must be unique.")
        return self


class MapBlock(_CamelModel):
    type: Literal["map"] = "map"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: str | None = None
    #: Visible area in meters.
    span: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)


class FileBlock(_CamelModel):
    type: Literal["file"] = "file"
    #: `https` URL; a tap previews it. URLs on the web app's own backend load
    #: with its token.
    url: str
    name: str | None = None
    mime: str | None = None

    @model_validator(mode="after")
    def _https(self) -> FileBlock:
        _require_https(self.url, "`url` of a `file` block")
        return self


class VideoBlock(_CamelModel):
    type: Literal["video"] = "video"
    url: str
    poster: str | None = None

    @model_validator(mode="after")
    def _https(self) -> VideoBlock:
        _require_https(self.url, "`url` of a `video` block")
        _require_https(self.poster, "`poster` of a `video` block")
        return self


class CalloutBlock(_CamelModel):
    type: Literal["callout"] = "callout"
    style: Literal["info", "success", "warning", "error"]
    title: str | None = None
    text: str


class BadgesBlock(_CamelModel):
    type: Literal["badges"] = "badges"
    items: list[NativeBadge]


class ButtonsBlock(_CamelModel):
    type: Literal["buttons"] = "buttons"
    items: list[NativeAction]


class KpiBlock(_CamelModel):
    type: Literal["kpi"] = "kpi"
    #: The same data as the `kpi` dashboard widget.
    data: KpiData


class StatsBlock(_CamelModel):
    type: Literal["stats"] = "stats"
    data: StatsData


class ChartBlock(_CamelModel):
    type: Literal["chart"] = "chart"
    data: ChartData


class ProgressBlock(_CamelModel):
    type: Literal["progress"] = "progress"
    data: ProgressData


class FieldsBlock(_CamelModel):
    type: Literal["fields"] = "fields"
    #: Form fields inside content. Their values come back with an action that
    #: has `submit=True`.
    fields: list[ActionField] = Field(min_length=1)


class CardBlock(_CamelModel):
    type: Literal["card"] = "card"
    title: str | None = None
    blocks: list[NativeContentBlock]


class RowBlock(_CamelModel):
    type: Literal["row"] = "row"
    #: Two or three blocks side by side.
    blocks: list[NativeContentBlock]


class DividerBlock(_CamelModel):
    type: Literal["divider"] = "divider"


class SpacerBlock(_CamelModel):
    type: Literal["spacer"] = "spacer"
    height: float | None = Field(default=None, ge=0)


NativeContentBlock = Annotated[
    HeadingBlock
    | TextBlock
    | ImageBlock
    | FactsBlock
    | ListBlock
    | TableBlock
    | MapBlock
    | FileBlock
    | VideoBlock
    | CalloutBlock
    | BadgesBlock
    | ButtonsBlock
    | KpiBlock
    | StatsBlock
    | ChartBlock
    | ProgressBlock
    | FieldsBlock
    | CardBlock
    | RowBlock
    | DividerBlock
    | SpacerBlock,
    Field(discriminator="type"),
]
"""A block of a `NativeContent`, discriminated by `type`."""


class NativeContent(_SurfaceBase):
    """Definition of a content screen for `showContent`."""

    subtitle: str | None = None
    blocks: list[NativeContentBlock]
    #: Buttons in the footer, at most 4.
    actions: list[NativeAction] | None = None

    @model_validator(mode="after")
    def _check(self) -> NativeContent:
        _check_content_limits(self)
        _check_definition_size(self)
        return self


def _iter_blocks(blocks: Sequence[Any], depth: int = 0) -> Iterator[tuple[Any, int]]:
    for block in blocks:
        yield block, depth
        if isinstance(block, CardBlock | RowBlock):
            yield from _iter_blocks(block.blocks, depth + 1)


def _content_actions(content: NativeContent) -> list[NativeAction]:
    actions = list(content.actions or [])
    for block, _ in _iter_blocks(content.blocks):
        if isinstance(block, ButtonsBlock):
            actions.extend(block.items)
        elif isinstance(block, ListBlock):
            actions.extend(item.action for item in block.items if item.action)
    return actions


def _chain_depth(content: NativeContent) -> int:
    deepest = 0
    for action in _content_actions(content):
        for step in action.then or []:
            if isinstance(step, ShowFormStep):
                deepest = max(deepest, 1)
            elif isinstance(step, ShowContentStep):
                deepest = max(deepest, 1 + _chain_depth(step.show_content))
    return deepest


def _check_content_limits(content: NativeContent) -> None:
    blocks = list(_iter_blocks(content.blocks))
    if len(blocks) > MAX_CONTENT_BLOCKS:
        raise ValueError(f"{len(blocks)} blocks, the app takes at most {MAX_CONTENT_BLOCKS}.")
    deepest = max((depth for _, depth in blocks), default=0)
    if deepest > MAX_BLOCK_NESTING:
        raise ValueError(
            f"Blocks are nested {deepest} deep, the app takes at most {MAX_BLOCK_NESTING}."
        )
    if len(content.actions or []) > MAX_FOOTER_ACTIONS:
        raise ValueError(
            f"{len(content.actions or [])} footer actions, the app takes at most "
            f"{MAX_FOOTER_ACTIONS}."
        )
    images = sum(
        _decoded_data_uri_bytes(block.data)
        for block, _ in blocks
        if isinstance(block, ImageBlock) and block.data
    )
    if images > MAX_INLINE_IMAGES_BYTES:
        raise ValueError(
            f"Inline images add up to {images} bytes, the app takes at most "
            f"{MAX_INLINE_IMAGES_BYTES}."
        )
    for block, _ in blocks:
        if isinstance(block, FieldsBlock):
            for field in block.fields:
                _check_field_limits(field)
    if (chain := _chain_depth(content)) > MAX_CHAIN_DEPTH:
        raise ValueError(f"{chain} chained surfaces, the app takes at most {MAX_CHAIN_DEPTH}.")


# `NativeAction`, the steps and the blocks refer to each other: resolve now
# that every name exists.
for _model in (
    NativeAction,
    ShowFormStep,
    ShowContentStep,
    NativeListItem,
    ListBlock,
    ButtonsBlock,
    CardBlock,
    RowBlock,
    NativeContent,
):
    _model.model_rebuild()


def dump_native_form(form: NativeForm) -> dict[str, Any]:
    """The form as a JSON-ready dict in the app format (camelCase, without
    `None` fields), e.g. for an endpoint of your own."""
    return form.model_dump(mode="json", by_alias=True, exclude_none=True)


def dump_native_content(content: NativeContent) -> dict[str, Any]:
    """The content as a JSON-ready dict in the app format (camelCase,
    without `None` fields), e.g. for an endpoint of your own."""
    return content.model_dump(mode="json", by_alias=True, exclude_none=True)
