"""The keyboard toolbar, key commands and the document viewer (2026-11b) with the
built npm package in a real browser, and everything of 2026-11b in apps without it. The
keyboard, the keys and the PDF viewer are played by the page's fake bridge
(`window.__kb`, `window.__keys`, `window.__viewer`); the real iOS app does not take part.
"""

import pytest
from helpers import open_page
from playwright.sync_api import Page


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


# --- keyboard toolbar ------------------------------------------------------------------------------


def test_the_toolbar_shows_with_the_keyboard_and_keeps_the_focus(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => { window.__taps = []; window.native.on('keyboardToolbarTap', (e) => window.__taps.push(e.id)) }"
    )
    res = page.evaluate(
        """() => window.native.setKeyboardToolbar({
          items: [{ id: 'prev', icon: 'chevron.up' }, { id: 'add', label: 'Add line', style: 'prominent' }],
          done: true,
        })"""
    )
    assert res == {"ok": True}
    assert page.evaluate("() => window.__kb.visible()") is False  # no field has focus

    page.evaluate("() => window.__kb.focusField()")
    assert page.evaluate("() => window.__kb.visible()") is True
    assert page.evaluate("() => window.__kb.tap('add')") is True
    assert page.evaluate("() => window.__kb.focus") is True  # a tap keeps the focus
    assert page.evaluate("() => window.__taps") == ["add"]
    assert page.evaluate("() => window.__kb.tapDone()") is True
    assert page.evaluate("() => window.__kb.focus") is False


def test_the_toolbar_is_not_shown_with_a_hardware_keyboard_or_after_removal(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.native.setKeyboardToolbar({ items: [{ id: 'a', label: 'A' }] })")
    page.evaluate("() => { window.__kb.focusField(); window.__kb.setHardware(true) }")
    assert page.evaluate("() => window.__kb.visible()") is False
    page.evaluate("() => window.__kb.setHardware(false)")
    assert page.evaluate("() => window.__kb.visible()") is True
    page.evaluate("() => window.native.setKeyboardToolbar({ items: [] })")
    assert page.evaluate("() => window.__kb.visible()") is False


# --- key commands -------------------------------------------------------------------------------------


def test_registered_keys_are_consumed_and_others_reach_the_page(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => { window.__cmds = []; window.native.on('keyCommand', (e) => window.__cmds.push(e.id)) }"
    )
    res = page.evaluate(
        """() => window.native.setKeyCommands({ commands: [
          { id: 'search', input: 'k', modifiers: ['command'], title: 'Search', group: 'Offers' },
          { id: 'next', input: 'down', modifiers: [], title: 'Next line', group: 'Navigate' },
        ] })"""
    )
    assert res == {"ok": True}

    def press(input: str, *modifiers: str) -> str:
        return page.evaluate(
            "([input, modifiers]) => window.__keys.press({ input, modifiers })",
            [input, list(modifiers)],
        )

    assert press("k", "command") == "consumed"
    assert press("k") == "dom"  # without the modifier: not registered
    assert press("f", "command") == "dom"  # Cmd+F is not registered: C8 behaviour
    assert press("down") == "consumed"
    page.evaluate("() => { window.__keys.textFocus = true }")
    assert press("down") == "dom"  # a command without modifiers waits for no text field
    assert press("k", "command") == "consumed"
    assert page.evaluate("() => window.__cmds") == ["search", "next", "search"]


def test_key_commands_need_a_hardware_keyboard_and_end_with_an_empty_list(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => window.native.setKeyCommands({ commands: [{ id: 'a', input: 'k', modifiers: ['command'], title: 'A' }] })"
    )
    page.evaluate("() => { window.__keys.hardware = false }")
    assert (
        page.evaluate("() => window.__keys.press({ input: 'k', modifiers: ['command'] })") == "dom"
    )
    page.evaluate("() => { window.__keys.hardware = true }")
    page.evaluate("() => window.native.setKeyCommands({ commands: [] })")
    assert (
        page.evaluate("() => window.__keys.press({ input: 'k', modifiers: ['command'] })") == "dom"
    )


# --- document viewer ------------------------------------------------------------------------------------

_HIGHLIGHTS = """[
  { id: 'l1', page: 1, x: 0.1, y: 0.4, w: 0.8, h: 0.05, style: 'primary', label: 'Pallet' },
  { id: 'l2', page: 3, x: 0.1, y: 0.2, w: 0.8, h: 0.05, style: 'secondary' },
]"""


def _open_viewer(page: Page) -> None:
    page.evaluate(
        f"""() => {{
          window.__ev = []
          window.native.on('documentTap', (e) => window.__ev.push(['tap', e]))
          window.native.on('documentPage', (e) => window.__ev.push(['page', e]))
          window.__doc = window.native.showDocument({{
            id: 'offer-pdf', url: '/files/offer.pdf', title: 'Offer 4711', highlights: {_HIGHLIGHTS}, selected: 'l1',
          }})
        }}"""
    )
    page.wait_for_function("() => window.__viewer.state !== null")


def test_the_viewer_shows_highlights_and_reports_taps_and_pages(page: Page) -> None:
    open_page(page)
    _open_viewer(page)
    state = page.evaluate("() => window.__viewer.state")
    origin = page.evaluate("() => location.origin")
    assert state["url"] == f"{origin}/files/offer.pdf"
    assert (state["selected"], len(state["highlights"])) == ("l1", 2)

    assert page.evaluate("() => window.__viewer.tap('l1', 1, 0.4, 0.42)") is True
    assert page.evaluate("() => window.__viewer.tap(null, 2, 0.9, 0.1)") is True
    assert page.evaluate("() => window.__viewer.scrollToPage(3)") is True
    assert page.evaluate("() => window.__ev") == [
        ["tap", {"id": "offer-pdf", "highlightId": "l1", "page": 1, "x": 0.4, "y": 0.42}],
        ["tap", {"id": "offer-pdf", "highlightId": None, "page": 2, "x": 0.9, "y": 0.1}],
        ["page", {"id": "offer-pdf", "page": 3}],
    ]
    page.evaluate("() => window.__viewer.close()")
    assert page.evaluate("() => window.__doc") == {"ok": True}
    assert page.evaluate("() => window.__viewer.state") is None


def test_update_document_changes_the_open_viewer(page: Page) -> None:
    open_page(page)
    _open_viewer(page)
    res = page.evaluate(
        """() => window.native.updateDocument({
          id: 'offer-pdf', selected: 'l2',
          highlights: [{ id: 'l2', page: 3, x: 0.1, y: 0.2, w: 0.8, h: 0.05, style: 'primary' }],
        })"""
    )
    assert res == {"ok": True}
    state = page.evaluate("() => window.__viewer.state")
    assert (state["selected"], state["page"], len(state["highlights"])) == (
        "l2",
        3,
        1,
    )  # scrolled to it
    assert (
        page.evaluate("() => window.native.updateDocument({ id: 'other', page: 2 })")["error"]
        == "notFound"
    )
    page.evaluate("() => window.__viewer.close()")
    assert (
        page.evaluate("() => window.native.updateDocument({ id: 'offer-pdf', page: 2 })")["error"]
        == "notFound"
    )


def test_a_missing_file_fails_with_its_status(page: Page) -> None:
    open_page(page)
    res = page.evaluate("() => window.native.showDocument({ url: '/files/missing.pdf' })")
    assert res == {"ok": False, "error": "failed", "status": 404}
    assert page.evaluate("() => window.__viewer.state") is None


def test_a_foreign_url_never_reaches_the_app_and_the_app_refuses_it_too(page: Page) -> None:
    open_page(page)
    url = "https://other.example.com/a.pdf"
    assert (
        page.evaluate(f"() => window.native.showDocument({{ url: '{url}' }})")["error"] == "invalid"
    )
    assert _log(page) == []
    assert (
        page.evaluate(f"() => window.native.call('showDocument', {{ url: '{url}' }})")["error"]
        == "invalid"
    )


# --- everything of 2026-11b without the app or in an app without it ---------------------------------------------

_CALLS = {
    "showMenu": "{ anchor: { x: 0, y: 0, width: 1, height: 1 }, sections: [{ items: [{ id: 'a', label: 'A' }] }] }",
    "showAlert": "{ title: 'T', actions: [{ id: 'a', label: 'A' }] }",
    "updateSurface": "{ id: 'f', title: 'x' }",
    "setKeyboardToolbar": "{ items: [] }",
    "showDocument": "{ url: '/files/offer.pdf' }",
    "updateDocument": "{ id: 'x', page: 2 }",
    "showPicker": "{ kind: 'date' }",
    "setKeyCommands": "{ commands: [] }",
}


@pytest.mark.parametrize("path", ["/?oldApp", "/?browser", "/?features="])
def test_every_new_call_is_unavailable_without_asking_the_app(page: Page, path: str) -> None:
    open_page(page, path)
    results = page.evaluate(
        "async () => ({ "
        + ", ".join(f"{k}: await window.native.{k}({v})" for k, v in _CALLS.items())
        + " })"
    )
    assert results == {name: {"ok": False, "error": "unavailable"} for name in _CALLS}
    assert _log(page) == []


@pytest.mark.parametrize("action", sorted(_CALLS))
def test_an_old_app_answers_unknown_action(page: Page, action: str) -> None:
    open_page(page, "/?oldApp")
    raw = page.evaluate("(action) => window.native.call(action, {})", action)
    assert raw == {"ok": False, "error": "unknownAction"}


def test_hasfeature_covers_every_flag_of_the_contract(page: Page) -> None:
    open_page(page)
    flags = [
        "menus",
        "titleMenu",
        "alerts",
        "toastActions",
        "liveSurfaces",
        "pageSearch",
        "navSearch",
        "keyboardToolbar",
        "segments",
        "sidebar",
        "documentViewer",
        "undoGestures",
        "pickers",
        "keyCommands",
    ]
    assert (
        page.evaluate("(flags) => flags.map((f) => window.native.hasFeature(f))", flags)
        == [True] * 14
    )
    open_page(page, "/?oldApp")
    assert (
        page.evaluate("(flags) => flags.map((f) => window.native.hasFeature(f))", flags)
        == [False] * 14
    )
