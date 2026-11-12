"""The 2026-11b parts of `setChrome` with the built npm package in a real browser:
search field, segments, iPad sidebar, undo gestures. The navigation bar is played by
the page's fake bridge (`window.__chrome`); the real iOS app does not take part.
"""

from helpers import open_page
from playwright.sync_api import Page


def _listen(page: Page, *events: str) -> None:
    page.evaluate(
        """(events) => {
          window.__ev = []
          for (const name of events) window.native.on(name, (e) => window.__ev.push([name, e]))
        }""",
        list(events),
    )


def _events(page: Page) -> list:
    return page.evaluate("() => window.__ev")


def _chrome(page: Page, chrome: str) -> None:
    page.evaluate(f"() => window.native.setChrome({chrome})")
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length > 0)"
    )


# --- search -------------------------------------------------------------------------------------


def test_the_search_field_reports_typing_submit_and_cancel(page: Page) -> None:
    open_page(page)
    _listen(page, "search", "searchCancel")
    _chrome(
        page,
        """{ search: { id: 'offers', placeholder: 'Search offers',
          scopes: [{ id: 'all', label: 'All' }, { id: 'mine', label: 'Mine' }], scope: 'mine' } }""",
    )

    assert page.evaluate("() => window.__chrome.searchField().placeholder") == "Search offers"
    assert page.evaluate("() => window.__chrome.typeSearch('mül')") is True
    assert page.evaluate("() => window.__chrome.submitSearch('müller')") is True
    assert page.evaluate("() => window.__chrome.cancelSearch()") is True
    assert _events(page) == [
        [
            "search",
            {
                "id": "offers",
                "query": "mül",
                "scope": "mine",
                "submitted": False,
                "source": "typing",
            },
        ],
        [
            "search",
            {
                "id": "offers",
                "query": "müller",
                "scope": "mine",
                "submitted": True,
                "source": "submit",
            },
        ],
        ["searchCancel", {"id": "offers"}],
    ]


def test_the_scan_button_needs_barcode_and_the_camera(page: Page) -> None:
    open_page(page)
    _listen(page, "search")
    _chrome(page, "{ search: { id: 'articles', placeholder: 'Article', barcode: true } }")
    assert page.evaluate("() => window.__chrome.scanSearch('4006381333931')") is True
    assert _events(page) == [
        [
            "search",
            {
                "id": "articles",
                "query": "4006381333931",
                "scope": None,
                "submitted": True,
                "source": "barcode",
            },
        ]
    ]

    open_page(page)
    _chrome(page, "{ search: { id: 'articles', placeholder: 'Article' } }")
    assert page.evaluate("() => window.__chrome.scanSearch('x')") is False

    open_page(page, "/?capabilities=customChrome")
    _chrome(page, "{ search: { id: 'articles', placeholder: 'Article', barcode: true } }")
    assert page.evaluate("() => window.__chrome.scanSearch('x')") is False


def test_omitting_search_removes_the_field(page: Page) -> None:
    open_page(page)
    _chrome(page, "{ search: { id: 'o', placeholder: 'Search' } }")
    assert page.evaluate("() => window.__chrome.searchField()") is not None
    page.evaluate("() => window.native.setChrome({})")
    page.wait_for_function("() => window.__chrome.searchField() === null")


# --- segments ---------------------------------------------------------------------------------------


def test_segments_select_and_report(page: Page) -> None:
    open_page(page)
    _listen(page, "segmentSelect")
    _chrome(
        page,
        """{ segments: { id: 'view', selected: 'list',
          items: [{ id: 'list', label: 'List' }, { id: 'map', label: 'Map', badge: '3' }] } }""",
    )
    assert page.evaluate("() => window.__chrome.selectSegment('map')") is True
    assert page.evaluate("() => window.__chrome.segments().selected") == "map"
    assert page.evaluate("() => window.__chrome.selectSegment('nope')") is False
    assert _events(page) == [["segmentSelect", {"id": "view", "item": "map"}]]


# --- sidebar --------------------------------------------------------------------------------------------

_SIDEBAR = """{ sidebar: {
  title: 'Offers', search: { placeholder: 'Search offers' },
  sections: [{ title: 'Today', items: [
    { id: 'o1', label: 'Offer 4711', trailingActions: [{ id: 'archive', label: 'Archive' }] },
    { id: 'o2', label: 'Offer 4712' },
  ] }],
} }"""


def test_the_sidebar_exists_in_the_regular_size_class_only(page: Page) -> None:
    open_page(page)
    _listen(page, "sidebarSelect", "sidebarAction", "sidebarSearch")
    _chrome(page, _SIDEBAR)

    # iPhone: compact width. The page shows its own list.
    assert page.evaluate("() => window.__chrome.sidebar()") is None
    assert page.evaluate("() => window.__chrome.selectSidebar('o1')") is False

    page.evaluate(
        "() => window.__layout.set({ sizeClass: 'regular', orientation: 'landscape', width: 1180, height: 820 })"
    )
    assert page.evaluate("() => window.__chrome.sidebar().title") == "Offers"
    assert page.evaluate("() => window.__chrome.selectSidebar('o1')") is True
    assert page.evaluate("() => window.__chrome.swipeSidebar('o1', 'archive')") is True
    assert page.evaluate("() => window.__chrome.searchSidebar('4711')") is True
    assert _events(page) == [
        ["sidebarSelect", {"id": "o1"}],
        ["sidebarAction", {"itemId": "o1", "id": "archive"}],
        ["sidebarSearch", {"query": "4711"}],
    ]

    # Back to compact (Split View): the sidebar is hidden again.
    page.evaluate("() => window.__layout.set({ sizeClass: 'compact', width: 507 })")
    assert page.evaluate("() => window.__chrome.sidebar()") is None


def test_sending_the_sidebar_again_keeps_the_selection(page: Page) -> None:
    open_page(page)
    page.evaluate("() => window.__layout.set({ sizeClass: 'regular' })")
    _chrome(page, _SIDEBAR)
    page.evaluate("() => window.__chrome.selectSidebar('o2')")
    page.evaluate(
        """() => window.native.setChrome({ sidebar: { title: 'Offers (12)', sections: [
          { items: [{ id: 'o2', label: 'Offer 4712' }, { id: 'o3', label: 'Offer 4713' }] },
        ] } })"""
    )
    page.wait_for_function("() => window.__chrome.sidebar()?.title === 'Offers (12)'")
    assert page.evaluate("() => window.__chrome.state.sidebarSelected") == "o2"


# --- undo -------------------------------------------------------------------------------------------------


def test_undo_gestures_follow_can_undo_and_can_redo(page: Page) -> None:
    open_page(page)
    _listen(page, "undo")
    _chrome(page, "{ undo: { canUndo: true, canRedo: false, undoLabel: 'Delete line' } }")

    assert page.evaluate("() => window.__chrome.undoState().undoLabel") == "Delete line"
    assert page.evaluate("() => window.__chrome.undo('undo')") is True
    assert page.evaluate("() => window.__chrome.undo('redo')") is False
    page.evaluate("() => window.native.setChrome({})")  # omitted: disabled
    page.wait_for_function("() => window.__chrome.undoState() === null")
    assert page.evaluate("() => window.__chrome.undo('undo')") is False
    assert _events(page) == [["undo", {"action": "undo"}]]


# --- old apps and the browser ----------------------------------------------------------------------------------


def test_an_app_without_the_features_ignores_every_addition(page: Page) -> None:
    open_page(page, "/?oldApp")
    page.evaluate(
        """() => window.native.setChrome({
          title: { text: 'T' }, search: { id: 's', placeholder: 'p' },
          segments: { id: 'v', items: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], selected: 'a' },
          sidebar: { title: 'S', sections: [] }, undo: { canUndo: true, canRedo: true },
        })"""
    )
    page.wait_for_function(
        "() => fetch('/native-log').then((r) => r.json()).then((l) => l.length > 0)"
    )
    state = page.evaluate("() => window.__chrome.state")
    assert [state[k] for k in ("title", "search", "segments", "sidebar", "undo")] == [None] * 5
    flags = page.evaluate(
        """() => ['titleMenu', 'navSearch', 'segments', 'sidebar', 'undoGestures'].map((f) => window.native.hasFeature(f))"""
    )
    assert flags == [False] * 5


def test_setchrome_additions_do_nothing_in_the_browser(page: Page) -> None:
    open_page(page, "/?browser")
    page.evaluate(
        "() => window.native.setChrome({ search: { id: 's', placeholder: 'p' }, undo: { canUndo: true, canRedo: false } })"
    )
    assert page.request.get("/native-log").json() == []
