"""Dictation, microphone, layout, back interception and tokens for other APIs,
with the built npm package in a real browser.

The native sheet, the keyboard and the back button are played by the page's fake
bridge (`window.__voice`, `window.__layout`, `window.__back`); tokens come from
the Python harness. The real iOS app does not take part.
"""

import json
from pathlib import Path

from helpers import open_page
from playwright.sync_api import Page

FIXTURES = Path(__file__).resolve().parent.parent / "contract-fixtures"
OTHER_RESOURCE = "api://44444444-4444-4444-8444-4444444444ee/.default"


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


# --- dictate and the microphone ----------------------------------------------------


def test_dictate_returns_the_text_and_sends_the_options(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__voice.script.push({ text: 'Zwei Paletten' })")
    res = page.evaluate(
        """() => window.native.dictate({
          locale: 'de-CH', maxSeconds: 30, contextualStrings: ['Palette'],
        })"""
    )

    assert res == {"ok": True, "text": "Zwei Paletten", "locale": "de-CH"}
    assert _log(page) == [
        {"action": "dictate", "locale": "de-CH", "maxSeconds": 30, "contextualStrings": ["Palette"]}
    ]


def test_dictate_uses_the_device_language_by_default(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__voice.script.push({ text: 'hello', locale: 'fr-CH' })")
    assert page.evaluate("() => window.native.dictate()") == {
        "ok": True,
        "text": "hello",
        "locale": "fr-CH",
    }
    assert _log(page) == [{"action": "dictate"}]


def test_dictate_errors(page: Page) -> None:
    open_page(page)
    for error in ("cancelled", "denied", "unavailable"):
        page.evaluate("(error) => window.__voice.script.push({ error })", error)
        assert page.evaluate("() => window.native.dictate()") == {"ok": False, "error": error}
    open_page(page, "/?capabilities=camera")
    assert page.evaluate("() => window.native.dictate()")["error"] == "capability"


def test_dictate_invalid_options_are_refused_by_the_package_and_the_app(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.native.dictate({ maxSeconds: 121 })")["error"] == "invalid"
    assert _log(page) == []
    raw = page.evaluate("() => window.native.call('dictate', { maxSeconds: 121 })")
    assert raw["error"] == "invalid"


def test_dictate_in_an_old_app_and_the_browser(page: Page) -> None:
    open_page(page, "/?oldApp")
    assert page.evaluate("() => window.native.dictate()") == {"ok": False, "error": "unavailable"}
    assert page.evaluate("() => window.native.call('dictate', {})") == {
        "ok": False,
        "error": "unknownAction",
    }
    open_page(page, "/?browser")
    assert page.evaluate("() => window.native.dictate()") == {"ok": False, "error": "unavailable"}


def _microphone(page: Page) -> str:
    return page.evaluate(
        """async () => {
          try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
            stream.getTracks().forEach((t) => t.stop())
            return 'granted'
          } catch (e) {
            return e.name
          }
        }"""
    )


def test_the_microphone_is_granted_to_the_page_only_with_the_capability(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.native.hasFeature('mediaCapture')") is True
    assert page.evaluate("() => window.native.can('microphone')") is True
    assert _microphone(page) == "granted"
    open_page(page, "/?capabilities=camera")
    assert page.evaluate("() => window.native.can('microphone')") is False
    assert _microphone(page) == "NotAllowedError"


# --- layout -------------------------------------------------------------------------------


def test_get_layout_and_the_attributes_on_html(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.native.getLayout()") == {
        "ok": True,
        "keyboardHeight": 0,
        "keyboardVisible": False,
        "sizeClass": "compact",
        "orientation": "portrait",
        "width": 390,
        "height": 664,
    }
    html = page.evaluate(
        """() => ({
          height: document.documentElement.style.getPropertyValue('--bms-keyboard-height'),
          size: document.documentElement.dataset.bmsSizeClass,
          orientation: document.documentElement.dataset.bmsOrientation,
        })"""
    )
    assert html == {"height": "0px", "size": "compact", "orientation": "portrait"}


def test_layout_changes_reach_the_page_and_keyboard_height(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.__seen = []
          window.native.on('layoutChange', (l) => window.__seen.push(l))
        }"""
    )
    page.evaluate("() => window.__layout.set({ keyboardHeight: 336 })")
    page.evaluate(
        """() => window.__layout.set({
          keyboardHeight: 0, sizeClass: 'regular', orientation: 'landscape',
          width: 1180, height: 820,
        })"""
    )

    seen = page.evaluate("() => window.__seen")
    assert [(s["keyboardHeight"], s["keyboardVisible"]) for s in seen] == [(336, True), (0, False)]
    assert seen[1]["sizeClass"] == "regular" and seen[1]["orientation"] == "landscape"
    assert (seen[1]["width"], seen[1]["height"]) == (1180, 820)

    page.evaluate("() => window.__layout.set({ keyboardHeight: 300 })")
    assert page.evaluate("() => window.native.keyboardHeight()") == 300
    assert (
        page.evaluate(
            "() => document.documentElement.style.getPropertyValue('--bms-keyboard-height')"
        )
        == "300px"
    )


def test_layout_without_the_app_or_the_feature(page: Page) -> None:
    open_page(page, "/?oldApp")
    assert page.evaluate("() => window.native.getLayout()") == {"ok": False, "error": "unavailable"}
    assert page.evaluate("() => window.native.keyboardHeight()") == 0
    assert page.evaluate("() => document.documentElement.dataset.bmsSizeClass") is None
    open_page(page, "/?browser")
    assert page.evaluate("() => window.native.getLayout()") == {"ok": False, "error": "unavailable"}
    assert page.evaluate("() => window.native.keyboardHeight()") == 0


# --- back interception ------------------------------------------------------------------------


def _press(page: Page, source: str) -> str:
    return page.evaluate("(source) => window.__back.press(source)", source)


def test_back_is_handled_by_the_page(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.__sources = []
          window.__off = window.native.onBackRequested((source) => {
            window.__sources.push(source)
            return true
          })
        }"""
    )
    page.wait_for_function("() => window.__back.enabled")
    assert _press(page, "button") == "handled"
    assert _press(page, "swipe") == "handled"
    assert page.evaluate("() => window.__sources") == ["button", "swipe"]
    actions = [(m["action"], m.get("enabled", m.get("handled"))) for m in _log(page)]
    assert actions == [
        ("setBackInterception", True),
        ("backResult", True),
        ("backResult", True),
    ]


def test_back_falls_through_when_the_page_does_not_handle_it(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.native.onBackRequested(async (source) => source === 'swipe') }")
    page.wait_for_function("() => window.__back.enabled")
    assert _press(page, "button") == "default"
    assert _press(page, "swipe") == "handled"


def test_a_slow_handler_counts_as_not_handled(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.native.onBackRequested(
            () => new Promise((resolve) => setTimeout(() => resolve(true), 2000))
          )
        }"""
    )
    page.wait_for_function("() => window.__back.enabled")
    assert _press(page, "button") == "default"
    # The package answered before the app's 800 ms ran out.
    answered = [m for m in _log(page) if m["action"] == "backResult"]
    assert answered == [{"action": "backResult", "handled": False}]


def test_a_long_press_closes_the_web_app_whatever_the_page_says(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.native.onBackRequested(() => true) }")
    page.wait_for_function("() => window.__back.enabled")
    assert page.evaluate("() => window.__back.longPress()") == "close"
    assert [m["action"] for m in _log(page)] == ["setBackInterception"]


def test_back_interception_ends_with_the_cleanup(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__off = window.native.onBackRequested(() => true) }")
    page.wait_for_function("() => window.__back.enabled")
    page.evaluate("() => window.__off()")
    page.wait_for_function("() => !window.__back.enabled")
    assert _press(page, "button") == "default"
    assert page.evaluate("() => typeof window.onNativeBackRequested") == "undefined"


def test_back_interception_is_refused_for_bad_payloads_by_the_app(page: Page) -> None:
    open_page(page)
    for payload in ({}, {"enabled": "yes"}):
        raw = page.evaluate("(p) => window.native.call('setBackInterception', p)", payload)
        assert raw["error"] == "invalid"
    assert page.evaluate("() => window.__back.enabled") is False


def test_back_in_old_apps_and_the_browser_does_nothing(page: Page) -> None:
    open_page(page, "/?oldApp")
    page.evaluate("() => { window.native.onBackRequested(() => true)() }")
    assert _log(page) == []
    assert page.evaluate("() => typeof window.onNativeBackRequested") == "undefined"
    open_page(page, "/?browser")
    assert page.evaluate("() => typeof window.native.onBackRequested(() => true)") == "function"


# --- tokens for other APIs -----------------------------------------------------------------------


def _bearer(page: Page, token: str, path: str) -> int:
    return page.request.get(path, headers={"Authorization": f"Bearer {token}"}).status


def test_a_resource_token_is_for_the_other_api_only(page: Page) -> None:
    open_page(page)
    page.request.post(
        "/test/token-resources", data={"resources": [OTHER_RESOURCE], "consented": [OTHER_RESOURCE]}
    )
    res = page.evaluate("(resource) => window.native.getAccessToken({ resource })", OTHER_RESOURCE)

    assert res["ok"] is True and res["resource"] == OTHER_RESOURCE
    assert _bearer(page, res["token"], "/api/other-api/me") == 200
    assert _bearer(page, res["token"], "/api/me") == 401  # not for this web app's backend

    normal = page.evaluate("() => window.native.getAccessToken()")
    assert "resource" not in normal
    assert _bearer(page, normal["token"], "/api/me") == 200
    assert _bearer(page, normal["token"], "/api/other-api/me") == 401


def test_a_resource_that_is_not_configured_is_forbidden(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        """() => window.native.getAccessToken({
          resource: 'api://99999999-9999-4999-8999-999999999999/.default',
        })"""
    )
    assert res == {"ok": False, "error": "forbidden"}


def test_consent_is_required_unless_the_app_may_show_it(page: Page) -> None:
    open_page(page)
    needed = page.evaluate(
        "(resource) => window.native.getAccessToken({ resource })", OTHER_RESOURCE
    )
    assert needed == {"ok": False, "error": "consentRequired"}

    shown = page.evaluate(
        "(resource) => window.native.getAccessToken({ resource, interactive: true })",
        OTHER_RESOURCE,
    )
    assert shown["ok"] is True
    # The user has consented now: silent from here on.
    again = page.evaluate(
        "(resource) => window.native.getAccessToken({ resource })", OTHER_RESOURCE
    )
    assert again["ok"] is True
    assert _log(page)[1] == {
        "action": "getAccessToken",
        "resource": OTHER_RESOURCE,
        "interactive": True,
    }


def test_a_resource_token_needs_the_identity_capability(page: Page) -> None:
    open_page(page, "/?capabilities=camera")
    res = page.evaluate("(resource) => window.native.getAccessToken({ resource })", OTHER_RESOURCE)
    assert res["error"] == "capability"


def test_an_old_app_would_hand_out_the_normal_token_so_the_package_does_not_ask(
    page: Page,
) -> None:
    open_page(page, "/?oldApp")
    assert page.evaluate(
        "(resource) => window.native.getAccessToken({ resource })", OTHER_RESOURCE
    ) == {"ok": False, "error": "unavailable"}
    assert _log(page) == []
    # What the old app answers when asked anyway: the token of this web app, no resource.
    raw = page.evaluate(
        "(resource) => window.native.call('getAccessToken', { resource })", OTHER_RESOURCE
    )
    assert raw["ok"] is True and "resource" not in raw
    # Without a resource nothing changed.
    assert page.evaluate("() => window.native.getAccessToken()")["ok"] is True


def test_the_fixture_results_exist_for_every_error_of_the_other_api(page: Page) -> None:
    errors = {
        case["value"]["error"]
        for case in json.loads((FIXTURES / "access-token-resource.json").read_text())["results"][
            "valid"
        ]
        if not case["value"]["ok"]
    }
    assert errors == {"consentRequired", "forbidden", "capability", "notSignedIn"}
