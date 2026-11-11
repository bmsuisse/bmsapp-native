"""Final alignment 2026-11c (decisions D1-D22): what the built npm package, the fake app
and the Python harness do about each of them. The real iOS app does not take part.
"""

import base64
from typing import Any

from helpers import open_page
from playwright.sync_api import Page

ANCHOR = {"x": 24, "y": 120, "width": 44, "height": 44}


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def _uploads(page: Page) -> list[dict]:
    return page.request.get("/backend-log").json()["uploads"]


def _wait_log(page: Page) -> None:
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length > 0)"
    )


# --- D4 capabilities never imply each other -------------------------------------------------


def test_consume_needs_its_own_capability(page: Page) -> None:
    open_page(page, "/?capabilities=customChrome,camera,microphone")
    res = page.evaluate("() => window.native.consumeReceivedDocuments()")
    assert (res["ok"], res["error"]) == (False, "capability")
    raw = page.evaluate("() => window.native.call('consumeReceivedDocuments', {})")
    assert raw["error"] == "capability"


def test_custom_chrome_does_not_imply_the_surface_capabilities(page: Page) -> None:
    open_page(page, "/?capabilities=customChrome")
    assert (
        page.evaluate("() => window.native.updateSurface({ id: 'f', title: 'x' })")["error"]
        == "capability"
    )
    open_page(page, "/?capabilities=nativeForms,nativeContent")
    res = page.evaluate(
        "(a) => window.native.showMenu({ anchor: a, sections: [{ items: [{ id: 'a', label: 'A' }] }] })",
        ANCHOR,
    )
    assert res["error"] == "capability"


# --- D5 JPEG ---------------------------------------------------------------------------------


def test_photos_and_heic_arrive_as_jpeg(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => window.__docs.script.push({ documents: [
          { name: 'IMG_0042.heic', mime: 'image/heic', photo: true, content: 'x' },
        ] })"""
    )
    picked = page.evaluate("() => window.native.pickFiles({ sources: ['photos'] })")
    assert [(d["name"], d["mime"]) for d in picked["documents"]] == [("IMG_0042.jpg", "image/jpeg")]

    page.evaluate("() => window.native.onDocumentsReceived(() => {})")
    shared = page.evaluate(
        "() => window.__share([{ name: 'Photo.HEIC', mime: 'image/heic' }, { name: 'Offer.pdf' }])"
    )
    assert shared == "delivered"
    names = [(u["filename"], u["content_type"]) for u in _uploads(page)]
    assert names == [("Photo.jpg", "image/jpeg"), ("Offer.pdf", "application/pdf")]


# --- D6 the upload result ----------------------------------------------------------------------


def _scan_one(page: Page, spec: str) -> dict[str, Any]:
    page.evaluate(f"() => window.__docs.script.push({{ documents: [{spec}] }})")
    return page.evaluate("() => window.native.scanDocument()")["documents"][0]


def test_the_body_is_the_parsed_json(page: Page) -> None:
    open_page(page)
    doc = _scan_one(page, "{ name: 'a.pdf' }")
    assert doc["upload"] == {"status": 200, "body": {"ok": True, "id": "doc-1"}}


def test_the_body_is_the_raw_text_when_it_is_not_json(page: Page) -> None:
    open_page(page)
    doc = _scan_one(page, "{ name: 'a.pdf', endpoint: '/test/html-upload' }")
    assert doc["upload"] == {"status": 200, "body": "<html>Bad Gateway</html>"}
    assert "error" not in doc


def test_http_400_or_more_after_the_retry_is_failed_with_the_upload(page: Page) -> None:
    open_page(page)
    page.request.post("/test/document-backend", data={"failures": {"down.pdf": 2}})
    doc = _scan_one(page, "{ name: 'down.pdf' }")
    assert doc["error"] == "failed"
    assert doc["upload"] == {"status": 503, "body": {"detail": "Try again"}}


def test_a_network_error_is_failed_without_an_upload_key(page: Page) -> None:
    open_page(page)
    doc = _scan_one(page, "{ name: 'a.pdf', offline: true }")
    assert doc["error"] == "failed"
    assert "upload" not in doc
    assert _uploads(page) == []


# --- D10 dictate -------------------------------------------------------------------------------


def test_dictate_wants_a_whole_number_of_seconds(page: Page) -> None:
    open_page(page)
    res = page.evaluate("() => window.native.dictate({ maxSeconds: 30.5 })")
    assert res["error"] == "invalid"
    assert _log(page) == []
    raw = page.evaluate("() => window.native.call('dictate', { maxSeconds: 30.5 })")
    assert raw["error"] == "invalid"  # the harness checks the same rule in Python
    page.evaluate("() => window.__voice.script.push({ text: 'ok' })")
    assert page.evaluate("() => window.native.dictate({ maxSeconds: 30 })")["ok"] is True


def test_dictate_with_an_unsupported_locale_is_unavailable(page: Page) -> None:
    open_page(page)
    res = page.evaluate("() => window.native.dictate({ locale: 'xx-XX' })")
    assert res["ok"] is False and res["error"] == "unavailable"


# --- D11 back ----------------------------------------------------------------------------------


def test_a_late_or_unsolicited_back_result_is_ignored_and_answered_ok(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.native.call('backResult', { handled: true })") == {
        "ok": True
    }
    page.evaluate(
        "() => { window.native.onBackRequested(() => new Promise((r) => setTimeout(() => r(true), 2000))) }"
    )
    page.wait_for_function("() => window.__back.enabled")
    assert page.evaluate("() => window.__back.press('button')") == "default"
    # The page answers once more after the app has moved on.
    assert page.evaluate("() => window.native.call('backResult', { handled: true })") == {
        "ok": True
    }


# --- D12 relative URLs ---------------------------------------------------------------------------


def test_the_app_resolves_relative_urls_against_the_sending_page(page: Page) -> None:
    open_page(page)
    assert page.evaluate(
        "() => window.native.call('previewFile', { url: '/files/offer.pdf' })"
    ) == {"ok": True}
    assert page.evaluate("() => window.native.call('previewFile', { url: 'files/offer.pdf' })") == {
        "ok": True
    }
    page.evaluate(
        "() => { window.__doc = window.native.call('showDocument', { url: 'files/offer.pdf' }) }"
    )
    page.wait_for_function("() => window.__viewer.state !== null")
    page.evaluate("() => window.__viewer.close()")
    assert page.evaluate("() => window.__doc") == {"ok": True}


# --- D14 live surfaces ----------------------------------------------------------------------------


def test_update_surface_merges_values_and_replaces_fields(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__surfaces.script.push({ hold: true })")
    page.evaluate(
        """() => { window.__form = window.native.showForm({
          id: 'f', values: { qty: 1, note: 'x' }, fields: [{ id: 'qty', type: 'number' }, { id: 'note', type: 'text' }],
        }) }"""
    )
    page.wait_for_function("() => window.__surfaces.open !== null")
    page.evaluate(
        "() => window.native.updateSurface({ id: 'f', values: { qty: 5 }, fields: [{ id: 'qty', type: 'number' }] })"
    )
    state = page.evaluate("() => window.__surfaces.def")
    assert state["values"] == {"qty": 5, "note": "x"}  # merged
    assert [f["id"] for f in state["fields"]] == ["qty"]  # replaced
    page.evaluate("() => window.native.closeSurface()")


def test_a_search_without_an_answer_gives_an_empty_result_and_a_retry(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__surfaces.searchTimeout = 200 }")
    page.evaluate("() => window.__surfaces.script.push({ hold: true })")
    page.evaluate(
        """() => { window.__form = window.native.showForm(
          { id: 'f', fields: [{ id: 'c', type: 'search', source: 'page', minQueryLength: 1 }] },
          { onSearch: () => new Promise(() => {}) }
        ) }"""
    )
    page.wait_for_function("() => window.__surfaces.open !== null")
    page.evaluate("() => window.__surfaces.search('c', 'q')")
    page.wait_for_function("() => window.__surfaces.found.c.timedOut === true")
    found = page.evaluate("() => window.__surfaces.found.c")
    assert found["options"] == [] and found["retry"] is True
    page.evaluate("() => window.native.closeSurface()")


def test_live_is_refused_for_files_rows_and_info_by_the_app_too(page: Page) -> None:
    open_page(page)
    for kind in ("photo", "scan", "signature", "info"):
        raw = page.evaluate(
            "(kind) => window.native.call('showForm', { fields: [{ id: 'f', type: kind, live: true }] })",
            kind,
        )
        assert raw["error"] == "invalid", kind
    # The package never sends it: it leaves the claim out.
    page.evaluate("() => window.__surfaces.script.push({ dismiss: true })")
    page.evaluate(
        "() => window.native.showForm({ fields: [{ id: 'p', type: 'photo', live: true }] })"
    )
    sent = [m for m in _log(page) if m["action"] == "showForm"][-1]
    assert "live" not in sent["fields"][0]


def test_ids_are_unique_per_surface_for_the_app_and_the_package(page: Page) -> None:
    open_page(page)
    blocks = "[{ type: 'divider', id: 'x' }, { type: 'divider', id: 'x' }]"
    assert (
        page.evaluate(f"() => window.native.updateSurface({{ id: 's', blocks: {blocks} }})")[
            "error"
        ]
        == "invalid"
    )
    raw = page.evaluate(
        f"() => window.native.call('updateSurface', {{ id: 's', blocks: {blocks} }})"
    )
    assert raw["error"] == "invalid"


# --- D15 menus ---------------------------------------------------------------------------------------


def test_the_package_does_not_send_lazy_items_in_the_bar_menus(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.native.setChrome({
            title: { text: 'Offer', menu: [{ items: [{ id: 'l', label: 'Lazy', children: 'lazy' }] }] },
            actionButtons: [{ id: 'more', icon: 'ellipsis', menu: [{ items: [{ id: 'l', label: 'Lazy', children: 'lazy' }] }] }],
          })
        }"""
    )
    _wait_log(page)
    sent = _log(page)[0]
    assert sent["title"] == {"text": "Offer"}
    assert sent["actionButtons"] == [{"id": "more", "icon": "ellipsis"}]
    assert page.evaluate("() => window.__chrome.tapActionButton('more')") == "tap"


def test_the_app_refuses_lazy_in_the_bar_and_shows_a_disabled_row_if_it_gets_one(
    page: Page,
) -> None:
    open_page(page)
    menu = "[{ items: [{ id: 'l', label: 'Lazy', children: 'lazy' }] }]"
    raw = page.evaluate(
        f"() => window.native.call('setChrome', {{ title: {{ text: 'T', menu: {menu} }} }})"
    )
    assert raw["error"] == "invalid"
    # A fire-and-forget message has no answer: the app takes the title and draws a disabled row.
    page.evaluate(
        f"() => window.BMSNative.postMessage({{ action: 'setChrome', title: {{ text: 'T', menu: {menu} }} }})"
    )
    page.wait_for_function("() => window.__chrome.navTitle() !== null")
    assert page.evaluate("() => window.__chrome.selectTitleMenu('l')") is False


def test_empty_menus_are_invalid_for_the_package_and_the_app(page: Page) -> None:
    open_page(page)
    for sections in ("[]", "[{ items: [] }]"):
        res = page.evaluate(
            f"(a) => window.native.showMenu({{ anchor: a, sections: {sections} }})", ANCHOR
        )
        assert res["error"] == "invalid"
        raw = page.evaluate(
            f"(a) => window.native.call('showMenu', {{ anchor: a, sections: {sections} }})", ANCHOR
        )
        assert raw["error"] == "invalid"
    assert [m["action"] for m in _log(page)] == ["showMenu", "showMenu"]  # only the raw calls


def test_a_menu_item_with_children_is_never_a_result(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__menu.script.push({ select: 'export' })")
    res = page.evaluate(
        """(a) => window.native.showMenu({ anchor: a, sections: [{ items: [
          { id: 'export', label: 'Export', children: [{ items: [{ id: 'pdf', label: 'PDF' }] }] },
        ] }] })""",
        ANCHOR,
    )
    assert res == {"ok": False, "error": "cancelled"}


# --- D16 alerts --------------------------------------------------------------------------------------------


def test_duplicate_action_ids_are_invalid_and_the_text_is_always_there(page: Page) -> None:
    open_page(page)
    dup = "{ title: 'T', actions: [{ id: 'a', label: 'A' }, { id: 'a', label: 'B' }] }"
    assert page.evaluate(f"() => window.native.showAlert({dup})")["error"] == "invalid"
    assert page.evaluate(f"() => window.native.call('showAlert', {dup})")["error"] == "invalid"
    page.evaluate("() => window.__alert.script.push({ tap: 'ok', text: '' })")
    res = page.evaluate(
        "() => window.native.showAlert({ title: 'T', actions: [{ id: 'ok', label: 'OK' }], textField: {} })"
    )
    assert res == {"ok": True, "id": "ok", "text": ""}


# --- D17 key commands ------------------------------------------------------------------------------------------


def test_system_collisions_are_ignored_the_first_identical_wins_and_letters_are_case_insensitive(
    page: Page,
) -> None:
    open_page(page)
    page.evaluate(
        "() => { window.__ids = []; window.native.on('keyCommand', (e) => window.__ids.push(e.id)) }"
    )
    page.evaluate(
        """() => window.native.setKeyCommands({ commands: [
          { id: 'close', input: 'w', modifiers: ['command'], title: 'Close' },
          { id: 'first', input: 'K', modifiers: ['command'], title: 'First' },
          { id: 'second', input: 'k', modifiers: ['command'], title: 'Second' },
        ] })"""
    )
    press = "(m) => window.__keys.press({ input: m[0], modifiers: m[1] })"
    assert page.evaluate(press, ["w", ["command"]]) == "dom"  # Cmd+W stays the app's
    assert page.evaluate(press, ["k", ["command"]]) == "consumed"
    assert page.evaluate(press, ["K", ["command"]]) == "consumed"
    assert page.evaluate("() => window.__ids") == ["first", "first"]


# --- D19 the viewer ------------------------------------------------------------------------------------------------

_DOC = """{
  id: 'pdf', url: '/files/offer.pdf', page: 1, selected: 'b',
  highlights: [
    { id: 'a', page: 1, x: 0, y: 0, w: 1, h: 1, style: 'secondary' },
    { id: 'b', page: 3, x: 0.1, y: 0.1, w: 0.5, h: 0.5, style: 'primary' },
    { id: 'c', page: 3, x: 0.2, y: 0.2, w: 0.5, h: 0.5, style: 'primary' },
  ],
}"""


def test_a_second_viewer_is_busy_selected_wins_over_page_and_the_topmost_highlight_is_hit(
    page: Page,
) -> None:
    open_page(page)
    page.evaluate(f"() => {{ window.__first = window.native.showDocument({_DOC}) }}")
    page.wait_for_function("() => window.__viewer.state !== null")
    state = page.evaluate("() => window.__viewer.state")
    assert (state["selected"], state["page"]) == ("b", 3)  # selected wins over page 1

    second = page.evaluate("() => window.native.showDocument({ url: '/files/offer.pdf' })")
    assert second["error"] == "busy"

    page.evaluate(
        "() => { window.__ev = []; window.native.on('documentTap', (e) => window.__ev.push(e)) }"
    )
    page.evaluate(
        "() => window.__viewer.tapAt(3, 0.3, 0.3)"
    )  # inside b and c: the last one is on top
    page.evaluate("() => window.__viewer.tapAt(3, 0.9, 0.9)")
    assert [e["highlightId"] for e in page.evaluate("() => window.__ev")] == ["c", None]

    # An unknown selection is ignored.
    page.evaluate("() => window.native.updateDocument({ id: 'pdf', selected: 'nope', page: 2 })")
    state = page.evaluate("() => window.__viewer.state")
    assert (state["selected"], state["page"]) == ("b", 2)
    page.evaluate("() => window.__viewer.close()")
    page.evaluate("() => window.__first")


def test_the_viewer_gets_a_generated_id_when_the_page_gives_none(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => { window.__first = window.native.showDocument({ url: '/files/offer.pdf' }) }"
    )
    page.wait_for_function("() => window.__viewer.state !== null")
    assert page.evaluate("() => window.__viewer.state.id").startswith("doc-")
    page.evaluate("() => window.__viewer.close()")


# --- D20 pickers ----------------------------------------------------------------------------------------------------------


def test_a_preselected_value_that_is_not_an_option_is_ignored(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__picker.script.push({ dismiss: true }, { dismiss: true })")
    options = "[{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]"
    page.evaluate(
        f"() => window.native.showPicker({{ kind: 'option', value: 'zzz', options: {options} }})"
    )
    page.evaluate(
        f"() => window.native.showPicker({{ kind: 'option', value: 'b', options: {options} }})"
    )
    assert [s["preselected"] for s in page.evaluate("() => window.__picker.shown")] == [None, "b"]


# --- D22 search ----------------------------------------------------------------------------------------------------------------


def test_a_scope_change_calls_search_with_the_current_query(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => { window.__ev = []; window.native.on('search', (e) => window.__ev.push(e)) }"
    )
    page.evaluate(
        """() => window.native.setChrome({ search: { id: 'o', placeholder: 'p', value: '',
          scopes: [{ id: 'all', label: 'All' }, { id: 'mine', label: 'Mine' }] } })"""
    )
    page.wait_for_function("() => window.__chrome.searchField() !== null")
    page.evaluate("() => window.__chrome.submitSearch('müller')")
    page.evaluate("() => window.__chrome.selectScope('mine')")
    assert page.evaluate("() => window.__ev.at(-1)") == {
        "id": "o",
        "query": "müller",
        "scope": "mine",
        "submitted": False,
        "source": "typing",
    }


def test_the_value_of_set_chrome_is_applied_only_if_it_differs_from_the_last_one(
    page: Page,
) -> None:
    open_page(page)
    send = "(v) => window.native.setChrome({ search: { id: 'o', placeholder: 'p', value: v } })"
    page.evaluate(send, "first")
    page.wait_for_function("() => window.__chrome.searchField()?.value === 'first'")
    page.evaluate("() => window.__chrome.submitSearch('typed by the user')")
    page.evaluate(send, "first")  # the same as before: what the user typed stays
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length >= 2)"
    )
    assert page.evaluate("() => window.__chrome.searchField().value") == "typed by the user"
    page.evaluate(send, "second")  # a new value: applied
    page.wait_for_function("() => window.__chrome.searchField().value === 'second'")


# --- D2 setChrome parts of an app without the feature are not sent --------------------------------------------------------------------


def test_set_chrome_sends_only_the_parts_the_app_lists(page: Page) -> None:
    open_page(page, "/?features=segments")
    page.evaluate(
        """() => window.native.setChrome({
          title: { text: 'T' }, search: { id: 's', placeholder: 'p' },
          segments: { id: 'v', items: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], selected: 'a' },
          undo: { canUndo: true, canRedo: false },
        })"""
    )
    _wait_log(page)
    sent = _log(page)[0]
    assert set(sent) == {"action", "segments"}


def test_a_base64_data_url_roundtrip_is_unchanged_by_all_this(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => window.__docs.script.push({ documents: [{ name: 'a.pdf', content: 'hello' }] })"
    )
    res = page.evaluate("() => window.native.scanDocument({ mode: 'return' })")
    assert base64.b64decode(res["documents"][0]["data"]) == b"hello"
