"""Shared sample payloads from `contract-fixtures/` (see the README there).

Every file must validate against the Pydantic models and serialize back
unchanged — a field that only the TypeScript side knows about would be
silently dropped by Pydantic, and that shows up here.
"""

import json
from pathlib import Path
from typing import Any

from bmsdna.app_native import ApprovalFeed, LiveActivityState, NativeContent, NativeForm, Widget
from pydantic import TypeAdapter

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
