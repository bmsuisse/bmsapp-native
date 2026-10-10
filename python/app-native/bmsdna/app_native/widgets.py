"""Dashboard widgets for the home tab of the iOS app.

Each web app can place widgets on the native dashboard, such as KPIs,
statistics, lists, charts, news or actions. The app only renders them; content
and logic live entirely in your backend. There are three ways onto the device:

1. **Feed** (`create_widget_feed_router`): The app fetches `GET <prefix>/widgets`
   itself, on launch, when returning to the foreground and via
   pull-to-refresh. This also works if the user has never opened your web
   app.
2. **Push** (`send_widget_update` in `apns.py`): A silent push sends the
   widgets directly or triggers the feed fetch.
3. **JS bridge** (`BMSNative.call('setWidgets', ...)`): live from the
   open web page, without the toolkit.

Buttons in widgets arrive as `POST <prefix>/widget-actions` in
`create_widget_action_router`. The response can update the widget
immediately. Search fields and lazily loaded select fields in forms fetch
their options via `POST <prefix>/widget-options` (`create_widget_options_router`).
The same endpoint serves the native forms that a web page opens itself
(`surfaces.py`): the request then carries `form_id` instead of `widget_id`.

The format is the same in all three cases (schema v1, see
`docs/dashboard-widgets-guide.md`). The models here validate it so that
typos show up in the backend rather than only on the device. The app
silently discards invalid widgets, after all.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic.alias_generators import to_camel

#: Current version of the widget format (field `schema` in the feed).
WIDGET_SCHEMA_VERSION = 1


class _CamelModel(BaseModel):
    """JSON fields in camelCase (`defaultEnabled`, `maxVisible`, ...), as the
    app expects them. In Python you can still write snake_case
    (`default_enabled=False`)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Value = str | int | float
"""Display value: the app formats numbers according to the device language,
strings appear unchanged (e.g. `"CHF 1'200"`)."""


class Trend(_CamelModel):
    direction: Literal["up", "down", "flat"] = "flat"
    text: str | None = None
    #: Whether the direction is "good" (green). Default: rising = good. Set to
    #: `False` for e.g. complaints.
    positive: bool | None = None


class ActionButton(_CamelModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    style: Literal["primary", "secondary", "destructive"] = "primary"
    icon: str | None = None
    #: Confirmation prompt before executing, e.g. "Really cancel?".
    confirm: str | None = None
    #: Require confirmation via Face ID/Touch ID before executing. This is
    #: only a UX confirmation on the device, not proof that can be verified
    #: on the server. `None` rather than `False` as the default, so that it
    #: doesn't appear in the JSON at all (and thus not in the silent push,
    #: see `MAX_INLINE_WIDGETS_BYTES`).
    biometric: bool | None = None


# --- Content per kind -----------------------------------------------------


class KpiData(_CamelModel):
    value: Value
    unit: str | None = None
    caption: str | None = None
    trend: Trend | None = None


class StatItem(_CamelModel):
    label: str
    value: Value
    trend: Trend | None = None


class StatsData(_CamelModel):
    items: list[StatItem] = Field(min_length=1, max_length=4)


class ListItem(_CamelModel):
    id: str = Field(min_length=1)
    title: str
    subtitle: str | None = None
    trailing: Value | None = None
    icon: str | None = None
    tint: str | None = None
    #: Path in the web app that opens when the row is tapped.
    path: str | None = None
    #: Buttons directly on the row (at most 2 are shown). On tap, the row's
    #: `id` comes along as `item_id` in `WidgetActionReceived`.
    actions: list[ActionButton] | None = None


class ListData(_CamelModel):
    items: list[ListItem] = []
    #: How many entries are visible at most, followed by "+ N more".
    #: The default is 5.
    max_visible: int | None = Field(default=None, ge=1)
    empty_text: str | None = None


class ChartPoint(_CamelModel):
    x: Value
    y: float


class ChartSeries(_CamelModel):
    name: str | None = None
    color: str | None = None
    points: list[ChartPoint]


class ChartData(_CamelModel):
    type: Literal["bar", "line", "area"] = "bar"
    series: list[ChartSeries] = Field(min_length=1)
    unit: str | None = None


class ProgressData(_CamelModel):
    value: float
    total: float | None = None
    caption: str | None = None
    style: Literal["bar", "ring"] = "bar"


class TextData(_CamelModel):
    #: Inline Markdown (**bold**, _italic_, [links](https://...)).
    markdown: str
    #: Label of a link below the text that opens the web app at the
    #: widget's `path`.
    link_label: str | None = None


class NewsItem(_CamelModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    #: Teaser text below the title (2–3 lines visible).
    text: str | None = None
    #: Cover image, absolute or relative to the web app's page. If it is on
    #: the web app's host, the app loads it with the web app's session cookie.
    image_url: str | None = None
    #: Path or full URL of the complete article (tap on the row).
    path: str | None = None
    #: Publication date, please with time zone.
    date: datetime | None = None
    #: Extra text next to the date, e.g. the author.
    caption: str | None = None
    #: Channels (sections) of the article. The app turns these into tabs in
    #: the tile, and the user can subscribe to channels: new articles in them
    #: show up as notifications. So keep `id`s stable.
    channels: list[str] | None = None


class NewsData(_CamelModel):
    #: Newest first. How many are visible depends on the tile size
    #: (2 × 2: two, 2 × 6: seven, or six with tabs). With channels, feel free
    #: to deliver more, so that rare channels also show something in their tab.
    items: list[NewsItem] = []
    empty_text: str | None = None


class ActionOption(_CamelModel):
    value: str
    label: str | None = None
    #: Second line below `label`, only visible in search results (field type
    #: `search`) and lazily loaded select lists, e.g. "Cust. no. 10023 · Zürich".
    subtitle: str | None = None


ConditionValue = str | float | bool


class ActionCondition(_CamelModel):
    """Condition for `ActionField.visible_if`: the field only appears if
    the field `field` has a matching value."""

    #: `id` of another field of the same form (also on an earlier
    #: page).
    field: str = Field(min_length=1)
    #: A value or a list of allowed values, e.g. `True` for a
    #: toggle or `["A1", "A2"]` for a select. If omitted: visible
    #: as soon as `field` is filled in or switched on.
    equals: ConditionValue | list[ConditionValue] | None = None


ActionFieldType = Literal[
    "text",
    "number",
    "select",
    "toggle",
    "date",
    "search",
    "textarea",
    "email",
    "phone",
    "url",
    "multiselect",
    "segmented",
    "stepper",
    "time",
    "datetime",
    "info",
    "photo",
    "scan",
    "signature",
    "barcode",
    "repeat",
]
"""The field types of a form, in widgets and in native forms. An older app
shows a type it does not know as `text`."""

#: The field types allowed inside a `repeat` group.
REPEAT_INNER_FIELD_TYPES = frozenset(
    {"text", "number", "select", "toggle", "date", "textarea", "stepper"}
)

#: `photo.max` is 1 to this value (default in the app: 5).
MAX_PHOTOS_PER_FIELD = 10
#: `photo.max_dimension` is at least this many pixels ...
MIN_PHOTO_DIMENSION = 256
#: ... and at most this many.
MAX_PHOTO_DIMENSION = 4096
#: `scan.max` (pages) is 1 to this value (default in the app: 10).
MAX_SCAN_PAGES = 20
#: `repeat.max` is at most this many rows.
MAX_REPEAT_ROWS = 50
#: A `repeat` group has 1 to this many fields per row.
MAX_REPEAT_FIELDS = 10

BarcodeSymbology = Literal[
    "aztec",
    "codabar",
    "code39",
    "code93",
    "code128",
    "dataMatrix",
    "ean8",
    "ean13",
    "i2of5",
    "itf14",
    "pdf417",
    "qr",
    "upce",
]
"""The symbologies a `barcode` field can be restricted to."""

Number = int | float


class SurfaceLimitError(ValueError):
    """A definition is beyond a limit of the app (`MAX_*`): the app answers
    `tooLarge`, nothing is cut silently. Every other problem of a definition is
    `invalid`.

    The models raise it inside their validators, so Pydantic reports it as a
    `ValidationError`; the exception itself is `error["ctx"]["error"]` of the
    entry in `ValidationError.errors()`. A backend that answers like the app
    can tell the two apart that way.
    """


class ActionField(_CamelModel):
    """A form field of an `action` widget or of a native form (`NativeForm`).

    One flat model for all types; which properties apply to which type is
    described per property, and the validator rejects what cannot work
    (a `repeat` without `fields`, `photo.max` of 11, ...).
    """

    id: str = Field(min_length=1)
    #: `search` is a search field whose results the app fetches from your
    #: backend while typing, via `create_widget_options_router` (Meilisearch,
    #: SQL, whatever you have). The `value` of the selected result is
    #: submitted. The media types `photo`, `scan` and `signature` give
    #: `NativeFileRef`s in native forms, `repeat` an array of objects.
    type: ActionFieldType = "text"
    label: str | None = None
    placeholder: str | None = None
    #: Footnote under the field.
    help: str | None = None
    #: Fixed choices for `select`, `multiselect` and `segmented`. Ignored with
    #: `remote=True` or `search`.
    options: list[ActionOption] | None = None
    #: `select` only: load the options via `create_widget_options_router`
    #: when the field is shown (with `query=""` and the values entered so
    #: far, e.g. contacts of the customer selected on page 1).
    remote: bool | None = None
    #: `search` only: the number of characters from which searching starts.
    #: At 0 the app already loads suggestions on open (`query=""`). Default
    #: in the app: 2.
    min_query_length: int | None = Field(default=None, ge=0)
    required: bool | None = None
    #: Only show the field if another field has a certain value,
    #: e.g. `ActionCondition(field="express", equals=True)`. Hidden
    #: fields are never required and are not included in `values`. If a
    #: page has no visible field, the app skips it.
    visible_if: ActionCondition | None = None
    #: Prefilled value. Date fields expect "YYYY-MM-DD", `time` "HH:mm",
    #: `datetime` "YYYY-MM-DDTHH:mm" (device-local), search and select fields
    #: the `value` of an option, `multiselect` a list of them.
    value: str | float | bool | list[str] | list[dict[str, Any]] | None = None
    #: `search`/`select` with `remote` only: display text for the prefilled
    #: `value`, as long as nothing has been loaded yet.
    value_label: str | None = None
    #: Text fields (`text`, `textarea`, `email`, `phone`, `url`, `barcode`):
    #: length limits.
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    #: `number` and `stepper`: bounds. `photo`: the number of pictures
    #: (`max`, 1 to 10, default 5). `scan`: the number of pages (`max`, 1 to 20,
    #: default 10). `repeat`: the number of rows (`min`, `max` up to 50).
    min: Number | None = None
    max: Number | None = None
    #: `stepper` only: the step, default 1.
    step: int | None = Field(default=None, ge=1)
    #: Text fields: regular expression the whole input has to match, and the
    #: text shown when it does not. (The app uses ICU regular expressions,
    #: so the pattern is not checked here.)
    pattern: str | None = None
    pattern_message: str | None = None
    #: `photo` only. Default in the app: `both`.
    source: Literal["camera", "library", "both"] | None = None
    #: `photo` only: longest side in pixels after downscaling, 256 to 4096.
    #: Default 2048.
    max_dimension: int | None = Field(default=None, ge=MIN_PHOTO_DIMENSION, le=MAX_PHOTO_DIMENSION)
    #: `scan` only: `jpeg` (default, one file per page) or `pdf` (one file).
    format: Literal["jpeg", "pdf"] | None = None
    #: `barcode` only: restrict the scanner to these symbologies. Default: all.
    symbologies: list[BarcodeSymbology] | None = None
    #: `repeat` only: the fields of one row. Only `text`, `number`, `select`,
    #: `toggle`, `date`, `textarea` and `stepper`; no nested `repeat`.
    fields: list[ActionField] | None = None
    #: `repeat` only: label of the "add row" button.
    add_label: str | None = None

    @model_validator(mode="after")
    def _check_type_specific(self) -> ActionField:
        if self.type == "repeat":
            _check_repeat(self)
        elif self.fields is not None:
            raise ValueError(f"`{self.id}`: `fields` only belongs to the type `repeat`.")
        if self.type in ("multiselect", "segmented") and not self.options:
            raise ValueError(f"`{self.id}`: type `{self.type}` needs `options`.")
        _check_ranges(self)
        return self


def _check_ranges(field: ActionField) -> None:
    counts = {"photo": MAX_PHOTOS_PER_FIELD, "scan": MAX_SCAN_PAGES}
    limit = counts.get(field.type)
    if limit is not None and field.max is not None and not 1 <= field.max <= limit:
        raise ValueError(f"`{field.id}`: `max` of a `{field.type}` is 1 to {limit}.")
    if field.min is not None and field.max is not None and field.min > field.max:
        raise ValueError(f"`{field.id}`: `min` is greater than `max`.")
    if (
        field.min_length is not None
        and field.max_length is not None
        and field.min_length > field.max_length
    ):
        raise ValueError(f"`{field.id}`: `min_length` is greater than `max_length`.")


def _check_repeat(field: ActionField) -> None:
    if not field.fields or len(field.fields) > MAX_REPEAT_FIELDS:
        raise ValueError(f"`{field.id}`: a `repeat` group needs 1 to {MAX_REPEAT_FIELDS} `fields`.")
    for inner in field.fields:
        if inner.type not in REPEAT_INNER_FIELD_TYPES:
            raise ValueError(
                f"`{field.id}`: a `repeat` group cannot contain the type `{inner.type}` "
                f"(`{inner.id}`). Allowed: {', '.join(sorted(REPEAT_INNER_FIELD_TYPES))}."
            )
    for inner in field.fields:
        if inner.visible_if is not None:
            raise ValueError(
                f"`{field.id}`: `{inner.id}` has `visible_if`, which a `repeat` group "
                "does not support."
            )
    inner_ids = [inner.id for inner in field.fields]
    if len(inner_ids) != len(set(inner_ids)):
        raise ValueError(f"`{field.id}`: the `id`s inside a `repeat` group must be unique.")
    if field.max is not None and field.max > MAX_REPEAT_ROWS:
        raise SurfaceLimitError(
            f"`{field.id}`: a `repeat` group has at most {MAX_REPEAT_ROWS} rows."
        )


class ActionPage(_CamelModel):
    """One page of a multi-page form (`ActionData.pages`)."""

    #: Title in the navigation bar. Default: widget title.
    title: str | None = None
    #: Hint text above the fields of this page.
    text: str | None = None
    fields: list[ActionField] = Field(min_length=1)


class ActionData(_CamelModel):
    text: str | None = None
    #: Single-page form. For multiple pages use `pages` instead.
    fields: list[ActionField] | None = None
    #: Multi-page form: the user pages through with "Next" (required
    #: fields per page), and it is submitted on the last one.
    #: All values of all pages arrive together in `values`.
    pages: list[ActionPage] | None = Field(default=None, min_length=1)
    buttons: list[ActionButton] = Field(min_length=1)

    @model_validator(mode="after")
    def _fields_or_pages(self) -> ActionData:
        if self.fields and self.pages:
            raise ValueError("Specify either `fields` or `pages`, not both.")
        check_form_fields(self.fields, self.pages)
        return self


def check_form_fields(
    fields: Sequence[ActionField] | None, pages: Sequence[ActionPage] | None
) -> None:
    """Checks what widget forms and native forms have in common: the field
    `id`s are unique across all pages, and every `visible_if` refers to
    another field of the same form. Raises `ValueError`."""
    all_fields = [f for page in pages or [] for f in page.fields] + list(fields or [])
    ids = [f.id for f in all_fields]
    if len(ids) != len(set(ids)):
        raise ValueError("Field `id`s must be unique across all pages.")
    for f in all_fields:
        if f.visible_if and (f.visible_if.field == f.id or f.visible_if.field not in ids):
            raise ValueError(
                f"`visible_if` of `{f.id}` does not refer to another field of this form."
            )


# --- Widgets --------------------------------------------------------------


class _WidgetBase(_CamelModel):
    #: Unique within your web app. Must stay stable, because the app ties
    #: the user's order and visibility settings to it.
    id: str = Field(min_length=1, pattern=r"^[^/]+$")
    #: `small` = half width, `medium`/`large` = full width (1 or 2
    #: rows high), `tall` = full width over 4 rows, `xlarge` = full
    #: width over 6 rows (for long content
    #: such as news). If omitted, a default per kind applies (kpi/progress:
    #: small, news: large, otherwise medium). For news, the user can also
    #: choose between `large`, `tall` and `xlarge` themselves.
    size: Literal["small", "medium", "large", "tall", "xlarge"] | None = None
    title: str = ""
    #: SF Symbol name, e.g. "shippingbox".
    icon: str | None = None
    #: Hex color, e.g. "#2e4a62". If omitted, the web app's color applies.
    tint: str | None = None
    #: Mandatory widget: always visible, the user cannot hide it.
    required: bool = False
    #: Initial state, as long as the user hasn't configured anything.
    default_enabled: bool = True
    #: Path in the web app that opens when the widget is tapped.
    path: str | None = None
    #: Please include a time zone, e.g. `datetime.now(UTC)`.
    updated_at: datetime | None = None
    #: After this, the app shows the widget as "outdated" until new data
    #: arrives.
    expires_at: datetime | None = None


class KpiWidget(_WidgetBase):
    kind: Literal["kpi"] = "kpi"
    data: KpiData


class StatsWidget(_WidgetBase):
    kind: Literal["stats"] = "stats"
    data: StatsData


class ListWidget(_WidgetBase):
    kind: Literal["list"] = "list"
    data: ListData


class ChartWidget(_WidgetBase):
    kind: Literal["chart"] = "chart"
    data: ChartData


class ProgressWidget(_WidgetBase):
    kind: Literal["progress"] = "progress"
    data: ProgressData


class TextWidget(_WidgetBase):
    kind: Literal["text"] = "text"
    data: TextData


class ActionWidget(_WidgetBase):
    kind: Literal["action"] = "action"
    data: ActionData


class NewsWidget(_WidgetBase):
    kind: Literal["news"] = "news"
    data: NewsData


Widget = Annotated[
    KpiWidget
    | StatsWidget
    | ListWidget
    | ChartWidget
    | ProgressWidget
    | TextWidget
    | ActionWidget
    | NewsWidget,
    Field(discriminator="kind"),
]

_widget_list_adapter: TypeAdapter[list[Widget]] = TypeAdapter(list[Widget])


def dump_widgets(widgets: Sequence[Widget]) -> list[dict[str, Any]]:
    """Converts widgets into JSON-ready dicts in the app format (camelCase,
    without `None` fields). You need this e.g. for an endpoint of your own
    or the JS bridge."""
    return _widget_list_adapter.dump_python(
        list(widgets), mode="json", by_alias=True, exclude_none=True
    )


class WidgetFeed(_CamelModel):
    """Response of `GET <prefix>/widgets`."""

    schema_version: int = Field(default=WIDGET_SCHEMA_VERSION, alias="schema")
    widgets: list[Widget] = []


# --- Router ---------------------------------------------------------------


@dataclass(frozen=True)
class WidgetRequestContext:
    """What your callbacks learn about the request."""

    #: The app's device ID (the same as for `create_ingest_router`).
    device_id: str | None
    #: Return value of your `auth_dependency`, so typically the
    #: authenticated user. Take the identity of the caller from here, not
    #: from `user_email` in the request body: that field comes from the
    #: client and anyone can set it to any address.
    user: Any
    request: Request


WidgetProvider = Callable[[WidgetRequestContext], Awaitable[Sequence[Widget]]]


def create_widget_feed_router(
    *,
    get_widgets: WidgetProvider,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter for `GET <prefix>/widgets`.

    `get_widgets` returns the current widgets for the requesting user or
    device. The app replaces all widgets of your web app with them. So a
    widget that is no longer returned disappears from the
    dashboard.

    `auth_dependency` authenticates the call (see `auth.py`); its result is
    available in `context.user`.
    """
    router = APIRouter()
    auth = auth_dependency

    @router.get(
        "/widgets",
        response_model=WidgetFeed,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def get_feed(
        request: Request, device_id: str | None = None, user: Any = Depends(auth)
    ) -> WidgetFeed:
        widgets = await get_widgets(
            WidgetRequestContext(device_id=device_id, user=user, request=request)
        )
        return WidgetFeed(widgets=list(widgets))

    return router


class WidgetActionReceived(BaseModel):
    """Payload of `POST <prefix>/widget-actions`, i.e. a button tap on a
    dashboard widget."""

    device_id: str
    #: `id` of the widget.
    widget_id: str
    #: `id` of the tapped button.
    action_id: str
    #: `id` of the list row, if the button was attached to a row of a
    #: `list` widget.
    item_id: str | None = None
    #: Form values of an `action` widget, `{field_id: value}`. Number fields
    #: arrive as a number, toggles as a bool and date fields as "YYYY-MM-DD".
    values: dict[str, Any] = {}
    #: Email the app reports for the signed-in user, if the web app has
    #: `.identity`. Unverified client input: use `context.user` from your
    #: `auth_dependency` for identity and permissions.
    user_email: str | None = None
    #: `"homeScreen"` if the button was tapped in the widget on the Home
    #: Screen, otherwise (dashboard in the app) not set. There the app only
    #: shows `message` and the updated widgets from the response;
    #: `open_path` has no effect.
    source: Literal["homeScreen"] | None = None


class WidgetActionResult(_CamelModel):
    """Response to a widget action. All fields are optional."""

    #: `False` reports a refusal (e.g. "No permission"). The app then
    #: shows `message` as an error.
    ok: bool = True
    #: Short banner in the app.
    message: str | None = None
    style: Literal["info", "success", "warning", "error"] | None = None
    #: Replaces ALL widgets of your web app on the device.
    widgets: list[Widget] | None = None
    #: Replaces only this one widget (same `id`), e.g. the list without
    #: the entry that was just approved.
    widget: Widget | None = None
    #: Afterwards opens your web app at this path.
    open_path: str | None = None


class WidgetOptionsRequest(BaseModel):
    """Payload of `POST <prefix>/widget-options`: the app wants options for
    a search field or lazily loaded select field of an `action` widget, or of
    a native form that a web page opened (`showForm`).

    Exactly one of `widget_id` (widget form) and `form_id` (native form) is
    set. Existing callbacks that only look at `widget_id` keep working: for a
    native form it is `None`.
    """

    device_id: str
    #: `id` of the widget, for the form of an `action` widget.
    widget_id: str | None = None
    #: `id` of the native form (`NativeForm.id`), for a form opened with
    #: `showForm`. The app generates one if the page gave none.
    form_id: str | None = None
    #: `id` of the field (`type="search"` or `select` with `remote=True`).
    field_id: str
    #: Search text entered, empty for `select` or `min_query_length=0`.
    query: str = ""
    #: All values entered in the form so far (also from earlier
    #: pages), same format as `WidgetActionReceived.values`. This lets you
    #: build dependent fields.
    values: dict[str, Any] = {}
    #: The `context` object the page put into the definition of a native form,
    #: unchanged (e.g. the customer the form was opened for). Not to be
    #: confused with the second argument of your callback, the
    #: `WidgetRequestContext`. Client input like everything else here.
    context: dict[str, Any] | None = None
    #: See `WidgetActionReceived.user_email`.
    user_email: str | None = None

    @model_validator(mode="after")
    def _widget_or_form(self) -> WidgetOptionsRequest:
        if (self.widget_id is None) == (self.form_id is None):
            raise ValueError("Exactly one of `widget_id` and `form_id` must be set.")
        return self


class WidgetOptionsResult(_CamelModel):
    """Response to `POST <prefix>/widget-options`."""

    #: Results in the desired order. The app shows at most 50.
    options: list[ActionOption] = []
    #: Text when nothing was found. Default in the app: "No results".
    empty_text: str | None = None


WidgetOptionsCallback = Callable[
    [WidgetOptionsRequest, WidgetRequestContext],
    Awaitable[WidgetOptionsResult | Sequence[ActionOption]],
]


def create_widget_options_router(
    *,
    on_options_requested: WidgetOptionsCallback,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/widget-options`.

    The app calls it for search fields (`type="search"`) on every input
    (debounced) and for `select` fields with `remote=True` when they are shown.
    Where the results come from is up to you, e.g. a Meilisearch search:

        async def on_options(req, context):
            if req.field_id == "customer":
                hits = (await meili.index("customers").search(req.query, {"limit": 20}))["hits"]
                return [
                    ActionOption(value=h["id"], label=h["name"], subtitle=h["city"])
                    for h in hits
                ]
            return []

    The callback may return a `WidgetOptionsResult` or directly a list of
    `ActionOption`.
    """
    router = APIRouter()
    auth = auth_dependency

    @router.post(
        "/widget-options",
        response_model=WidgetOptionsResult,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def request_options(
        body: WidgetOptionsRequest, request: Request, user: Any = Depends(auth)
    ) -> WidgetOptionsResult:
        result = await on_options_requested(
            body, WidgetRequestContext(device_id=body.device_id, user=user, request=request)
        )
        if isinstance(result, WidgetOptionsResult):
            return result
        return WidgetOptionsResult(options=list(result))

    return router


WidgetActionCallback = Callable[
    [WidgetActionReceived, WidgetRequestContext],
    Awaitable[WidgetActionResult | None],
]


def create_widget_action_router(
    *,
    on_action_received: WidgetActionCallback,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter for `POST <prefix>/widget-actions`.

    As with the other routers there is no storage of its own: the action
    goes unchanged to your callback. Return `None` for a
    plain "ok", or a `WidgetActionResult` with a message or
    updated widgets.
    """
    router = APIRouter()
    auth = auth_dependency

    @router.post(
        "/widget-actions",
        response_model=WidgetActionResult,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def receive_action(
        body: WidgetActionReceived, request: Request, user: Any = Depends(auth)
    ) -> WidgetActionResult:
        result = await on_action_received(
            body, WidgetRequestContext(device_id=body.device_id, user=user, request=request)
        )
        return result or WidgetActionResult()

    return router
