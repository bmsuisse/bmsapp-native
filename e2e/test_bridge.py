"""The built `@bmsuisse/app-native` in the browser against the Python models.

See server.py: `window.BMSNative` forwards every message to the harness,
which validates the formats with the same Pydantic models backends use.
"""

import json
from pathlib import Path

from helpers import open_page
from playwright.sync_api import Page

FIXTURES = Path(__file__).resolve().parent.parent / "contract-fixtures"


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def test_feed_widgets_round_trip(page: Page) -> None:
    """Python feed → web app → setWidgets → Python models: nothing gets lost."""
    open_page(page)
    result = page.evaluate(
        """async () => {
          const feed = await fetch('/api/widgets').then((r) => r.json())
          return { schema: feed.schema, res: await window.native.setWidgets(feed.widgets) }
        }"""
    )
    expected = len(json.loads((FIXTURES / "widgets.json").read_text()))
    assert result["schema"] == 1
    assert result["res"] == {"ok": True, "accepted": expected, "rejected": 0}


def test_invalid_widget_is_rejected(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        """() => window.native.setWidgets([
          { id: 'ok', kind: 'kpi', data: { value: 1 } },
          { id: 'broken', kind: 'kpi', data: {} },
        ])"""
    )
    assert res == {"ok": True, "accepted": 1, "rejected": 1}


def test_live_activity_lifecycle(page: Page) -> None:
    open_page(page)
    state = json.loads((FIXTURES / "live-activity-state.json").read_text())
    res = page.evaluate(
        """async (state) => {
          const n = window.native
          return {
            start: await n.startLiveActivity({ id: 'A-123', state, path: '/orders/A-123' }),
            update: await n.updateLiveActivity({
              id: 'A-123',
              state: { ...state, currentStep: 2, status: 'Ready' },
              alert: { title: 'Ready for pickup' },
            }),
            invalid: await n.updateLiveActivity({ id: 'A-123', state: { title: '' } }),
            running: await n.getLiveActivities(),
          }
        }""",
        state,
    )
    assert res["start"] == {"ok": True}
    assert res["update"] == {"ok": True}
    assert res["invalid"] == {"ok": False, "error": "invalid"}
    assert res["running"] == {"ok": True, "ids": ["A-123"]}


def test_fire_and_forget_messages_reach_the_app(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.native.setChrome({
            scope: 'route',
            menu: [{ items: [{ id: 'new', label: 'New', icon: 'plus' }] }],
          })
          window.native.toast('Saved', 'success')
          window.native.haptic('success')
        }"""
    )
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length >= 3)"
    )
    log = _log(page)
    assert [m["action"] for m in log] == ["setChrome", "toast", "haptic"]
    assert log[0]["menu"][0]["items"][0]["id"] == "new"
    assert log[1] == {"action": "toast", "message": "Saved", "style": "success"}


def test_app_callbacks_reach_listeners(page: Page) -> None:
    """The app calls global functions (`onNativeMenuSelect`, …) — `on()` dispatches them."""
    open_page(page)
    received = page.evaluate(
        """() => {
          const got = []
          window.native.on('menuSelect', (id) => got.push(['menu', id]))
          window.native.on('barcodeScanned', (v) => got.push(['barcode', v]))
          window.onNativeMenuSelect('new')
          window.onBarcodeScanned('4006381333931')
          return got
        }"""
    )
    assert received == [["menu", "new"], ["barcode", "4006381333931"]]


def test_browser_without_app(page: Page) -> None:
    """Without BMSNative: nothing throws, calls with a response report `unavailable`."""
    open_page(page, "/?browser=1")
    res = page.evaluate(
        """async () => ({
          native: window.native.isNativeApp(),
          widgets: await window.native.setWidgets([]),
          biometric: await window.native.biometricConfirm('x'),
        })"""
    )
    assert res == {
        "native": False,
        "widgets": {"ok": False, "error": "unavailable"},
        "biometric": {"ok": True},
    }
    assert _log(page) == []
