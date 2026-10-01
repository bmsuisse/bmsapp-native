"""Sign-in with the Entra token: the built npm package in a real browser against
`create_entra_auth_dependency` of the Python package.

See server.py: a throw-away key stands in for Microsoft, the harness stands in
for the app (`getAccessToken`). The page does what the app's injected script does
for it: it asks for the token and sends it as `Authorization: Bearer`.
"""

import json
import time

import pytest
import server
from helpers import open_page
from playwright.sync_api import Page
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

# Loads `/api/avatar.svg` with an <img>: the browser sets no Authorization header
# there, so this only works with a cookie.
IMAGE_LOADS = """() => new Promise((resolve) => {
  const img = new Image()
  img.onload = () => resolve(true)
  img.onerror = () => resolve(false)
  img.src = '/api/avatar.svg?' + Math.random()
})"""

# The call the app's script makes for the page: ask for a token, attach it.
CALL_WITH_TOKEN = """async (refresh) => {
  const session = await window.native.getAccessToken({ refresh })
  const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + session.token } })
  return { status: response.status, body: await response.json() }
}"""

CALL_WITH_COOKIE = (
    "() => fetch('/api/me').then(async (r) => ({ status: r.status, body: await r.json() }))"
)


def _session_cookie(page: Page) -> dict:
    cookies = [c for c in page.context.cookies() if c["name"] == "bms_session"]
    assert len(cookies) == 1
    return cookies[0]


def test_get_access_token_and_call_the_backend_with_it(page: Page) -> None:
    open_page(page)
    result = page.evaluate(
        """async () => {
          const session = await window.native.getAccessToken()
          const response = await fetch('/api/me', {
            headers: { Authorization: 'Bearer ' + session.token },
          })
          return {
            ok: session.ok,
            hasToken: typeof session.token === 'string' && session.token.split('.').length === 3,
            expiresAt: session.expiresAt,
            status: response.status,
            body: await response.json(),
          }
        }"""
    )

    assert result["ok"] is True
    assert result["hasToken"] is True
    # Seconds since 1970, not milliseconds.
    assert time.time() < result["expiresAt"] <= time.time() + 3700
    assert result["status"] == 200
    assert result["body"] == {
        "oid": server.ANNA["oid"],
        "email": "anna@example.com",
        "name": "Anna",
    }


def test_the_token_is_exchanged_for_a_cookie_the_page_cannot_read(page: Page) -> None:
    open_page(page)
    # No header possible, no cookie yet.
    assert page.evaluate(IMAGE_LOADS) is False

    assert page.evaluate(CALL_WITH_TOKEN, False)["status"] == 200

    cookie = _session_cookie(page)
    assert cookie["httpOnly"] is True
    assert cookie["secure"] is True
    assert cookie["sameSite"] == "Lax"
    assert cookie["path"] == "/"
    assert cookie["domain"] == "127.0.0.1"  # host-only: no leading dot, no parent domain
    assert 7 * 3600 < cookie["expires"] - time.time() <= 8 * 3600 + 60
    assert "bms_session" not in page.evaluate("() => document.cookie")

    # From now on the cookie is enough: images, links, downloads, fetch without header.
    assert page.evaluate(IMAGE_LOADS) is True
    assert page.evaluate(CALL_WITH_COOKIE) == {
        "status": 200,
        "body": {"oid": server.ANNA["oid"], "email": "anna@example.com", "name": "Anna"},
    }


def test_the_cookie_is_replaced_when_another_user_signs_in(page: Page) -> None:
    open_page(page)
    assert page.evaluate(CALL_WITH_TOKEN, False)["body"]["email"] == "anna@example.com"
    first = _session_cookie(page)["value"]

    # Another user signs in to the app; the page asks for a renewed token.
    page.request.post("/test/app-user", data=server.BORIS)
    assert page.evaluate(CALL_WITH_TOKEN, True)["body"]["email"] == "boris@example.com"

    assert _session_cookie(page)["value"] != first
    assert page.evaluate(CALL_WITH_COOKIE)["body"]["email"] == "boris@example.com"


@pytest.mark.parametrize(
    "claims",
    [{"expires_in": -600}, {"audience": "someone-else"}],
    ids=["expired", "foreign-audience"],
)
def test_an_invalid_token_is_401_and_sets_no_cookie(page: Page, claims: dict) -> None:
    open_page(page)
    token = server.mint_token(**server.ANNA, **claims)

    status = page.evaluate(
        """async (token) =>
          (await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } })).status""",
        token,
    )

    assert status == 401
    assert page.context.cookies() == []


def test_a_valid_cookie_does_not_rescue_an_invalid_token(page: Page) -> None:
    open_page(page)
    page.evaluate(CALL_WITH_TOKEN, False)
    expired = server.mint_token(**server.ANNA, expires_in=-600)

    status = page.evaluate(
        """async (token) =>
          (await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } })).status""",
        expired,
    )

    assert status == 401


def test_browser_without_app_has_no_token_and_no_access(page: Page) -> None:
    open_page(page, "/?browser=1")
    result = page.evaluate(
        """async () => ({
          token: await window.native.getAccessToken(),
          refreshed: await window.native.getAccessToken({ refresh: true }),
          status: (await fetch('/api/me')).status,
        })"""
    )

    unavailable = {"ok": False, "error": "unavailable"}
    assert result == {"token": unavailable, "refreshed": unavailable, "status": 401}


def test_websocket_takes_the_token_in_the_first_message(page: Page) -> None:
    """A browser cannot set a header on a WebSocket: the page sends the token as
    the first message, not in the URL."""
    open_page(page)
    connect_js = """async (invalid) => {
      const session = await window.native.getAccessToken()
      return await new Promise((resolve) => {
        const socket = new WebSocket(`ws://${location.host}/ws`)
        socket.onopen = () => socket.send(invalid ? 'garbage' : session.token)
        socket.onmessage = (event) => resolve({ message: JSON.parse(event.data) })
        socket.onclose = (event) => resolve({ closed: event.code })
      })
    }"""

    assert page.evaluate(connect_js, False) == {"message": {"email": "anna@example.com"}}
    assert page.evaluate(connect_js, True) == {"closed": 1008}


def test_websocket_handshake_with_the_bearer_header(base_url: str) -> None:
    """What the app does: the token goes into the header of the handshake."""
    url = base_url.replace("http", "ws", 1) + "/ws-header"
    token = server.mint_token(**server.ANNA)

    with connect(url, additional_headers={"Authorization": f"Bearer {token}"}) as socket:
        assert json.loads(socket.recv()) == {"email": "anna@example.com"}

    with pytest.raises(InvalidStatus) as refused:
        connect(url)
    assert refused.value.response.status_code in (401, 403)

    with pytest.raises(InvalidStatus):
        connect(url, additional_headers={"Authorization": "Bearer garbage"})
