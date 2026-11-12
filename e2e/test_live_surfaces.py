"""Live surfaces (2026-11b): `onChange`, `updateSurface` and search fields answered
by the page, with the built npm package in a real browser. The native form is played
by the page's fake bridge (`window.__surfaces`); the real iOS app does not take part.
"""

from helpers import open_page
from playwright.sync_api import Page


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def _hold(page: Page) -> None:
    """The next surface stays open until the test closes it."""
    page.evaluate("() => window.__surfaces.script.push({ hold: true })")


def _open_form(page: Page, definition: str, options: str = "{}") -> None:
    page.evaluate(f"() => {{ window.__form = window.native.showForm({definition}, {options}) }}")
    page.wait_for_function("() => window.__surfaces.open !== null")


def _close(page: Page) -> dict:
    page.evaluate("() => window.native.closeSurface()")
    return page.evaluate("() => window.__form")


def test_changes_of_live_fields_reach_onchange(page: Page) -> None:
    open_page(page)
    _hold(page)
    page.evaluate("() => { window.__changes = [] }")
    _open_form(
        page,
        """{ id: 'f', fields: [
          { id: 'name', type: 'text' },
          { id: 'express', type: 'toggle', live: false },
          { id: 'hint', type: 'info', value: 'read-only' },
        ] }""",
        "{ onChange: (field, value) => window.__changes.push([field, value]) }",
    )

    sent = _log(page)[0]
    assert [f.get("live") for f in sent["fields"]] == [True, False, None]
    assert page.evaluate("() => window.__surfaces.type('name', 'Mül')") is True
    assert page.evaluate("() => window.__surfaces.type('express', true)") is False  # live: false
    assert page.evaluate("() => window.__changes") == [["name", "Mül"]]
    assert _close(page)["error"] == "cancelled"


def test_update_surface_keeps_focus_and_entered_values_where_ids_persist(page: Page) -> None:
    open_page(page)
    _hold(page)
    _open_form(
        page,
        "{ id: 'f', fields: [{ id: 'qty', type: 'number' }, { id: 'note', type: 'text' }] }",
        "{ onChange: () => {} }",
    )
    page.evaluate("() => window.__surfaces.type('qty', 3)")
    page.evaluate("() => window.__surfaces.type('note', 'x')")
    res = page.evaluate(
        """() => window.native.updateSurface({
          id: 'f', fields: [{ id: 'qty', type: 'number' }, { id: 'price', type: 'number' }],
        })"""
    )

    assert res == {"ok": True}
    state = page.evaluate(
        "() => ({ entered: window.__surfaces.entered, focus: window.__surfaces.focus, update: window.__surfaces.updates[0] })"
    )
    assert state["entered"] == {"qty": 3}  # `note` is gone, `qty` kept what was entered
    assert state["focus"] is None  # the focused field `note` is gone
    assert state["update"]["kept"] == ["qty"]
    # The new field is live as well, because the form was opened with onChange.
    assert _log(page)[-1]["fields"][1]["live"] is True
    _close(page)


def test_update_surface_replaces_the_blocks_of_content(page: Page) -> None:
    open_page(page)
    _hold(page)
    page.evaluate(
        """() => {
          window.__content = window.native.showContent({
            id: 'offer', blocks: [{ type: 'heading', id: 'h', text: 'Lines' }, { type: 'list', id: 'lines', items: [{ id: 'l1', title: 'Pallet' }] }],
          })
        }"""
    )
    page.wait_for_function("() => window.__surfaces.open !== null")
    res = page.evaluate(
        """() => window.native.updateSurface({
          id: 'offer', title: 'Offer 4711', blocks: [
            { type: 'heading', id: 'h', text: 'Lines (2)' },
            { type: 'list', id: 'lines', items: [{ id: 'l1', title: 'Pallet' }, { id: 'l2', title: 'Box' }] },
          ],
        })"""
    )
    assert res == {"ok": True}
    update = page.evaluate("() => window.__surfaces.updates[0]")
    assert update["keys"] == ["title", "blocks"]
    assert update["scrollKept"] is True
    assert page.evaluate("() => window.__surfaces.def.title") == "Offer 4711"
    page.evaluate("() => window.native.closeSurface()")


def test_update_surface_of_a_surface_that_is_not_open_is_not_found(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.native.updateSurface({ id: 'f', title: 'x' })") == {
        "ok": False,
        "error": "notFound",
    }
    _hold(page)
    _open_form(page, "{ id: 'f', fields: [{ id: 'a', type: 'text' }] }")
    assert (
        page.evaluate("() => window.native.updateSurface({ id: 'other', title: 'x' })")["error"]
        == "notFound"
    )
    _close(page)


def test_update_surface_is_refused_by_the_app_for_a_bad_definition(page: Page) -> None:
    open_page(page)
    _hold(page)
    _open_form(page, "{ id: 'f', fields: [{ id: 'a', type: 'text' }] }")
    res = page.evaluate(
        "() => window.native.updateSurface({ id: 'f', fields: [{ id: 'x', type: 'text', source: 'page' }] })"
    )
    assert res["error"] == "invalid"
    _close(page)


def test_update_surface_needs_a_surface_capability(page: Page) -> None:
    open_page(page, "/?capabilities=customChrome")
    assert (
        page.evaluate("() => window.native.updateSurface({ id: 'f', title: 'x' })")["error"]
        == "capability"
    )


# --- search answered by the page ---------------------------------------------------------------------


_SEARCH_FORM = (
    "{ id: 'f', fields: [{ id: 'customer', type: 'search', source: 'page', minQueryLength: 1 }] }"
)


def test_the_page_answers_a_search(page: Page) -> None:
    open_page(page)
    _hold(page)
    page.evaluate("() => { window.__asked = [] }")
    _open_form(
        page,
        _SEARCH_FORM,
        """{ onSearch: async (field, query) => {
          window.__asked.push([field, query])
          return [{ value: 'c1', label: 'Müller AG', subtitle: 'Zürich', image: 'https://example.com/c1.png' }]
        } }""",
    )
    assert page.evaluate("() => window.__surfaces.search('customer', 'mü')") is not None
    page.wait_for_function("() => window.__surfaces.found.customer?.options !== null")

    assert page.evaluate("() => window.__asked") == [["customer", "mü"]]
    found = page.evaluate("() => window.__surfaces.found.customer")
    assert found["options"] == [
        {
            "value": "c1",
            "label": "Müller AG",
            "subtitle": "Zürich",
            "image": "https://example.com/c1.png",
        }
    ]
    answered = [m for m in _log(page) if m["action"] == "surfaceSearchResult"]
    assert answered[0]["requestId"] == found["requestId"]
    _close(page)


def test_only_the_newest_search_of_a_field_is_answered(page: Page) -> None:
    open_page(page)
    _hold(page)
    _open_form(
        page,
        _SEARCH_FORM,
        """{ onSearch: (field, query) => new Promise((resolve) =>
          setTimeout(() => resolve([{ value: query, label: query }]), query === 'm' ? 400 : 20)
        ) }""",
    )
    first = page.evaluate("() => window.__surfaces.search('customer', 'm')")
    second = page.evaluate("() => window.__surfaces.search('customer', 'mü')")
    page.wait_for_function("() => window.__surfaces.found.customer?.options !== null")
    page.wait_for_timeout(600)  # the slow answer to the first request would be here by now

    answers = [m for m in _log(page) if m["action"] == "surfaceSearchResult"]
    assert [a["requestId"] for a in answers] == [second]
    assert page.evaluate("() => window.__surfaces.found.customer.options") == [
        {"value": "mü", "label": "mü"}
    ]
    assert first != second

    # An old answer sent anyway is ignored by the app.
    late = page.evaluate(
        f"() => window.native.call('surfaceSearchResult', {{ requestId: '{first}', options: [{{ value: 'x', label: 'x' }}] }})"
    )
    assert late["ok"] is True
    assert page.evaluate("() => window.__surfaces.found.customer.options") == [
        {"value": "mü", "label": "mü"}
    ]
    _close(page)


def test_a_search_that_is_not_answered_in_time_times_out(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__surfaces.searchTimeout = 200 }")
    _hold(page)
    _open_form(page, _SEARCH_FORM, "{ onSearch: () => new Promise(() => {}) }")
    page.evaluate("() => window.__surfaces.search('customer', 'mü')")
    page.wait_for_function("() => window.__surfaces.found.customer.timedOut === true")
    assert [m for m in _log(page) if m["action"] == "surfaceSearchResult"] == []
    _close(page)


def test_a_search_result_that_is_too_big_is_cut_to_fifty_options(page: Page) -> None:
    open_page(page)
    _hold(page)
    _open_form(
        page,
        _SEARCH_FORM,
        "{ onSearch: () => Array.from({ length: 60 }, (_, k) => ({ value: `v${k}`, label: `Option ${k}` })) }",
    )
    page.evaluate("() => window.__surfaces.search('customer', 'o')")
    page.wait_for_function("() => window.__surfaces.found.customer?.options !== null")
    assert len(page.evaluate("() => window.__surfaces.found.customer.options")) == 50
    _close(page)


def test_a_search_field_with_a_page_source_is_refused_by_the_app_on_other_types(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        "() => window.native.showForm({ fields: [{ id: 'a', type: 'text', source: 'page' }] })"
    )
    assert res["error"] == "invalid"  # the Pydantic model of the harness
    assert page.evaluate("() => window.__surfaces.open") is None


def test_live_fields_and_page_search_are_unavailable_in_apps_without_them(page: Page) -> None:
    for path, option in (
        ("/?oldApp", "onChange: () => {}"),
        ("/?features=liveSurfaces", "onSearch: () => []"),
    ):
        open_page(page, path)
        definition = (
            "{ fields: [{ id: 'a', type: 'text' }] }"
            if option.startswith("onChange")
            else "{ fields: [{ id: 'c', type: 'search', source: 'page' }] }"
        )
        res = page.evaluate(f"() => window.native.showForm({definition}, {{ {option} }})")
        assert res == {"ok": False, "error": "unavailable"}
        assert _log(page) == []
    open_page(page, "/?browser")
    assert page.evaluate("() => window.native.updateSurface({ id: 'f', title: 'x' })") == {
        "ok": False,
        "error": "unavailable",
    }
