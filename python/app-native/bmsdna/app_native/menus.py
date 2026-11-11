"""Menus and page search results that a backend can build server-side.

The page passes a menu to `showMenu` (or to the `menu` of an action button or of the
title in `setChrome`), and the options of a search field with `source: "page"` to
`surfaceSearchResult`. These models describe both, so that an endpoint of yours can
serve them and the page hands them over unchanged:

    @app.get("/api/offers/{offer_id}/menu", response_model_by_alias=True,
             response_model_exclude_none=True)
    async def offer_menu(offer_id: str) -> list[MenuSection]: ...

They check the limits of the app (`MAX_MENU_*`), so oversized menus show up in the
backend rather than as an `invalid` answer on the device. Format and examples:
`docs/menus-and-alerts-guide.md`.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .widgets import _CamelModel

#: Levels of submenus below the root menu.
MAX_MENU_DEPTH = 2
#: Items of one menu, all levels together.
MAX_MENU_ITEMS = 80
#: Characters of a label.
MAX_MENU_LABEL = 80
#: Seconds the page has to answer a lazy submenu.
MENU_LAZY_SECONDS = 5

#: Options of one page search answer.
MAX_SEARCH_OPTIONS = 50
#: One `image` of a search option as a `data:` URI, decoded, in bytes.
MAX_SEARCH_IMAGE_BYTES = 100 * 1024
#: Seconds the page has to answer a search.
SEARCH_ANSWER_SECONDS = 10

MenuLabel = Annotated[str, StringConstraints(max_length=MAX_MENU_LABEL)]


class MenuItem(_CamelModel):
    """One row of a native menu. Not the `MenuItem` of the hamburger menu
    (`setChrome({ menu })`), which the backend does not model."""

    #: Unique within the menu, all levels together. Comes back as the result.
    id: str = Field(min_length=1)
    #: At most 80 characters. Shown as delivered: localize it yourself.
    label: MenuLabel
    subtitle: str | None = None
    #: SF Symbol name.
    icon: str | None = None
    destructive: bool | None = None
    disabled: bool | None = None
    #: Shows a check mark.
    checked: bool | None = None
    #: A submenu: sections, or `"lazy"` to load them when the user opens the item
    #: (the page answers with `menuItems` within 5 seconds).
    children: list[MenuSection] | Literal["lazy"] | None = None
    #: Lazy items only: the disabled row shown if the page does not answer in time.
    lazy_failed_label: str | None = None


class MenuSection(_CamelModel):
    title: str | None = None
    items: list[MenuItem]


class MenuPreview(_CamelModel):
    """The card that is lifted from the anchor on iPhone."""

    title: str
    subtitle: str | None = None


def check_menu_sections(
    sections: Sequence[MenuSection],
    *,
    depth: int = 0,
    taken_ids: Collection[str] = (),
    taken_items: int = 0,
) -> int:
    """Checks the limits of a menu: submenus at most `MAX_MENU_DEPTH` levels below the
    root, at most `MAX_MENU_ITEMS` items in total, ids unique. Returns the number of
    items; raises `ValueError` otherwise.

    For the sections that answer a lazy item, pass the `depth` of that item plus one
    and what the menu already has: `taken_ids` and `taken_items`."""
    ids = set(taken_ids)
    total = _walk(sections, depth, ids)
    if taken_items + total > MAX_MENU_ITEMS:
        raise ValueError(f"{taken_items + total} items, the app takes at most {MAX_MENU_ITEMS}.")
    return total


def _walk(sections: Sequence[MenuSection], depth: int, ids: set[str]) -> int:
    total = 0
    for section in sections:
        for item in section.items:
            total += 1
            if item.id in ids:
                raise ValueError(f"The id `{item.id}` is used twice in the menu.")
            ids.add(item.id)
            if isinstance(item.children, list):
                if depth + 1 > MAX_MENU_DEPTH:
                    raise ValueError(
                        f"`{item.id}`: submenus are nested too deep, at most "
                        f"{MAX_MENU_DEPTH} levels below the root."
                    )
                total += _walk(item.children, depth + 1, ids)
    return total


class NativeMenu(_CamelModel):
    """A menu for `showMenu`, without the anchor (the page knows where it is):
    `showMenu({ ...menu, anchor })`."""

    id: str | None = Field(default=None, min_length=1)
    preview: MenuPreview | None = None
    sections: list[MenuSection]

    @model_validator(mode="after")
    def _limits(self) -> NativeMenu:
        check_menu_sections(self.sections)
        return self


class SurfaceSearchOption(_CamelModel):
    """One result of a search field with `source: "page"`; the page answers with
    at most 50 of them. Not `ActionOption`: the label is required and there is an
    `image`."""

    value: str
    label: str
    subtitle: str | None = None
    #: `https` URL, or a `data:` URI of at most 100 KB.
    image: str | None = None

    @model_validator(mode="after")
    def _image(self) -> SurfaceSearchOption:
        image = self.image
        if image is None:
            return self
        if image.lower().startswith("https://"):
            return self
        if image.lower().startswith("data:"):
            header, _, payload = image.partition(",")
            if header.lower().endswith(";base64"):
                size = len(payload) * 3 // 4 - (len(payload) - len(payload.rstrip("=")))
            else:
                size = len(payload.encode())
            if size <= MAX_SEARCH_IMAGE_BYTES:
                return self
            raise ValueError(f"An inline image is {size} bytes, at most {MAX_SEARCH_IMAGE_BYTES}.")
        raise ValueError("`image` must be an https URL or a data: URI.")


class SurfaceSearchAnswer(_CamelModel):
    """What the page sends as `surfaceSearchResult`: the `request_id` of the search
    and at most 50 results."""

    request_id: str = Field(min_length=1)
    options: list[SurfaceSearchOption] = Field(max_length=MAX_SEARCH_OPTIONS)


for _model in (MenuItem, MenuSection, NativeMenu):
    _model.model_rebuild()
