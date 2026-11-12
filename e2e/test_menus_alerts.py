"""Menus, alerts, toasts with an action and pickers (2026-11b) with the built npm
package in a real browser. The native UI is played by the page's fake bridge
(`window.__menu`, `__alert`, `__toast`, `__picker`, `__chrome`); the real iOS app does
not take part.
"""

from helpers import open_page
from playwright.sync_api import Page

ANCHOR = {"x": 24, "y": 120, "width": 44, "height": 44}


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def _no_dialogs(page: Page) -> list[str]:
    """`window.confirm`, `alert` and `prompt` must never be used as a fallback."""
    seen: list[str] = []

    def on_dialog(dialog) -> None:  # type: ignore[no-untyped-def]
        seen.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)
    return seen


# --- showMenu -----------------------------------------------------------------------


def test_show_menu_resolves_the_chosen_item(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__menu.script.push({ select: 'share' })")
    res = page.evaluate(
        """(anchor) => window.native.showMenu({
          anchor,
          preview: { title: 'Offer 4711', subtitle: 'Müller AG' },
          sections: [
            { title: 'Offer', items: [{ id: 'open', label: 'Open' }, { id: 'share', label: 'Share', icon: 'square.and.arrow.up' }] },
            { items: [{ id: 'delete', label: 'Delete', destructive: true }] },
          ],
        })""",
        ANCHOR,
    )

    assert res == {"ok": True, "id": "share"}
    shown = page.evaluate("() => window.__menu.shown")
    assert shown[0]["anchor"] == ANCHOR
    assert shown[0]["preview"] == {"title": "Offer 4711", "subtitle": "Müller AG"}
    assert [m["action"] for m in _log(page)] == ["showMenu"]


def test_show_menu_dismissed_and_busy(page: Page) -> None:
    open_page(page)
    assert page.evaluate(
        "(a) => window.native.showMenu({ anchor: a, sections: [{ items: [{ id: 'a', label: 'A' }] }] })",
        ANCHOR,
    ) == {"ok": False, "error": "cancelled"}

    page.evaluate("() => window.__menu.script.push({ hold: true })")
    page.evaluate(
        "(a) => { window.__open = window.native.showMenu({ anchor: a, sections: [{ items: [{ id: 'a', label: 'A' }] }] }) }",
        ANCHOR,
    )
    page.wait_for_function("() => window.__menu.open !== null")
    busy = page.evaluate(
        "(a) => window.native.showMenu({ anchor: a, sections: [{ items: [{ id: 'b', label: 'B' }] }] })",
        ANCHOR,
    )
    assert busy["error"] == "busy"
    page.evaluate("() => window.__menu.held()")
    assert page.evaluate("() => window.__open") == {"ok": False, "error": "cancelled"}


_LAZY = """(a) => window.native.showMenu({
  anchor: a,
  sections: [{ items: [
    { id: 'open', label: 'Open' },
    { id: 'send', label: 'Send to …', children: 'lazy', lazyFailedLabel: 'Could not load' },
  ] }],
  loadChildren: LOAD,
})"""


def test_a_lazy_item_is_loaded_when_the_user_opens_it(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__menu.script.push({ expand: ['send'], select: 'anna' })")
    code = _LAZY.replace(
        "LOAD",
        """async (itemId) => {
          window.__asked = itemId
          return [{ title: 'Recent', items: [{ id: 'anna', label: 'Anna Muster' }] }]
        }""",
    )
    res = page.evaluate(code, ANCHOR)

    assert res == {"ok": True, "id": "anna"}
    assert page.evaluate("() => window.__asked") == "send"
    [shown] = page.evaluate("() => window.__menu.shown")
    assert shown["expansions"]["send"]["state"] == "loaded"
    assert shown["expansions"]["send"]["rows"] == [{"id": "anna", "label": "Anna Muster"}]
    # The harness (Python) validated menuItems against the menu.
    assert [m["action"] for m in _log(page)] == ["showMenu", "menuItems"]
    assert "loadChildren" not in _log(page)[0]


def test_a_lazy_item_that_is_not_answered_in_time_shows_the_failed_row(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__menu.lazyTimeout = 300 }")
    page.evaluate("() => window.__menu.script.push({ expand: ['send'], hold: true })")
    page.evaluate(
        """(a) => {
          window.__open = window.native.showMenu({
            anchor: a,
            sections: [{ items: [
              { id: 'send', label: 'Send to …', children: 'lazy', lazyFailedLabel: 'Could not load' },
            ] }],
            loadChildren: () => new Promise((resolve) =>
              setTimeout(() => resolve([{ items: [{ id: 'late', label: 'Late' }] }]), 800)
            ),
          })
        }""",
        ANCHOR,
    )
    page.wait_for_function("() => window.__menu.shown[0]?.expansions.send?.state === 'failed'")
    [shown] = page.evaluate("() => window.__menu.shown")
    assert shown["expansions"]["send"]["rows"] == [
        {"id": None, "label": "Could not load", "disabled": True}
    ]
    # The page answers after the app gave up (the menu is still open): the app ignores it.
    page.wait_for_function("() => window.__menu.late.length === 1")
    page.evaluate("() => window.__menu.held()")
    assert page.evaluate("() => window.__open")["error"] == "cancelled"


def test_a_failed_lazy_item_without_a_label_shows_a_dash(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__menu.lazyTimeout = 200 }")
    page.evaluate("() => window.__menu.script.push({ expand: ['send'] })")
    code = _LAZY.replace(", lazyFailedLabel: 'Could not load'", "").replace(
        "LOAD", "() => new Promise(() => {})"
    )
    page.evaluate(code, ANCHOR)
    [shown] = page.evaluate("() => window.__menu.shown")
    assert shown["expansions"]["send"]["rows"][0]["label"] == "–"


def test_a_loader_that_returns_an_invalid_menu_is_not_answered(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__menu.lazyTimeout = 200 }")
    page.evaluate("() => window.__menu.script.push({ expand: ['send'] })")
    code = _LAZY.replace(
        "LOAD", "async () => [{ items: [{ id: 'open', label: 'same id as the menu' }] }]"
    )
    page.evaluate(code, ANCHOR)
    assert [m["action"] for m in _log(page)] == ["showMenu"]
    # The harness refuses the same answer when it is sent directly.
    raw = page.evaluate(
        """() => window.native.call('menuItems', {
          requestId: 'r', sections: [{ items: [{ id: 'open', label: 'same id' }] }],
        })"""
    )
    assert raw["error"] == "invalid"


def test_menus_are_unavailable_in_old_apps_and_the_browser(page: Page) -> None:
    for path in ("/?oldApp", "/?browser"):
        open_page(page, path)
        res = page.evaluate(
            "(a) => window.native.showMenu({ anchor: a, sections: [{ items: [{ id: 'a', label: 'A' }] }] })",
            ANCHOR,
        )
        assert res == {"ok": False, "error": "unavailable"}
        assert _log(page) == []
    open_page(page, "/?oldApp")
    raw = page.evaluate("() => window.native.call('showMenu', {})")
    assert raw["error"] == "unknownAction"


def test_show_menu_needs_the_custom_chrome_capability(page: Page) -> None:
    open_page(page, "/?capabilities=camera")
    res = page.evaluate(
        "(a) => window.native.showMenu({ anchor: a, sections: [{ items: [{ id: 'a', label: 'A' }] }] })",
        ANCHOR,
    )
    assert res["error"] == "capability"


# --- menus of action buttons and of the title -------------------------------------------


def test_an_action_button_with_a_menu_opens_it_instead_of_firing_the_tap(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.__ev = []
          window.native.on('actionButtonMenuSelect', (e) => window.__ev.push(['menu', e]))
          window.native.on('actionButtonTap', (id) => window.__ev.push(['tap', id]))
          window.native.setChrome({ actionButtons: [
            { id: 'more', icon: 'ellipsis.circle', menu: [{ items: [{ id: 'share', label: 'Share' }] }] },
            { id: 'search', icon: 'magnifyingglass' },
          ] })
        }"""
    )
    page.wait_for_function("() => window.__chrome.state.actionButtons.length === 2")

    assert page.evaluate("() => window.__chrome.tapActionButton('more')") == "menu"
    assert page.evaluate("() => window.__chrome.selectActionButtonMenu('more', 'share')") is True
    assert page.evaluate("() => window.__chrome.selectActionButtonMenu('more', 'nope')") is False
    assert page.evaluate("() => window.__chrome.tapActionButton('search')") == "tap"
    assert page.evaluate("() => window.__ev") == [
        ["menu", {"buttonId": "more", "id": "share"}],
        ["tap", "search"],
    ]


def test_an_app_without_menus_fires_the_tap_for_a_button_with_a_menu(page: Page) -> None:
    open_page(page, "/?features=titleMenu")
    page.evaluate(
        """() => {
          window.__ev = []
          window.native.on('actionButtonTap', (id) => window.__ev.push(id))
          window.native.setChrome({ actionButtons: [
            { id: 'more', icon: 'ellipsis', menu: [{ items: [{ id: 'share', label: 'Share' }] }] },
          ] })
        }"""
    )
    page.wait_for_function("() => window.__chrome.state.actionButtons.length === 1")
    assert page.evaluate("() => window.__chrome.tapActionButton('more')") == "tap"
    assert page.evaluate("() => window.__ev") == ["more"]


def test_the_title_and_its_menu(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.__ev = []
          window.native.on('titleMenuSelect', (e) => window.__ev.push(e))
          window.native.setChrome({ title: {
            text: 'Offer 4711', subtitle: 'Müller AG',
            menu: [{ items: [{ id: 'rename', label: 'Rename' }, { id: 'dup', label: 'Duplicate' }] }],
          } })
        }"""
    )
    page.wait_for_function("() => window.__chrome.navTitle() !== null")
    assert page.evaluate("() => window.__chrome.navTitle()") == {
        "text": "Offer 4711",
        "subtitle": "Müller AG",
        "menu": [
            {"items": [{"id": "rename", "label": "Rename"}, {"id": "dup", "label": "Duplicate"}]}
        ],
        "hasMenu": True,
    }
    assert page.evaluate("() => window.__chrome.selectTitleMenu('dup')") is True
    assert page.evaluate("() => window.__ev") == [{"id": "dup"}]


def test_an_app_without_titlemenu_keeps_the_name_of_the_web_app(page: Page) -> None:
    open_page(page, "/?features=menus")
    page.evaluate("() => window.native.setChrome({ title: { text: 'Offer 4711' } })")
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length > 0)"
    )
    assert page.evaluate("() => window.__chrome.navTitle()") is None


# --- showAlert -----------------------------------------------------------------------------


_CONFIRM = """() => window.native.showAlert({
  title: 'Delete offer?', message: 'This cannot be undone.',
  actions: [
    { id: 'cancel', label: 'Cancel', style: 'cancel' },
    { id: 'delete', label: 'Delete', style: 'destructive' },
  ],
})"""


def test_an_alert_resolves_the_tapped_action(page: Page) -> None:
    open_page(page)
    dialogs = _no_dialogs(page)
    page.evaluate("() => window.__alert.script.push({ tap: 'delete' })")
    assert page.evaluate(_CONFIRM) == {"ok": True, "id": "delete"}
    [shown] = page.evaluate("() => window.__alert.shown")
    assert shown["title"] == "Delete offer?" and shown["style"] == "alert"
    assert dialogs == []


def test_an_alert_with_an_input_line_returns_the_text(page: Page) -> None:
    open_page(page)
    page.evaluate(
        "() => window.__alert.script.push({ tap: 'ok', text: 'Offer 4712 with a long name' })"
    )
    res = page.evaluate(
        """() => window.native.showAlert({
          title: 'Rename',
          actions: [{ id: 'cancel', label: 'Cancel', style: 'cancel' }, { id: 'ok', label: 'OK', preferred: true }],
          textField: { placeholder: 'Name', value: 'Offer 4711', keyboard: 'default', maxLength: 10 },
        })"""
    )
    assert res == {"ok": True, "id": "ok", "text": "Offer 4712"}


def test_a_tap_outside_an_action_sheet_is_the_cancel_action(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__alert.script.push({ outside: true }, { outside: true })")
    with_cancel = page.evaluate(
        """(anchor) => window.native.showAlert({
          title: 'Export', style: 'actionSheet', anchor,
          actions: [{ id: 'pdf', label: 'PDF' }, { id: 'close', label: 'Cancel', style: 'cancel' }],
        })""",
        ANCHOR,
    )
    assert with_cancel == {"ok": True, "id": "close"}
    without = page.evaluate(
        """() => window.native.showAlert({ title: 'Export', style: 'actionSheet', actions: [{ id: 'pdf', label: 'PDF' }] })"""
    )
    assert without == {"ok": False, "error": "cancelled"}
    shown = page.evaluate("() => window.__alert.shown")
    assert [s["centred"] for s in shown] == [False, True]  # no anchor: centred on iPad


def test_alerts_are_unavailable_without_a_fallback_to_the_browser_dialogs(page: Page) -> None:
    for path in ("/?oldApp", "/?browser"):
        open_page(page, path)
        dialogs = _no_dialogs(page)
        assert page.evaluate(_CONFIRM) == {"ok": False, "error": "unavailable"}
        assert dialogs == []
        assert _log(page) == []


def test_an_invalid_alert_never_reaches_the_app(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        "() => window.native.showAlert({ title: 'T', style: 'actionSheet', actions: [{ id: 'a', label: 'A' }], textField: {} })"
    )
    assert res["error"] == "invalid"
    assert _log(page) == []


# --- toast with an action -----------------------------------------------------------------------


def test_a_toast_with_an_action_calls_onaction_once(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        """async () => {
          window.__undone = []
          return await window.native.toast('Offer deleted', {
            action: { id: 'undo', label: 'Undo' }, onAction: (id) => window.__undone.push(id),
          })
        }"""
    )
    assert res["ok"] is True and res["toastId"].startswith("toast-")
    visible = page.evaluate("() => window.__toast.visible")
    assert (visible["message"], visible["duration"]) == ("Offer deleted", 6)

    assert page.evaluate("() => window.__toast.tap()") is True
    assert page.evaluate("() => window.__toast.tap()") is False  # the tap closed the toast
    assert page.evaluate("() => window.__undone") == ["undo"]
    assert page.evaluate("() => window.__toast.visible") is None


def test_a_new_toast_replaces_the_visible_one_and_its_action(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """async () => {
          window.__calls = []
          await window.native.toast('One', { action: { id: 'a', label: 'A' }, onAction: (id) => window.__calls.push(['one', id]) })
          await window.native.toast('Two', { duration: 4 })
        }"""
    )
    visible = page.evaluate("() => window.__toast.visible")
    assert (visible["message"], visible["duration"]) == ("Two", 4)
    assert page.evaluate("() => window.__toast.tap()") is False
    assert page.evaluate("() => window.__calls") == []
    assert [t["message"] for t in page.evaluate("() => window.__toast.history")] == ["One", "Two"]


def test_the_old_fire_and_forget_toast_still_works(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.native.toast('Saved', 'success')")
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length > 0)"
    )
    assert _log(page) == [{"action": "toast", "message": "Saved", "style": "success"}]
    assert (
        page.evaluate("() => window.__toast.visible") is None
    )  # the fake only tracks calls with a response


def test_toast_actions_in_old_apps_and_the_browser(page: Page) -> None:
    for path in ("/?oldApp", "/?browser"):
        open_page(page, path)
        res = page.evaluate("() => window.native.toast('x', { action: { id: 'a', label: 'A' } })")
        assert res == {"ok": False, "error": "unavailable"}
        assert _log(page) == []
    open_page(page, "/?oldApp")
    # What the old app does with the call: it accepts it and has no toastId.
    assert page.evaluate("() => window.native.call('toast', { message: 'x' })") == {"ok": True}


# --- showPicker ------------------------------------------------------------------------------------


def test_a_date_picker_resolves_the_chosen_date(page: Page) -> None:
    open_page(page)
    dialogs = _no_dialogs(page)
    page.evaluate("() => window.__picker.script.push({ value: '2026-12-01' })")
    res = page.evaluate(
        """() => window.native.showPicker({
          kind: 'date', title: 'Valid until', value: '2026-11-30', min: '2026-11-11',
        })"""
    )
    assert res == {"ok": True, "value": "2026-12-01"}
    assert page.evaluate("() => window.__picker.shown[0].title") == "Valid until"
    assert dialogs == []
    assert page.locator("input[type=date]").count() == 0


def test_an_option_picker_is_a_popover_with_an_anchor(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__picker.script.push({ value: 'pal' }, { dismiss: true })")
    options = (
        "[{ value: 'pcs', label: 'Pieces' }, { value: 'pal', label: 'Pallets', subtitle: 'à 48' }]"
    )
    chosen = page.evaluate(
        f"(anchor) => window.native.showPicker({{ kind: 'option', anchor, options: {options} }})",
        ANCHOR,
    )
    dismissed = page.evaluate(
        f"() => window.native.showPicker({{ kind: 'option', options: {options} }})"
    )
    assert chosen == {"ok": True, "value": "pal"}
    assert dismissed == {"ok": False, "error": "cancelled"}
    assert [s["popover"] for s in page.evaluate("() => window.__picker.shown")] == [True, False]


def test_pickers_are_unavailable_without_a_browser_fallback(page: Page) -> None:
    for path in ("/?oldApp", "/?browser"):
        open_page(page, path)
        dialogs = _no_dialogs(page)
        assert page.evaluate("() => window.native.showPicker({ kind: 'date' })") == {
            "ok": False,
            "error": "unavailable",
        }
        assert dialogs == [] and page.locator("input[type=date]").count() == 0
        assert _log(page) == []
