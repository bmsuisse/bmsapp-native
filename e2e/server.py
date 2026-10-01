"""Test harness: emulates the app side so the built npm package can run in a
real browser against the Python models.

- `GET  /`            Test page (page/index.html). It sets up
                      `window.BMSNative` like the app does, except that every
                      message goes to `POST /native/<action>` here. With
                      `?browser=1` without `BMSNative`, i.e. like a regular
                      browser.
- `GET  /pkg/...`     built `@bmsuisse/app-native` (packages/app-native/dist).
- `GET  /api/widgets` Widget feed from `create_widget_feed_router`, filled with
                      contract-fixtures/widgets.json.
- `POST /native/<action>` answers the bridge calls. Formats that have a
                      Pydantic model (widgets, Live Activities) are validated
                      with it — a stand-in for the app, which discards invalid
                      entries. All messages end up in `LOG`.

Sign-in with the Entra token, as a backend built with `bmsdna-app-native`
does it. A throw-away RSA key stands in for Microsoft, no real tenant is
involved:

- `POST /native/getAccessToken` is the app: it hands out a token of the current
                      "app user" (`STATE["user"]`).
- `GET  /api/me`      protected with `create_entra_auth_dependency`; the same
                      for `GET /api/avatar.svg`, which a page can only load with a cookie
                      (`<img>` sets no `Authorization` header).
- `WS   /ws`          the token arrives in the first message (what a browser
                      can do).
- `WS   /ws-header`   the token arrives in the handshake header (what the app does).

The real app (Swift) does not run here; the harness checks that the web app
and backend packages speak the same format.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from bmsdna.app_native import (
    EntraTokenError,
    EntraTokenVerifier,
    EntraUser,
    LiveActivityState,
    SignedSessionCookie,
    Widget,
    create_entra_auth_dependency,
    create_widget_feed_router,
    insecure_no_auth,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request, Response, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jwt.algorithms import RSAAlgorithm
from pydantic import TypeAdapter, ValidationError

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "packages" / "app-native" / "dist"
FIXTURES = ROOT / "contract-fixtures"

_widget = TypeAdapter(Widget)
_widgets = TypeAdapter(list[Widget])

LOG: list[dict[str, Any]] = []

# --- Entra: a stand-in for Microsoft ------------------------------------------

# Placeholders, not real IDs.
TENANT = "00000000-0000-4000-8000-0000000000aa"
CLIENT = "11111111-1111-4111-8111-1111111111bb"
ANNA = {"oid": "22222222-2222-4222-8222-2222222222cc", "email": "anna@example.com"}
BORIS = {"oid": "33333333-3333-4333-8333-3333333333dd", "email": "boris@example.com"}

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "e2e-key"

#: Who is signed in to the "app". Tests switch it; `DELETE /native-log` resets it.
STATE: dict[str, dict[str, str]] = {"user": ANNA}


async def _fetch_jwks() -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    return {"keys": [{**jwk, "kid": _KID, "use": "sig", "alg": "RS256"}]}


def mint_token(
    *, oid: str, email: str, expires_in: int = 3600, audience: str = CLIENT, **claims: Any
) -> str:
    """A token like Entra issues it, signed with the throw-away key."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": audience,
        "tid": TENANT,
        "oid": oid,
        "sub": "pairwise-id",
        "email": email,
        "name": email.split("@")[0].title(),
        "uti": uuid.uuid4().hex,  # every token differs, even within the same second
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
    }
    payload.update(claims)
    return jwt.encode(payload, _KEY, algorithm="RS256", headers={"kid": _KID})


VERIFIER = EntraTokenVerifier(tenant_id=TENANT, audience=CLIENT, fetch_jwks=_fetch_jwks)
AUTH = create_entra_auth_dependency(
    VERIFIER,
    # Secure is fine here: browsers treat http://127.0.0.1 as a secure origin.
    session=SignedSessionCookie(secret="e2e-secret-with-at-least-32-bytes!"),
)

# --- Bridge -------------------------------------------------------------------


async def _fixture_widgets(_context: object) -> list[Any]:
    return _widgets.validate_python(json.loads((FIXTURES / "widgets.json").read_text()))


def _valid(adapter: TypeAdapter[Any], value: Any) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


def _has_text(body: dict[str, Any], *keys: str) -> bool:
    return any(isinstance(body.get(key), str) and body[key].strip() for key in keys)


def _device_action(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """What the app answers: `invalid` for incomplete details, otherwise `ok`
    with a finished sentence."""
    valid = {
        "navigate": lambda: bool(
            body.get("destination")
            or _has_text(body, "address")
            or (body.get("latitude") is not None and body.get("longitude") is not None)
        ),
        "addReminder": lambda: _has_text(body, "title"),
        "saveContact": lambda: _has_text(body, "givenName", "familyName", "organization"),
        "callPhone": lambda: _has_text(body, "number"),
    }[action]()
    if not valid:
        return {"ok": False, "error": "invalid", "message": "Ungültige Angaben."}
    return {"ok": True, "message": f"{action} ausgeführt."}


def _answer(action: str, body: dict[str, Any]) -> dict[str, Any]:
    if action == "setWidgets":
        items = body.get("widgets") or []
        accepted = sum(_valid(_widget, w) for w in items)
        return {"ok": True, "accepted": accepted, "rejected": len(items) - accepted}
    if action == "updateWidget":
        if _valid(_widget, body.get("widget")):
            return {"ok": True}
        return {"ok": False, "error": "invalid"}
    if action in ("startLiveActivity", "updateLiveActivity"):
        ok = bool(body.get("id")) and _valid(TypeAdapter(LiveActivityState), body.get("state"))
        return {"ok": True} if ok else {"ok": False, "error": "invalid"}
    if action == "getLiveActivities":
        ids = [m["id"] for m in LOG if m.get("action") == "startLiveActivity"]
        return {"ok": True, "ids": ids}
    if action == "getAccessToken":
        token = mint_token(**STATE["user"])
        exp = jwt.decode(token, options={"verify_signature": False})["exp"]
        return {"ok": True, "token": token, "expiresAt": exp}
    if action in ("navigate", "addReminder", "saveContact", "callPhone"):
        return _device_action(action, body)
    return {"ok": True}


def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_widget_feed_router(get_widgets=_fixture_widgets, auth_dependency=insecure_no_auth),
        prefix="/api",
    )

    @app.get("/api/me")
    async def me(user: EntraUser = Depends(AUTH)) -> dict[str, str | None]:
        return {"oid": user.oid, "email": user.email, "name": user.name}

    @app.get("/api/avatar.svg")
    async def avatar(user: EntraUser = Depends(AUTH)) -> Response:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>'
        return Response(svg, media_type="image/svg+xml")

    @app.websocket("/ws")
    async def ws_first_message(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            user = await VERIFIER.verify(await websocket.receive_text())
        except EntraTokenError:
            await websocket.close(code=1008)
            return
        await websocket.send_json({"email": user.email})
        await websocket.close()

    @app.websocket("/ws-header")
    async def ws_header(websocket: WebSocket, user: EntraUser = Depends(AUTH)) -> None:
        await websocket.accept()
        await websocket.send_json({"email": user.email})
        await websocket.close()

    @app.post("/native/{action}")
    async def native(action: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        LOG.append({**body, "action": action})
        return _answer(action, body)

    @app.get("/native-log")
    async def native_log() -> list[dict[str, Any]]:
        return LOG

    @app.delete("/native-log")
    async def clear_native_log() -> None:
        LOG.clear()
        STATE["user"] = ANNA

    @app.post("/test/app-user")
    async def set_app_user(request: Request) -> None:
        """Who is signed in to the emulated app from now on."""
        STATE["user"] = await request.json()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "page" / "index.html")

    app.mount("/pkg", StaticFiles(directory=DIST), name="pkg")
    return app
