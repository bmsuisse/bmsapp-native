"""Shared sample payloads from `contract-fixtures/` (see the README there).

Every file must validate against the Pydantic models and serialize back
unchanged — a field that only the TypeScript side knows about would be
silently dropped by Pydantic, and that shows up here.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from bmsdna.app_native import (
    ActionField,
    ApprovalFeed,
    LiveActivityState,
    NativeContent,
    NativeDocument,
    NativeDocumentContext,
    NativeForm,
    NativeMenu,
    SurfaceSearchAnswer,
    Widget,
)
from bmsdna.app_native.documents import DocumentKind
from bmsdna.app_native.menus import MenuSection, check_menu_sections
from pydantic import TypeAdapter, ValidationError

FIXTURES = Path(__file__).resolve().parents[3] / "contract-fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def test_widgets_round_trip() -> None:
    raw = _load("widgets.json")
    adapter = TypeAdapter(list[Widget])
    widgets = adapter.validate_python(raw)
    dumped = adapter.dump_python(widgets, mode="json", by_alias=True, exclude_unset=True)
    assert dumped == raw


def test_approvals_round_trip() -> None:
    raw = _load("approvals.json")
    feed = ApprovalFeed.model_validate(raw)
    assert feed.model_dump(mode="json", by_alias=True, exclude_unset=True) == raw


def test_live_activity_state_round_trip() -> None:
    raw = _load("live-activity-state.json")
    state = LiveActivityState.model_validate(raw)
    assert state.model_dump(mode="json", by_alias=True, exclude_unset=True) == raw


def test_native_form_round_trip() -> None:
    raw = _load("native-form.json")
    form = NativeForm.model_validate(raw)
    assert form.model_dump(mode="json", by_alias=True, exclude_unset=True) == raw


def test_native_content_round_trip() -> None:
    raw = _load("native-content.json")
    content = NativeContent.model_validate(raw)
    assert content.model_dump(mode="json", by_alias=True, exclude_unset=True) == raw


# --- Contract 2026-11 -------------------------------------------------------------
# Documents are the part with a Python model. The options, layout, dictation and
# the like have none (the web app and the app talk, not the backend); the files are
# checked for their shape, and the e2e suite runs them through the npm package
# against the harness that plays the app.

_DOCUMENTS = TypeAdapter(list[NativeDocument])

_FILES = [
    "menu.json",
    "alert.json",
    "toast-action.json",
    "live-surface.json",
    "nav-search.json",
    "keyboard-toolbar.json",
    "segments.json",
    "sidebar.json",
    "document-viewer.json",
    "undo.json",
    "picker.json",
    "key-commands.json",
    "scan-result.json",
    "pick-files.json",
    "documents-received.json",
    "dictate.json",
    "layout.json",
    "back-requested.json",
    "preview-file.json",
    "access-token-resource.json",
]


def _entries(section: dict[str, Any]) -> list[dict[str, Any]]:
    return [*section.get("valid", []), *section.get("invalid", [])]


def _fill(template: Any, k: int) -> Any:
    if isinstance(template, str):
        return template.replace("{k}", str(k))
    if isinstance(template, list):
        return [_fill(v, k) for v in template]
    if isinstance(template, dict):
        return {key: _fill(v, k) for key, v in template.items()}
    return template


def _expand(value: Any) -> Any:
    """`"@N"` stands for N characters, `{"@repeat": N, "of": template}` for a list
    of N copies of the template with `{k}` replaced by 0 … N-1 (see the README)."""
    if isinstance(value, str) and value.startswith("@") and value[1:].isdigit():
        return "x" * int(value[1:])
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        if "@repeat" in value:
            return [_fill(_expand(value["of"]), k) for k in range(value["@repeat"])]
        return {k: _expand(v) for k, v in value.items()}
    return value


def _leaf_sections(node: dict[str, Any]) -> list[dict[str, Any]]:
    """The sections with `valid` / `invalid`, also when grouped (`events.search`)."""
    if "valid" in node or "invalid" in node:
        return [node]
    return [
        leaf for child in node.values() if isinstance(child, dict) for leaf in _leaf_sections(child)
    ]


@pytest.mark.parametrize("name", _FILES)
def test_2026_11_fixtures_have_the_expected_shape(name: str) -> None:
    raw = _load(name)
    assert isinstance(raw["description"], str)
    sections = [
        leaf for key, value in raw.items() if key != "description" for leaf in _leaf_sections(value)
    ]
    assert sections, "no sections"
    for section in sections:
        entries = _entries(section)
        assert entries, f"{name}: empty section"
        assert len({entry["name"] for entry in entries}) == len(entries), "names are unique"
        for entry in section.get("valid", []):
            assert "value" in entry and "error" not in entry
        for entry in section.get("invalid", []):
            assert "value" in entry and isinstance(entry["error"], str)


def _documents_of(value: Any) -> list[Any]:
    return value["documents"] if isinstance(value, dict) and "documents" in value else []


_DOCUMENT_SECTIONS = [
    ("scan-result.json", "results"),
    ("pick-files.json", "results"),
    ("documents-received.json", "events"),
    ("documents-received.json", "consume"),
]


@pytest.mark.parametrize(("name", "section"), _DOCUMENT_SECTIONS)
def test_native_documents_round_trip(name: str, section: str) -> None:
    for entry in _load(name)[section].get("valid", []):
        raw = _documents_of(entry["value"])
        documents = _DOCUMENTS.validate_python(raw)
        dumped = _DOCUMENTS.dump_python(documents, mode="json", by_alias=True, exclude_unset=True)
        assert dumped == raw, entry["name"]


@pytest.mark.parametrize(("name", "section"), _DOCUMENT_SECTIONS)
def test_malformed_native_documents_are_rejected(name: str, section: str) -> None:
    # Empty lists are for the app's "at least one" rule, not for the model; the
    # other malformed answers contain a document that cannot be one.
    for entry in _load(name)[section].get("invalid", []):
        raw = _documents_of(entry["value"])
        if not raw or not all(isinstance(d, dict) for d in raw):
            continue
        with pytest.raises(ValidationError):
            _DOCUMENTS.validate_python(raw)


def test_options_follow_the_context_and_kind_rules_of_the_models() -> None:
    context = TypeAdapter(NativeDocumentContext)
    kind = TypeAdapter(DocumentKind)
    for name in ("scan-result.json", "pick-files.json"):
        for case in _load(name)["options"]["valid"]:
            value = _expand(case["value"])
            if "context" in value:
                context.validate_python(value["context"])
            if "kind" in value:
                kind.validate_python(value["kind"])
        for case in _load(name)["options"]["invalid"]:
            value = _expand(case["value"])
            if "context" in value:
                with pytest.raises(ValidationError):
                    context.validate_python(value["context"])
            if "kind" in value:
                with pytest.raises(ValidationError):
                    kind.validate_python(value["kind"])


# --- Contract 2026-11b ---------------------------------------------------------------
# Menus, search options and the new field options have Python models; the rest (chrome,
# alerts, pickers, viewer, …) is TypeScript and app only and is checked by the shape.

_MENU_SECTION_PROBLEMS = {
    "81 items",
    "a label of 81 characters",
    "an id used twice",
    "an id used twice at different levels",
    "submenus three levels deep",
    "an item without id",
    "children neither sections nor lazy",
    "preview without title",
}


def _menu_of(case: dict[str, Any]) -> dict[str, Any]:
    value = _expand(case["value"])
    return {k: v for k, v in value.items() if k != "anchor"}


def test_menus_follow_the_limits_of_the_models() -> None:
    options = _load("menu.json")["options"]
    for case in options["valid"]:
        NativeMenu.model_validate(_menu_of(case))
    for case in options["invalid"]:
        if case["name"] in _MENU_SECTION_PROBLEMS:
            with pytest.raises(ValidationError):
                NativeMenu.model_validate(_menu_of(case))


def test_menu_round_trips() -> None:
    raw = _menu_of(_load("menu.json")["options"]["valid"][1])
    menu = NativeMenu.model_validate(raw)
    assert menu.model_dump(mode="json", by_alias=True, exclude_unset=True) == raw


def test_lazy_answers_are_checked_against_what_the_menu_has() -> None:
    menu = _load("menu.json")
    base = NativeMenu.model_validate(_menu_of(menu["options"]["valid"][1]))
    ids: set[str] = set()
    count = 0

    def visit(sections: list[MenuSection]) -> None:
        nonlocal count
        for section in sections:
            for item in section.items:
                ids.add(item.id)
                count += 1
                if isinstance(item.children, list):
                    visit(item.children)

    visit(base.sections)
    sections = TypeAdapter(list[MenuSection])
    for case in menu["menuItems"]["valid"]:
        parsed = sections.validate_python(case["value"])
        check_menu_sections(parsed, depth=1, taken_ids=ids, taken_items=count)
    for case in menu["menuItems"]["invalid"]:
        with pytest.raises(ValueError):  # ValidationError is a ValueError
            parsed = sections.validate_python(case["value"])
            check_menu_sections(parsed, depth=1, taken_ids=ids, taken_items=count)


def test_search_answers() -> None:
    answers = _load("live-surface.json")["searchAnswer"]
    for case in answers["valid"]:
        SurfaceSearchAnswer.model_validate(_expand(case["value"]))
    for case in answers["invalid"]:
        with pytest.raises(ValidationError):
            SurfaceSearchAnswer.model_validate(_expand(case["value"]))
        sent = SurfaceSearchAnswer.model_validate(_expand(case["sent"]))
        assert len(sent.options) <= 50


def test_new_field_options() -> None:
    fields = _load("live-surface.json")["fields"]
    for case in fields["valid"]:
        field = ActionField.model_validate(case["value"])
        assert field.model_dump(mode="json", by_alias=True, exclude_unset=True) == case["value"]
    for case in fields["invalid"]:
        with pytest.raises(ValidationError):
            ActionField.model_validate(case["value"])
