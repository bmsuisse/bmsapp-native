"""What the app checks before it acts on a call of contract 2026-11b (`invalid`).

Written independently of the npm package: the contract fixtures run through both, so
a rule that only one side knows shows up as a failing test. Every function returns
`None` for a valid payload and a sentence for an invalid one. Menus and search
answers use the Pydantic models of `bmsdna-app-native`.
"""

import datetime
import re
from typing import Any
from urllib.parse import urlsplit

from bmsdna.app_native import NativeMenu, SurfaceSearchAnswer, check_menu_sections
from bmsdna.app_native.menus import MenuSection
from pydantic import TypeAdapter, ValidationError

_NAMED_KEYS = {"up", "down", "left", "right", "escape", "return", "tab", "delete"}
_MODIFIERS = {"command", "option", "shift", "control"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def anchor_problem(anchor: Any) -> str | None:
    if not isinstance(anchor, dict):
        return "anchor has to be an object"
    for key in ("x", "y", "width", "height"):
        if not _is_number(anchor.get(key)):
            return f"anchor.{key} has to be a number"
    return None


def menu_problem(body: dict[str, Any]) -> str | None:
    if (problem := anchor_problem(body.get("anchor"))) is not None:
        return problem
    menu = {key: value for key, value in body.items() if key not in ("anchor", "action")}
    try:
        NativeMenu.model_validate(menu)
    except ValidationError as error:
        return str(error.errors()[0]["msg"])
    return None


def menu_items_problem(
    body: dict[str, Any], menu: dict[str, Any] | None, requests: dict[str, str]
) -> str | None:
    """`menuItems`: the sections answering the lazy item that `requestId` was asked for
    (`requests` maps request ids to item ids) of the `menu` that was shown last."""
    if not _text(body.get("requestId")):
        return "requestId is required"
    try:
        sections = TypeAdapter(list[MenuSection]).validate_python(body.get("sections"))
    except ValidationError as error:
        return str(error.errors()[0]["msg"])
    if menu is None:
        return None
    try:
        check_menu_sections(
            sections,
            depth=menu["lazy"].get(requests.get(body["requestId"], ""), 0) + 1,
            taken_ids=menu["ids"],
            taken_items=menu["count"],
        )
    except ValueError as error:
        return str(error)
    return None


def lazy_index(menu: NativeMenu) -> dict[str, Any]:
    """Ids, item count and the depth of each lazy item of a root menu."""
    ids: set[str] = set()
    lazy: dict[str, int] = {}
    count = 0

    def visit(sections: list[MenuSection], depth: int) -> None:
        nonlocal count
        for section in sections:
            for item in section.items:
                count += 1
                ids.add(item.id)
                if item.children == "lazy":
                    lazy[item.id] = depth
                elif isinstance(item.children, list):
                    visit(item.children, depth + 1)

    visit(menu.sections, 0)
    return {"ids": ids, "count": count, "lazy": lazy}


def _alert_actions_problem(actions: Any) -> str | None:
    if not isinstance(actions, list) or not 1 <= len(actions) <= 6:
        return "1 to 6 actions"
    cancels = 0
    for action in actions:
        if not isinstance(action, dict) or not _text(action.get("id")):
            return "an action needs an id"
        if not isinstance(action.get("label"), str):
            return "an action needs a label"
        if action.get("style", "default") not in ("default", "cancel", "destructive"):
            return "action style"
        if "preferred" in action and not isinstance(action["preferred"], bool):
            return "preferred"
        cancels += action.get("style") == "cancel"
    return "at most one cancel action" if cancels > 1 else None


def alert_problem(body: dict[str, Any]) -> str | None:
    if not _text(body.get("title")):
        return "title is required"
    style = body.get("style", "alert")
    if style not in ("alert", "actionSheet"):
        return "style"
    if "anchor" in body and (problem := anchor_problem(body["anchor"])) is not None:
        return problem
    if (problem := _alert_actions_problem(body.get("actions"))) is not None:
        return problem
    field = body.get("textField")
    if field is not None:
        if style != "alert" or not isinstance(field, dict):
            return "textField only with style alert"
        if field.get("keyboard", "default") not in ("default", "decimal", "number", "email"):
            return "keyboard"
        max_length = field.get("maxLength")
        if "maxLength" in field and not (
            isinstance(max_length, int) and not isinstance(max_length, bool) and max_length >= 1
        ):
            return "maxLength"
    return None


def toast_problem(body: dict[str, Any]) -> str | None:
    if not isinstance(body.get("message"), str):
        return "message is required"
    if body.get("style", "info") not in ("info", "success", "warning", "error"):
        return "style"
    duration = body.get("duration")
    if "duration" in body and not (_is_number(duration) and 1 <= duration <= 10):
        return "duration is 1 to 10 seconds"
    action = body.get("action")
    if "action" in body and not (
        isinstance(action, dict) and _text(action.get("id")) and _text(action.get("label"))
    ):
        return "an action needs an id and a label"
    return None


def update_surface_problem(body: dict[str, Any]) -> str | None:
    if not _text(body.get("id")):
        return "id is required"
    for key in ("title", "subtitle"):
        if key in body and not isinstance(body[key], str):
            return f"{key} has to be a string"
    for key in ("blocks", "actions", "fields", "pages"):
        if key in body and not isinstance(body[key], list):
            return f"{key} has to be a list"
    if "values" in body and not isinstance(body["values"], dict):
        return "values has to be an object"
    return None


def search_answer_problem(body: dict[str, Any]) -> str | None:
    try:
        SurfaceSearchAnswer.model_validate({k: v for k, v in body.items() if k != "action"})
    except ValidationError as error:
        return str(error.errors()[0]["msg"])
    return None


def keyboard_toolbar_problem(body: dict[str, Any]) -> str | None:
    items = body.get("items")
    if not isinstance(items, list) or len(items) > 6:
        return "at most 6 items"
    if "done" in body and not isinstance(body["done"], bool):
        return "done"
    for item in items:
        if not isinstance(item, dict) or not _text(item.get("id")):
            return "an item needs an id"
        if not (_text(item.get("label")) or _text(item.get("icon"))):
            return "an item needs a label or an icon"
        if item.get("style", "plain") not in ("plain", "prominent"):
            return "style"
    return None


def key_commands_problem(body: dict[str, Any]) -> str | None:
    commands = body.get("commands")
    if not isinstance(commands, list) or len(commands) > 60:
        return "at most 60 commands"
    for command in commands:
        if not isinstance(command, dict) or not _text(command.get("id")):
            return "a command needs an id"
        key = command.get("input")
        if not (isinstance(key, str) and (key in _NAMED_KEYS or len(key) == 1)):
            return "input is one character or a key name"
        modifiers = command.get("modifiers")
        if not isinstance(modifiers, list) or not set(modifiers) <= _MODIFIERS:
            return "modifiers"
        if not _text(command.get("title")):
            return "a command needs a title"
        if "group" in command and not isinstance(command["group"], str):
            return "group"
    return None


def _highlights_problem(highlights: Any) -> str | None:
    if not isinstance(highlights, list) or len(highlights) > 500:
        return "at most 500 highlights"
    ids: set[str] = set()
    for h in highlights:
        if not isinstance(h, dict) or not _text(h.get("id")) or h["id"] in ids:
            return "highlight ids are required and unique"
        ids.add(h["id"])
        page = h.get("page")
        if not (isinstance(page, int) and not isinstance(page, bool) and page >= 1):
            return "page is 1-based"
        if not all(_is_number(h.get(k)) and 0 <= h[k] <= 1 for k in ("x", "y", "w", "h")):
            return "x, y, w, h are fractions"
        if h.get("style") not in ("primary", "secondary"):
            return "style"
    return None


def document_problem(body: dict[str, Any], host: str | None, *, update: bool) -> str | None:
    if "id" in body and not _text(body["id"]):
        return "id"
    if update and not _text(body.get("id")):
        return "id is required"
    if "page" in body and not (
        isinstance(body["page"], int) and not isinstance(body["page"], bool) and body["page"] >= 1
    ):
        return "page is 1-based"
    if "selected" in body and not _text(body["selected"]):
        return "selected"
    if "title" in body and not isinstance(body["title"], str):
        return "title"
    if "highlights" in body and (problem := _highlights_problem(body["highlights"])) is not None:
        return problem
    if update:
        return None
    url = body.get("url")
    if not _text(url):
        return "url is required"
    parts = urlsplit(url)
    if parts.scheme not in ("", "http", "https") or (parts.netloc and parts.netloc != host):
        return "url has to be on the web app's own origin"
    return None


def _date_problem(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE.match(value):
        return True
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return True
    return False


def picker_problem(body: dict[str, Any]) -> str | None:
    kind = body.get("kind")
    if kind not in ("date", "option"):
        return "kind"
    if "anchor" in body and (problem := anchor_problem(body["anchor"])) is not None:
        return problem
    if kind == "date":
        if any(key in body and _date_problem(body[key]) for key in ("value", "min", "max")):
            return "dates are YYYY-MM-DD"
        return None
    options = body.get("options")
    if not isinstance(options, list) or not 1 <= len(options) <= 200:
        return "1 to 200 options"
    for option in options:
        if not (
            isinstance(option, dict)
            and isinstance(option.get("value"), str)
            and isinstance(option.get("label"), str)
        ):
            return "an option needs a value and a label"
    return None


def chrome_problem(chrome: dict[str, Any]) -> str | None:
    """The 2026-11b parts of `setChrome`: title, search, segments, sidebar, undo and the
    menus of action buttons. The app drops what is invalid."""
    for button in chrome.get("actionButtons") or []:
        if isinstance(button, dict) and "menu" in button:
            try:
                NativeMenu.model_validate({"sections": button["menu"]})
            except ValidationError as error:
                return str(error.errors()[0]["msg"])
    checks = (
        ("title", _title_problem),
        ("search", _search_problem),
        ("segments", _segments_problem),
        ("sidebar", _sidebar_problem),
        ("undo", _undo_problem),
    )
    for key, check in checks:
        if key in chrome and (problem := check(chrome[key])) is not None:
            return problem
    return None


def _title_problem(title: Any) -> str | None:
    if not isinstance(title, dict) or not _text(title.get("text")):
        return "title.text is required"
    if "subtitle" in title and not isinstance(title["subtitle"], str):
        return "title.subtitle"
    if "menu" in title:
        try:
            NativeMenu.model_validate({"sections": title["menu"]})
        except ValidationError as error:
            return str(error.errors()[0]["msg"])
    return None


def _search_problem(search: Any) -> str | None:
    if not isinstance(search, dict) or not _text(search.get("id")):
        return "search.id is required"
    if not isinstance(search.get("placeholder"), str):
        return "search.placeholder is required"
    scopes = search.get("scopes")
    if scopes is not None:
        ids = (
            [s.get("id") for s in scopes if isinstance(s, dict)] if isinstance(scopes, list) else []
        )
        if len(ids) != len(scopes) or len(set(ids)) != len(ids) or not all(map(_text, ids)):
            return "scopes"
        if "scope" in search and search["scope"] not in ids:
            return "scope has to be one of the scopes"
    elif "scope" in search:
        return "scope without scopes"
    if "barcode" in search and not isinstance(search["barcode"], bool):
        return "barcode"
    return None


def _segments_problem(segments: Any) -> str | None:
    if not isinstance(segments, dict) or not _text(segments.get("id")):
        return "segments.id is required"
    items = segments.get("items")
    if not isinstance(items, list) or not 2 <= len(items) <= 5:
        return "2 to 5 items"
    ids = []
    for item in items:
        if not (
            isinstance(item, dict) and _text(item.get("id")) and isinstance(item.get("label"), str)
        ):
            return "an item needs an id and a label"
        if "badge" in item and not isinstance(item["badge"], str):
            return "badge is a string"
        ids.append(item["id"])
    if len(set(ids)) != len(ids) or segments.get("selected") not in ids:
        return "ids are unique and selected is one of them"
    return None


def _sidebar_problem(sidebar: Any) -> str | None:
    if not isinstance(sidebar, dict) or not isinstance(sidebar.get("title"), str):
        return "sidebar.title is required"
    if "search" in sidebar and not (
        isinstance(sidebar["search"], dict)
        and isinstance(sidebar["search"].get("placeholder"), str)
    ):
        return "sidebar.search needs a placeholder"
    sections = sidebar.get("sections")
    if not isinstance(sections, list):
        return "sections"
    count = 0
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("items"), list):
            return "a section needs items"
        for item in section["items"]:
            count += 1
            if not (
                isinstance(item, dict)
                and _text(item.get("id"))
                and isinstance(item.get("label"), str)
            ):
                return "an item needs an id and a label"
            for action in item.get("trailingActions") or []:
                if not (isinstance(action, dict) and _text(action.get("id"))):
                    return "an action needs an id"
    return "at most 300 items" if count > 300 else None


def _undo_problem(undo: Any) -> str | None:
    if not isinstance(undo, dict):
        return "undo"
    if not (isinstance(undo.get("canUndo"), bool) and isinstance(undo.get("canRedo"), bool)):
        return "canUndo and canRedo are booleans"
    if any(key in undo and not isinstance(undo[key], str) for key in ("undoLabel", "redoLabel")):
        return "labels are strings"
    return None
