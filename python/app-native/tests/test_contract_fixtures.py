"""Shared sample payloads from `contract-fixtures/` (see the README there).

Every file must validate against the Pydantic models and serialize back
unchanged — a field that only the TypeScript side knows about would be
silently dropped by Pydantic, and that shows up here.
"""

import json
from pathlib import Path
from typing import Any

from bmsdna.app_native import LiveActivityState, Widget
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


def test_live_activity_state_round_trip() -> None:
    raw = _load("live-activity-state.json")
    state = LiveActivityState.model_validate(raw)
    assert state.model_dump(mode="json", by_alias=True, exclude_unset=True) == raw
