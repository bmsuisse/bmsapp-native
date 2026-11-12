"""Final alignment 2026-11c on the Python side: D6 (upload result), D14 (live fields,
unique ids), D15 (empty menus), D21 (the size limit)."""

from typing import Any

import pytest
from bmsdna.app_native import (
    MAX_NATIVE_DOCUMENT_BYTES,
    NOT_LIVE_FIELD_TYPES,
    ActionField,
    MenuSection,
    NativeContent,
    NativeDocument,
    NativeMenu,
    check_menu_sections,
)
from pydantic import TypeAdapter, ValidationError

UPLOAD_ID = "8c2f1a4e-5b0a-4f3e-9d57-2b6f1c9e7a10"


def _document(**extra: Any) -> dict[str, Any]:
    return {"name": "a.pdf", "mime": "application/pdf", "size": 1, "uploadId": UPLOAD_ID, **extra}


# --- D6 -----------------------------------------------------------------------------------


def test_an_upload_with_http_400_or_more_is_failed_and_keeps_its_upload() -> None:
    failed = NativeDocument.model_validate(
        _document(upload={"status": 503, "body": {"detail": "Try again"}}, error="failed")
    )
    assert failed.upload is not None and failed.upload.status == 503
    assert failed.upload.body == {"detail": "Try again"}
    with pytest.raises(ValidationError, match="HTTP 400 or more"):
        NativeDocument.model_validate(_document(upload={"status": 503, "body": None}))
    with pytest.raises(ValidationError):
        NativeDocument.model_validate(
            _document(upload={"status": 404, "body": "x"}, error="tooLarge")
        )


def test_a_network_error_has_no_upload() -> None:
    doc = NativeDocument.model_validate({"name": "a.pdf", "uploadId": UPLOAD_ID, "error": "failed"})
    assert doc.upload is None


@pytest.mark.parametrize(
    "body",
    [{"ok": True, "id": "doc-1"}, "<html>Bad Gateway</html>", "", ["a"], 7, True, None],
)
def test_the_body_is_the_parsed_json_or_the_raw_text(body: Any) -> None:
    doc = NativeDocument.model_validate(_document(upload={"status": 200, "body": body}))
    assert doc.upload is not None and doc.upload.body == body
    dumped = doc.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert dumped["upload"] == {"status": 200, "body": body}


def test_the_upload_needs_a_body_key_and_a_status_of_a_real_response() -> None:
    with pytest.raises(ValidationError):
        NativeDocument.model_validate(_document(upload={"status": 200}))
    with pytest.raises(ValidationError):
        NativeDocument.model_validate(_document(upload={"status": 99, "body": None}))


# --- D21 ----------------------------------------------------------------------------------


def test_the_limit_per_document_is_25_000_000_bytes() -> None:
    assert MAX_NATIVE_DOCUMENT_BYTES == 25_000_000
    NativeDocument.model_validate(_document(size=25_000_000))
    with pytest.raises(ValidationError):
        NativeDocument.model_validate(_document(size=25_000_001))


# --- D14 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(NOT_LIVE_FIELD_TYPES))
def test_only_scalar_fields_can_be_live(kind: str) -> None:
    extra = {"fields": [{"id": "a", "type": "text"}]} if kind == "repeat" else {}
    with pytest.raises(ValidationError, match="cannot be `live`"):
        ActionField.model_validate({"id": "f", "type": kind, "live": True, **extra})
    # `live: false` is not a claim and stays fine.
    ActionField.model_validate({"id": "f", "type": kind, "live": False, **extra})


@pytest.mark.parametrize(
    "kind", ["text", "number", "select", "toggle", "date", "search", "barcode", "stepper", "email"]
)
def test_scalar_fields_can_be_live(kind: str) -> None:
    assert ActionField.model_validate({"id": "f", "type": kind, "live": True}).live is True


def test_source_page_is_for_search_fields_only() -> None:
    ActionField.model_validate({"id": "f", "type": "search", "source": "page"})
    for kind in ("text", "photo"):
        with pytest.raises(ValidationError):
            ActionField.model_validate({"id": "f", "type": kind, "source": "page"})


def _content(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"blocks": list(blocks)}


def test_ids_are_unique_per_surface() -> None:
    NativeContent.model_validate(
        _content(
            {"type": "divider", "id": "x"},
            {"type": "heading", "id": "y", "text": "H"},
            {"type": "list", "items": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]},
        )
    )
    with pytest.raises(ValidationError, match="block `id` is used twice"):
        NativeContent.model_validate(
            _content({"type": "divider", "id": "x"}, {"type": "divider", "id": "x"})
        )
    with pytest.raises(ValidationError, match="list item `id` is used twice"):
        NativeContent.model_validate(
            _content(
                {"type": "list", "items": [{"id": "a", "title": "A"}, {"id": "a", "title": "B"}]}
            )
        )
    with pytest.raises(ValidationError, match="field `id` is used twice"):
        NativeContent.model_validate(
            _content(
                {"type": "fields", "fields": [{"id": "a", "type": "text"}]},
                {"type": "fields", "fields": [{"id": "a", "type": "text"}]},
            )
        )


def test_ids_of_different_kinds_may_coincide_and_nested_blocks_count() -> None:
    NativeContent.model_validate(
        _content(
            {"type": "divider", "id": "a"},
            {"type": "fields", "fields": [{"id": "a", "type": "text"}]},
        )
    )
    with pytest.raises(ValidationError):
        NativeContent.model_validate(
            _content(
                {"type": "divider", "id": "x"},
                {"type": "card", "blocks": [{"type": "divider", "id": "x"}]},
            )
        )


# --- D15 ----------------------------------------------------------------------------------


def test_an_empty_menu_section_or_children_list_is_invalid() -> None:
    item = {"id": "a", "label": "A"}
    NativeMenu.model_validate({"sections": [{"items": [item]}]})
    for bad in (
        {"sections": []},
        {"sections": [{"items": []}]},
        {"sections": [{"items": [{**item, "children": []}]}]},
    ):
        with pytest.raises(ValidationError):
            NativeMenu.model_validate(bad)


def test_the_answer_for_a_lazy_item_cannot_be_empty() -> None:
    sections = TypeAdapter(list[MenuSection]).validate_python(
        [{"items": [{"id": "x", "label": "X"}]}]
    )
    assert check_menu_sections(sections, depth=1, taken_ids={"a"}, taken_items=2) == 1
    with pytest.raises(ValueError, match="at least one section"):
        check_menu_sections([], depth=1)


def test_lazy_children_and_the_failed_label_are_part_of_the_item() -> None:
    menu = NativeMenu.model_validate(
        {
            "sections": [
                {"items": [{"id": "a", "label": "A", "children": "lazy", "lazyFailedLabel": "–"}]}
            ]
        }
    )
    assert menu.sections[0].items[0].children == "lazy"
