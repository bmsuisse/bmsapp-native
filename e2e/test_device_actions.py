"""Device actions (navigate, addReminder, saveContact, callPhone) with the built
npm package in a real browser: what reaches the app, and the fallbacks without it.

The harness answers like the app does (`invalid` for incomplete details, else
`ok` with a sentence). The real iOS app does not take part.
"""

from urllib.parse import parse_qs, urlparse

from helpers import open_page
from playwright.sync_api import Page


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def test_device_actions_reach_the_app(page: Page) -> None:
    open_page(page)
    results = page.evaluate(
        """async () => {
          const n = window.native
          return {
            navigate: await n.navigate({
              destination: { address: 'Industriestrasse 5, 4600 Olten' },
              waypoints: ['Bern'],
              app: 'google',
            }),
            reminder: await n.addReminder({
              title: 'Call back',
              due: n.toIsoWithOffset(new Date(2026, 9, 2, 9, 0, 0)),
              confirm: false,
            }),
            contact: await n.saveContact({
              givenName: 'Anna',
              phones: [{ label: 'mobile', value: '+41 79 000 00 00' }],
            }),
            call: await n.callPhone({ number: '+41 44 000 00 00' }),
            // The types forbid this: a contact needs a name or a company.
            invalid: await n.saveContact({ phones: ['+41'] }),
          }
        }"""
    )

    for name in ("navigate", "reminder", "contact", "call"):
        assert results[name]["ok"] is True
        assert results[name]["message"]
    assert results["invalid"] == {"ok": False, "error": "invalid", "message": "Ungültige Angaben."}

    log = _log(page)
    assert [m["action"] for m in log] == [
        "navigate",
        "addReminder",
        "saveContact",
        "callPhone",
        "saveContact",
    ]
    assert log[0]["destination"] == {"address": "Industriestrasse 5, 4600 Olten"}
    assert log[0]["waypoints"] == ["Bern"]
    assert log[0]["app"] == "google"
    # The time zone of the browser is Europe/Zurich (see conftest.py): +02:00 in October.
    assert log[1]["due"] == "2026-10-02T09:00:00+02:00"
    assert log[1]["confirm"] is False
    assert log[2]["phones"] == [{"label": "mobile", "value": "+41 79 000 00 00"}]
    assert log[3]["number"] == "+41 44 000 00 00"


def test_navigate_in_a_browser_opens_google_maps_in_a_new_tab(page: Page) -> None:
    # No real request to Google.
    page.context.route("https://www.google.com/**", lambda route: route.fulfill(body="maps"))
    open_page(page, "/?browser=1")

    with page.context.expect_page() as opened:
        result = page.evaluate(
            """() => window.native.navigate({
              address: 'Bahnhofstrasse 1, 8001 Zürich',
              mode: 'walking',
            })"""
        )

    assert result["ok"] is True
    assert result["app"] == "google"
    url = urlparse(opened.value.url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://www.google.com/maps/dir/"
    query = parse_qs(url.query)
    assert query["api"] == ["1"]
    assert query["destination"] == ["Bahnhofstrasse 1, 8001 Zürich"]
    assert query["travelmode"] == ["walking"]
    assert _log(page) == []  # nothing went to the app


def test_call_phone_in_a_browser_opens_a_tel_link(page: Page) -> None:
    open_page(page, "/?browser=1")
    page.evaluate(
        """() => {
          window.__clicked = []
          HTMLAnchorElement.prototype.click = function () {
            window.__clicked.push(this.getAttribute('href'))
          }
        }"""
    )

    result = page.evaluate("() => window.native.callPhone({ number: '+41 44 000 00 00' })")

    assert result["ok"] is True
    assert page.evaluate("() => window.__clicked") == ["tel:+41440000000"]


def test_reminder_and_contact_are_unavailable_in_a_browser(page: Page) -> None:
    open_page(page, "/?browser=1")
    result = page.evaluate(
        """async () => ({
          reminder: await window.native.addReminder({ title: 'x' }),
          contact: await window.native.saveContact({ givenName: 'Anna' }),
        })"""
    )

    for name in ("reminder", "contact"):
        assert result[name]["ok"] is False
        assert result[name]["error"] == "unavailable"
        assert result[name]["message"]
    assert _log(page) == []


def test_date_helpers_use_the_time_zone_of_the_browser(page: Page) -> None:
    open_page(page, "/?browser=1")
    result = page.evaluate(
        """() => ({
          summer: window.native.toIsoWithOffset(new Date(2026, 9, 2, 9, 0, 0)),
          winter: window.native.toIsoWithOffset(new Date(2026, 0, 15, 17, 5, 9)),
          // 00:30 local is still the day before in UTC: the trap of toISOString().
          dateOnly: window.native.toDateOnly(new Date(2026, 9, 2, 0, 30)),
          utcDate: new Date(2026, 9, 2, 0, 30).toISOString().slice(0, 10),
        })"""
    )

    assert result == {
        "summer": "2026-10-02T09:00:00+02:00",
        "winter": "2026-01-15T17:05:09+01:00",
        "dateOnly": "2026-10-02",
        "utcDate": "2026-10-01",
    }
