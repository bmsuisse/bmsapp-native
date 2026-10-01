from playwright.sync_api import Page


def open_page(page: Page, path: str = "/") -> Page:
    """Opens the test page and waits until `window.native` is ready."""
    page.request.delete("/native-log")
    page.goto(path)
    page.wait_for_function("() => !!window.native")
    return page
