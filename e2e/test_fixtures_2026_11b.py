"""The fixtures of the 2026-11b contract through the built package and the harness.

`valid` cases reach the app as they are; `invalid` ones are refused by the package
(`invalid`, the app is not asked) AND by the harness, which checks the same payload in
Python (`rules.py`) independently of the package. Parts of `setChrome` have no answer:
the package warns in a development build, and the harness refuses a direct
`call('setChrome')` with `invalid`.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from helpers import open_page
from playwright.sync_api import Page

FIXTURES = Path(__file__).resolve().parent.parent / "contract-fixtures"

#: file -> (section, action, JS that calls the package with `o`)
_OPTIONS = [
    ("menu.json", "options", "showMenu", "window.native.showMenu(o)"),
    ("alert.json", "options", "showAlert", "window.native.showAlert(o)"),
    (
        "toast-action.json",
        "options",
        "toast",
        "(({ message, ...rest }) => window.native.toast(message, rest))(o)",
    ),
    ("live-surface.json", "options", "updateSurface", "window.native.updateSurface(o)"),
    (
        "keyboard-toolbar.json",
        "options",
        "setKeyboardToolbar",
        "window.native.setKeyboardToolbar(o)",
    ),
    ("document-viewer.json", "options", "showDocument", "window.native.showDocument(o)"),
    ("document-viewer.json", "update", "updateDocument", "window.native.updateDocument(o)"),
    ("picker.json", "options", "showPicker", "window.native.showPicker(o)"),
    ("key-commands.json", "options", "setKeyCommands", "window.native.setKeyCommands(o)"),
]

_CHROME = [
    ("menu.json", "chrome"),
    ("nav-search.json", "chrome"),
    ("segments.json", "chrome"),
    ("sidebar.json", "chrome"),
    ("undo.json", "chrome"),
]


def _fill(template: Any, k: int) -> Any:
    if isinstance(template, str):
        return template.replace("{k}", str(k))
    if isinstance(template, list):
        return [_fill(v, k) for v in template]
    if isinstance(template, dict):
        return {key: _fill(v, k) for key, v in template.items()}
    return template


def _expand(value: Any, origin: str, key: str = "") -> Any:
    if isinstance(value, str):
        if value.startswith("@") and value[1:].isdigit():
            n = int(value[1:])
            return ["a"] * n if key == "contextualStrings" else "x" * n
        return value.replace("{origin}", origin)
    if isinstance(value, list):
        return [_expand(v, origin) for v in value]
    if isinstance(value, dict):
        if "@repeat" in value:
            return [_fill(_expand(value["of"], origin), k) for k in range(value["@repeat"])]
        return {k: _expand(v, origin, k) for k, v in value.items()}
    return value


def _cases(table: list[tuple[str, ...]]) -> list[Any]:
    cases = []
    for entry in table:
        file, section = entry[0], entry[1]
        data = json.loads((FIXTURES / file).read_text())[section]
        for kind in ("valid", "invalid"):
            for case in data.get(kind, []):
                cases.append(
                    pytest.param(
                        *entry, {**case, "kind": kind}, id=f"{file}:{section}:{case['name']}"
                    )
                )
    return cases


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


@pytest.mark.parametrize(("file", "section", "action", "js", "case"), _cases(_OPTIONS))
def test_options_reach_the_app_or_are_refused_by_both(
    page: Page, file: str, section: str, action: str, js: str, case: dict
) -> None:
    open_page(page)
    origin = page.evaluate("() => location.origin")
    value = _expand(case["value"], origin)
    call = f"(o) => {js}"

    if case["kind"] == "valid":
        sent = _expand(case.get("sent", case["value"]), origin)
        page.evaluate(call, value)
        expected = {**sent, "action": action}
        if action == "toast" and "action" in sent:
            expected["@action"] = sent[
                "action"
            ]  # the harness keeps the button apart, see page/index.html
        assert _log(page) == [expected]
        return

    res = page.evaluate(call, value)
    assert res["error"] == case["error"] == "invalid"
    assert _log(page) == []
    # The harness refuses the same payload with the rules written in Python.
    raw = page.evaluate(f"(o) => window.native.call('{action}', o)", value)
    assert raw["error"] == "invalid"


@pytest.mark.parametrize(("file", "section", "case"), _cases(_CHROME))
def test_parts_of_setchrome_warn_in_the_package_and_are_refused_by_the_harness(
    page: Page, file: str, section: str, case: dict
) -> None:
    open_page(page)
    origin = page.evaluate("() => location.origin")
    value = _expand(case["value"], origin)
    warnings: list[str] = []
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)

    page.evaluate("(chrome) => window.native.setChrome(chrome)", value)
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length > 0)"
    )
    raw = page.evaluate("(chrome) => window.native.call('setChrome', chrome)", value)

    if case["kind"] == "valid":
        assert warnings == []
        assert raw == {"ok": True}
    else:
        assert case["error"] == "invalid"
        assert any("setChrome" in w for w in warnings), warnings
        assert raw["error"] == "invalid"
