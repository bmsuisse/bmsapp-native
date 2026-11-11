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
    ApprovalFeed,
    LiveActivityState,
    NativeContent,
    NativeDocument,
    NativeDocumentContext,
    NativeForm,
    Widget,
)
from bmsdna.app_native.documents import DocumentKind
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


def _expand(value: Any) -> Any:
    """`"@N"` in `text` stands for N characters (see the README)."""
    if isinstance(value, str) and value.startswith("@") and value[1:].isdigit():
        return "x" * int(value[1:])
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


@pytest.mark.parametrize("name", _FILES)
def test_2026_11_fixtures_have_the_expected_shape(name: str) -> None:
    raw = _load(name)
    assert isinstance(raw["description"], str)
    sections = [value for key, value in raw.items() if key != "description"]
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
