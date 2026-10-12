"""Text scan and multi-barcode scan with the built npm package in a real browser:
what reaches the app, results, errors, the callbacks, and the fallbacks.

The scanner is played by the page's fake bridge (`window.__scan.script`); the
real iOS app does not take part.
"""

from helpers import open_page
from playwright.sync_api import Page


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def _script(page: Page, *steps: dict) -> None:
    page.evaluate("(steps) => window.__scan.script.push(...steps)", list(steps))


def test_scan_text_returns_the_tapped_line(page: Page) -> None:
    open_page(page)
    _script(page, {"text": "AB-1234"})
    result = page.evaluate(
        """async () => {
          const heard = []
          window.native.on('textScanned', (t) => heard.push(t))
          const res = await window.native.scanText({ pattern: /[A-Z]{2}-\\d{4,}/i })
          return { res, heard }
        }"""
    )
    assert result["res"] == {"ok": True, "text": "AB-1234"}
    assert result["heard"] == ["AB-1234"]
    assert _log(page) == [{"action": "scanText", "pattern": "[A-Z]{2}-\\d{4,}"}]


def test_multi_scan_collects_codes(page: Page) -> None:
    open_page(page)
    _script(page, {"values": ["4006381333931", "https://example.com/a"]})
    result = page.evaluate(
        """async () => {
          const heard = []
          window.native.on('barcodesScanned', (v) => heard.push(v))
          const res = await window.native.scanBarcodes({ formats: ['ean13', 'qr'], max: 20 })
          return { res, heard }
        }"""
    )
    assert result["res"] == {"ok": True, "values": ["4006381333931", "https://example.com/a"]}
    assert result["heard"] == [["4006381333931", "https://example.com/a"]]
    assert _log(page) == [
        {"action": "scanBarcode", "multiple": True, "formats": ["ean13", "qr"], "max": 20}
    ]


def test_single_scan_with_formats_resolves_with_the_value(page: Page) -> None:
    open_page(page)
    _script(page, {"value": "4006381333931"})
    res = page.evaluate("() => window.native.scanBarcode({ formats: ['ean13'] })")
    assert res == {"ok": True, "value": "4006381333931"}


def test_scan_barcode_without_options_stays_callback_only(page: Page) -> None:
    open_page(page)
    _script(page, {"value": "123"})
    result = page.evaluate(
        """async () => {
          const heard = []
          window.native.on('barcodeScanned', (v) => heard.push(v))
          const res = await window.native.scanBarcode()
          return { res, heard }
        }"""
    )
    assert result == {"res": {"ok": True}, "heard": ["123"]}


def test_errors_reach_the_page(page: Page) -> None:
    open_page(page)
    for error in ("cancelled", "unavailable", "denied", "busy"):
        _script(page, {"error": error, "message": "m"})
        res = page.evaluate("() => window.native.scanText()")
        assert res == {"ok": False, "error": error, "message": "m"}


def test_invalid_options_are_refused_by_the_app(page: Page) -> None:
    open_page(page)
    too_long = page.evaluate("() => window.native.scanText({ pattern: 'a'.repeat(201) })")
    assert too_long["error"] == "invalid"
    max_out = page.evaluate("() => window.native.scanBarcodes({ max: 201 })")
    assert max_out["error"] == "invalid"


def test_a_second_scan_while_one_is_open_is_busy(page: Page) -> None:
    open_page(page)
    _script(page, {"hold": True})
    page.evaluate("() => { window.__first = window.native.scanText() }")
    page.wait_for_function("() => window.__scan.open")
    res = page.evaluate("() => window.native.scanText()")
    assert res["error"] == "busy"
    page.evaluate("() => window.__scan.held({ ok: false, error: 'cancelled' })")


def test_without_the_camera_capability(page: Page) -> None:
    open_page(page, "/?capabilities=deviceApps")
    assert page.evaluate("() => window.native.canScan()") is False
    res = page.evaluate("() => window.native.scanText()")
    assert res["error"] == "capability"


def test_an_old_app(page: Page) -> None:
    open_page(page, "/?oldApp")
    text = page.evaluate("() => window.native.scanText()")
    assert text == {"ok": False, "error": "unavailable"}

    # The old app ignores the options; the code only comes through the callback.
    _script(page, {"values": ["ONE", "TWO"]})
    res = page.evaluate("() => window.native.scanBarcodes({ max: 5 })")
    assert res == {"ok": True, "values": ["ONE"], "oldApp": True}


def test_without_the_app(page: Page) -> None:
    open_page(page, "/?browser")
    res = page.evaluate(
        """async () => ({
          text: await window.native.scanText(),
          one: await window.native.scanBarcode({ formats: ['qr'] }),
          many: await window.native.scanBarcodes(),
          can: window.native.canScan(),
        })"""
    )
    unavailable = {"ok": False, "error": "unavailable"}
    assert res == {"text": unavailable, "one": unavailable, "many": unavailable, "can": False}
