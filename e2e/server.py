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
                      Pydantic model (widgets, Live Activities, native forms and
                      content) are validated with it — a stand-in for the app,
                      which discards invalid entries. All messages end up in `LOG`.

Native forms and content (`showForm`, `showContent`): the page's fake bridge
(page/index.html) plays the native sheets, scripted by the test. What the
backend of a web app does for them is real here:

- `POST /api/documents`       `create_document_router`: the media of a form arrive
                      here as multipart, before the page gets the result. The
                      callback keeps the file under a reference (idempotent per
                      `upload_id`) and answers with an `id`, or none
                      (`STATE["reference"]`).
- `POST /api/widget-options`  `create_widget_options_router`: option lookups of
                      native forms (`form_id`, `context`).
- `POST /api/customers`       the web app's own endpoint that the page sends the
                      values and media references to; it resolves them with
                      `resolve_file_refs` and can answer a field error.
- `GET  /backend-log`         what the document and options routers received.

Contract 2026-11 (`scanDocument` options, `pickFiles`, `dictate`, `previewFile`,
back interception, resource tokens): `POST /native/<action>` checks the payload
the way the app does (`invalid`), written independently of the npm package. What
the app does with a valid one is played by the page's fake bridge. The files that
`previewFile` downloads are `GET /files/<name>` (`missing…` is a 404).

Sign-in with the Entra token, as a backend built with `bmsdna-app-native`
does it. A throw-away RSA key stands in for Microsoft, no real tenant is
involved:

- `POST /native/getAccessToken` is the app: it hands out a token of the current
                      "app user" (`STATE["user"]`). With a `resource` the token is for the
                      "other API" (`GET /api/other-api/me`, which takes only such tokens);
                      the user consents first (`consentRequired`, `interactive`).
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
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jwt
import rules
from bmsdna.app_native import (
    ActionField,
    ActionOption,
    ActionPage,
    EntraTokenError,
    EntraTokenVerifier,
    EntraUser,
    InMemoryUploadResults,
    LiveActivityState,
    NativeContent,
    NativeFileRef,
    NativeForm,
    NativeMenu,
    ReceivedDocument,
    SignedSessionCookie,
    SurfaceLimitError,
    Widget,
    WidgetOptionsRequest,
    WidgetRequestContext,
    check_document_context,
    create_document_router,
    create_entra_auth_dependency,
    create_widget_feed_router,
    create_widget_options_router,
    insecure_no_auth,
    resolve_file_refs,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jwt.algorithms import RSAAlgorithm
from pydantic import BaseModel, TypeAdapter, ValidationError

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

#: The "other API" that `getAccessToken({ resource })` is for (a placeholder ID).
OTHER_CLIENT = "44444444-4444-4444-8444-4444444444ee"
RESOURCE = f"api://{OTHER_CLIENT}/.default"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "e2e-key"

#: Who is signed in to the "app". Tests switch it; `DELETE /native-log` resets it.
STATE: dict[str, Any] = {
    "user": ANNA,
    "reference": "id",
    # Whether the document router remembers answers per `upload_id`.
    "dedupe": False,
    # `filename` -> how many uploads of it still fail with a 503.
    "upload_failures": {},
    # The resources configured for this web app in the app, and which of them the
    # user has already consented to.
    "resources": [RESOURCE],
    "consented": [],
}

#: What the document and options routers received, newest last.
BACKEND_LOG: dict[str, list[dict[str, Any]]] = {"uploads": [], "options": []}
#: The files of native forms by reference. `owner` is what the page's own endpoint
#: checks; a real backend takes it from its `auth_dependency` (`context.user`).
FILES: dict[str, dict[str, Any]] = {}
#: `upload_id` -> reference: the same upload twice must not create a second file.
UPLOAD_REFS: dict[str, str] = {}


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
OTHER_VERIFIER = EntraTokenVerifier(tenant_id=TENANT, audience=OTHER_CLIENT, fetch_jwks=_fetch_jwks)
OTHER_AUTH = create_entra_auth_dependency(OTHER_VERIFIER)
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


def _refusal(error: ValidationError) -> tuple[str, str]:
    """Like the app: a definition beyond a limit is `tooLarge`, anything else
    that does not parse is `invalid`; the message names the field path."""
    problems = error.errors()
    limits = [p for p in problems if isinstance(p.get("ctx", {}).get("error"), SurfaceLimitError)]
    problem = (limits or problems)[0]
    path = ".".join(str(part) for part in problem["loc"])
    message = f"{path}: {problem['msg']}" if path else problem["msg"]
    return ("tooLarge" if limits else "invalid"), message


def _surface(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """`showForm`/`showContent`: the app parses the definition first. What it
    does with a valid one is played by the page's fake bridge."""
    definition = {key: value for key, value in body.items() if key != "action"}
    model = NativeForm if action == "showForm" else NativeContent
    try:
        model.model_validate(definition)
    except ValidationError as error:
        code, message = _refusal(error)
        return {"ok": False, "error": code, "message": message}
    return {"ok": True}


def _scan(action: str, body: dict[str, Any]) -> dict[str, Any]:
    """`scanText`/`scanBarcode`: the app checks the options (`invalid`); the
    scanner itself is played by the page's fake bridge."""
    invalid = {"ok": False, "error": "invalid", "message": "Invalid scan options."}
    if action == "scanText":
        pattern = body.get("pattern")
        if pattern is not None and (not isinstance(pattern, str) or len(pattern) > 200):
            return invalid
        return {"ok": True}
    formats = body.get("formats")
    if "formats" in body and not (
        isinstance(formats, list) and all(isinstance(f, str) for f in formats)
    ):
        return invalid
    if body.get("multiple") is True and "max" in body:
        maximum = body["max"]
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 200:
            return invalid
    return {"ok": True}


# --- Contract 2026-11 ----------------------------------------------------------
# What the app checks before it does anything (`invalid`). Written independently of
# the npm package: the fixtures run against both.

_KIND = re.compile(r"^[a-z0-9_-]{1,32}$")
_SOURCES = ("files", "photos", "camera")


def _bad(message: str) -> dict[str, Any]:
    return {"ok": False, "error": "invalid", "message": message}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _document_options_problem(body: dict[str, Any]) -> str | None:
    """`context`, `kind`, `mode` and `multiple` as `scanDocument` and `pickFiles` take them."""
    context = body.get("context")
    if context is not None:
        if not isinstance(context, dict):
            return "context has to be a JSON object"
        try:
            check_document_context(context)
        except ValueError as error:
            return str(error)
    kind = body.get("kind")
    if "kind" in body and not (isinstance(kind, str) and _KIND.fullmatch(kind)):
        return "kind has to match [a-z0-9_-]{1,32}"
    if body.get("mode", "upload") not in ("upload", "return"):
        return "mode has to be upload or return"
    if "multiple" in body and not isinstance(body["multiple"], bool):
        return "multiple has to be a boolean"
    return None


def _scan_document(body: dict[str, Any]) -> dict[str, Any]:
    problem = _document_options_problem(body)
    return _bad(problem) if problem else {"ok": True}


def _pick_files(body: dict[str, Any]) -> dict[str, Any]:
    sources = body.get("sources")
    if not isinstance(sources, list) or not sources or any(s not in _SOURCES for s in sources):
        return _bad("sources needs at least one of files, photos, camera")
    accept = body.get("accept")
    if "accept" in body and not (
        isinstance(accept, list) and all(isinstance(a, str) for a in accept)
    ):
        return _bad("accept has to be a list of strings")
    problem = _document_options_problem(body)
    return _bad(problem) if problem else {"ok": True}


def _dictate(body: dict[str, Any]) -> dict[str, Any]:
    locale = body.get("locale")
    if "locale" in body and not (isinstance(locale, str) and locale):
        return _bad("locale has to be a BCP-47 string")
    seconds = body.get("maxSeconds")
    if "maxSeconds" in body and not (
        isinstance(seconds, int | float) and not isinstance(seconds, bool) and 1 <= seconds <= 120
    ):
        return _bad("maxSeconds has to be 1 to 120")
    strings = body.get("contextualStrings")
    if "contextualStrings" in body and not (
        isinstance(strings, list)
        and len(strings) <= 50
        and all(isinstance(t, str) for t in strings)
    ):
        return _bad("contextualStrings has to be at most 50 strings")
    return {"ok": True}


def _preview_file(body: dict[str, Any], host: str | None) -> dict[str, Any]:
    url = body.get("url")
    if not isinstance(url, str) or not url:
        return _bad("url is required")
    if "filename" in body and not isinstance(body["filename"], str):
        return _bad("filename has to be a string")
    parts = urlsplit(url)
    if parts.scheme not in ("", "http", "https"):
        return _bad("url has to be on the web app's own origin")
    if parts.netloc and parts.netloc != host:
        return _bad("url has to be on the web app's own origin")
    return {"ok": True}


def _access_token(body: dict[str, Any]) -> dict[str, Any]:
    if "resource" not in body:
        token = mint_token(**STATE["user"])
        exp = jwt.decode(token, options={"verify_signature": False})["exp"]
        return {"ok": True, "token": token, "expiresAt": exp}
    resource = body["resource"]
    if not isinstance(resource, str) or not resource:
        return _bad("resource has to be an Entra scope")
    if "interactive" in body and not isinstance(body["interactive"], bool):
        return _bad("interactive has to be a boolean")
    if resource not in STATE["resources"]:
        return {"ok": False, "error": "forbidden"}
    if resource not in STATE["consented"]:
        if body.get("interactive") is not True:
            return {"ok": False, "error": "consentRequired"}
        STATE["consented"].append(resource)
    audience = resource.removeprefix("api://").removesuffix("/.default")
    token = mint_token(**STATE["user"], audience=audience)
    exp = jwt.decode(token, options={"verify_signature": False}, audience=audience)["exp"]
    return {"ok": True, "token": token, "expiresAt": exp, "resource": resource}


def _refuse(problem: str | None) -> dict[str, Any]:
    return {"ok": True} if problem is None else _bad(problem)


def _show_menu(body: dict[str, Any]) -> dict[str, Any]:
    problem = rules.menu_problem(body)
    if problem is None:
        menu = NativeMenu.model_validate(
            {k: v for k, v in body.items() if k not in ("anchor", "action")}
        )
        STATE["menu"] = rules.lazy_index(menu)
    return _refuse(problem)


def _surface_content(body: dict[str, Any]) -> str | None:
    """`updateSurface`: the new definition parts are checked like `showForm`/`showContent`."""
    if (problem := rules.update_surface_problem(body)) is not None:
        return problem
    try:
        if body.get("blocks"):
            NativeContent.model_validate({"blocks": body["blocks"], "actions": body.get("actions")})
        for field in body.get("fields") or []:
            ActionField.model_validate(field)
        for page in body.get("pages") or []:
            ActionPage.model_validate(page)
    except ValidationError as error:
        return _refusal(error)[1]
    return None


def _contract_b_answer(
    action: str, body: dict[str, Any], host: str | None, *, is_post: bool
) -> dict[str, Any] | None:
    """The actions of contract 2026-11b; `None` for any other action."""
    if action == "toast":
        # `post("toast")` is the old fire-and-forget form and takes whatever it took.
        return {"ok": True} if is_post else _refuse(rules.toast_problem(body))
    if action == "showMenu":
        return _show_menu(body)
    checks: dict[str, Callable[[], str | None]] = {
        "menuItems": lambda: rules.menu_items_problem(
            body, STATE.get("menu"), STATE.setdefault("menu_requests", {})
        ),
        "showAlert": lambda: rules.alert_problem(body),
        "updateSurface": lambda: _surface_content(body),
        "surfaceSearchResult": lambda: rules.search_answer_problem(body),
        "setKeyboardToolbar": lambda: rules.keyboard_toolbar_problem(body),
        "setKeyCommands": lambda: rules.key_commands_problem(body),
        "showDocument": lambda: rules.document_problem(body, host, update=False),
        "updateDocument": lambda: rules.document_problem(body, host, update=True),
        "showPicker": lambda: rules.picker_problem(body),
        "setChrome": lambda: rules.chrome_problem(body),
    }
    check = checks.get(action)
    return None if check is None else _refuse(check())


def _contract_answer(
    action: str, body: dict[str, Any], host: str | None, *, is_post: bool = False
) -> dict[str, Any] | None:
    """The actions of contracts 2026-11 and 2026-11b; `None` for any other action."""
    if (answer := _contract_b_answer(action, body, host, is_post=is_post)) is not None:
        return answer
    if action == "scanDocument":
        return _scan_document(body)
    if action == "pickFiles":
        return _pick_files(body)
    if action == "dictate":
        return _dictate(body)
    if action == "previewFile":
        return _preview_file(body, host)
    if action == "setBackInterception":
        return {"ok": True} if isinstance(body.get("enabled"), bool) else _bad("enabled")
    if action == "backResult":
        return {"ok": True} if isinstance(body.get("handled"), bool) else _bad("handled")
    if action == "getAccessToken":
        return _access_token(body)
    return None


def _answer(
    action: str, body: dict[str, Any], host: str | None = None, *, is_post: bool = False
) -> dict[str, Any]:
    answer = _contract_answer(action, body, host, is_post=is_post)
    if answer is not None:
        return answer
    if action in ("scanText", "scanBarcode"):
        return _scan(action, body)
    if action in ("showForm", "showContent"):
        return _surface(action, body)
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
    if action in ("navigate", "addReminder", "saveContact", "callPhone"):
        return _device_action(action, body)
    return {"ok": True}


async def _on_document(doc: ReceivedDocument, context: WidgetRequestContext) -> str | None:
    meta = doc.metadata
    failures = STATE["upload_failures"]
    if failures.get(doc.filename, 0) > 0:
        failures[doc.filename] -= 1
        BACKEND_LOG["uploads"].append(
            {"filename": doc.filename, "upload_id": meta.upload_id, "failed": True}
        )
        raise HTTPException(status_code=503, detail="Try again")
    BACKEND_LOG["uploads"].append(
        {
            "device_id": meta.device_id,
            "user_email": meta.user_email,
            "kind": meta.kind,
            "upload_id": meta.upload_id,
            "form_id": meta.form_id,
            "field_id": meta.field_id,
            "context": meta.context,
            "filename": doc.filename,
            "content_type": doc.content_type,
            "size": len(doc.data),
        }
    )
    if meta.upload_id is None:
        return None  # an older app: nothing to hand back
    # Idempotent per upload_id: the app repeats an upload after a failed attempt.
    reference = UPLOAD_REFS.get(meta.upload_id)
    if reference is None:
        reference = f"doc-{len(UPLOAD_REFS) + 1}" if STATE["reference"] == "id" else meta.upload_id
        UPLOAD_REFS[meta.upload_id] = reference
        FILES[reference] = {
            "owner": meta.device_id,
            "filename": doc.filename,
            "content_type": doc.content_type,
            "data": doc.data,
        }
    # Without an id the app hands the page the upload_id: the file is stored
    # under it, so the page's reference resolves either way.
    return reference if STATE["reference"] == "id" else None


async def _on_options(
    req: WidgetOptionsRequest, context: WidgetRequestContext
) -> list[ActionOption]:
    BACKEND_LOG["options"].append(req.model_dump())
    people = {"u-1": "Anna Muster", "u-2": "Beat Keller"}
    return [
        ActionOption(value=value, label=label)
        for value, label in people.items()
        if req.query.casefold() in label.casefold()
    ]


class _SwitchableResults(InMemoryUploadResults):
    """Remembers answers per `upload_id` only while `STATE["dedupe"]` is on."""

    async def get(self, upload_id: str, context: WidgetRequestContext) -> dict[str, Any] | None:
        return await super().get(upload_id, context) if STATE["dedupe"] else None

    async def set(
        self, upload_id: str, response: dict[str, Any], context: WidgetRequestContext
    ) -> None:
        if STATE["dedupe"]:
            await super().set(upload_id, response, context)


_RESULTS = _SwitchableResults()


def _reset_surface_backend() -> None:
    STATE["reference"] = "id"
    STATE["dedupe"] = False
    STATE["upload_failures"] = {}
    STATE["resources"] = [RESOURCE]
    STATE["consented"] = []
    STATE.pop("menu", None)
    STATE.pop("menu_requests", None)
    _RESULTS._entries.clear()
    for entries in BACKEND_LOG.values():
        entries.clear()
    FILES.clear()
    UPLOAD_REFS.clear()


class NewCustomer(BaseModel):
    """What the page sends to its own backend after a native form: the values
    and, for `photo`/`scan`/`signature` fields, the references."""

    device_id: str
    name: str
    email: str | None = None
    card: list[NativeFileRef] = []


def _test_endpoints(router: APIRouter) -> None:
    """Endpoints that tests use to set up the emulated app and backend (`/test/...`), and
    the files and the second API that the app downloads from and asks for tokens for."""

    @router.post("/test/document-reference")
    async def set_document_reference(request: Request) -> None:
        """`"id"`: the document router answers with an `id`. `"none"`: it answers
        `{"ok": true}` only and the app hands out the `upload_id`."""
        STATE["reference"] = (await request.json())["mode"]

    @router.post("/test/document-backend")
    async def set_document_backend(request: Request) -> None:
        """`{"dedupe": bool, "failures": {filename: count}}`: whether the document
        router remembers answers per `upload_id`, and which files fail with a 503
        that many times first (the app then retries once)."""
        body = await request.json()
        STATE["dedupe"] = bool(body.get("dedupe", False))
        STATE["upload_failures"] = dict(body.get("failures", {}))

    @router.post("/test/menu-expand")
    async def menu_expand(request: Request) -> None:
        """The emulated app asks the page for the children of a lazy item: remember which
        item the `requestId` belongs to, to check the answer (`menuItems`) against it."""
        body = await request.json()
        STATE.setdefault("menu_requests", {})[body["requestId"]] = body["itemId"]

    @router.post("/test/token-resources")
    async def set_token_resources(request: Request) -> None:
        """`{"resources": [...], "consented": [...]}`: what is configured for this web
        app in the emulated app, and what the user has already consented to."""
        body = await request.json()
        STATE["resources"] = list(body.get("resources", [RESOURCE]))
        STATE["consented"] = list(body.get("consented", []))

    @router.get("/files/{name}")
    async def files(name: str) -> Response:
        """Files that `previewFile` downloads: `missing.pdf` does not exist."""
        if name.startswith("missing"):
            raise HTTPException(status_code=404, detail="Not found")
        if name.endswith(".txt"):
            return Response("e2e", media_type="text/plain")
        return Response(b"%PDF-1.4 e2e", media_type="application/pdf")

    @router.get("/api/other-api/me")
    async def other_api_me(user: EntraUser = Depends(OTHER_AUTH)) -> dict[str, str | None]:
        """Another API of the same tenant: it takes tokens for `RESOURCE` only."""
        return {"email": user.email}


def _surface_backend() -> APIRouter:
    """What the backend of a web app adds for native forms: the document router
    the media go to, the option lookup, and the page's own endpoint."""
    router = APIRouter()
    router.include_router(
        create_document_router(
            on_document_received=_on_document,
            auth_dependency=insecure_no_auth,
            upload_results=_RESULTS,
        ),
        prefix="/api",
    )
    router.include_router(
        create_widget_options_router(
            on_options_requested=_on_options, auth_dependency=insecure_no_auth
        ),
        prefix="/api",
    )

    @router.post("/api/customers")
    async def create_customer(body: NewCustomer) -> dict[str, Any]:
        if body.email == "taken@example.com":
            raise HTTPException(
                status_code=422, detail={"fieldErrors": {"email": "Already registered"}}
            )

        async def lookup(ref: str) -> dict[str, Any] | None:
            stored = FILES.get(ref)
            return stored if stored and stored["owner"] == body.device_id else None

        files = await resolve_file_refs(body.card, lookup)
        return {
            "ok": True,
            "id": "c-1",
            "files": [
                {"name": f["filename"], "size": len(f["data"]), "contentType": f["content_type"]}
                for f in files
            ],
        }

    @router.get("/backend-log")
    async def backend_log() -> dict[str, list[dict[str, Any]]]:
        return BACKEND_LOG

    _test_endpoints(router)

    return router


def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_widget_feed_router(get_widgets=_fixture_widgets, auth_dependency=insecure_no_auth),
        prefix="/api",
    )
    app.include_router(_surface_backend())

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
        is_post = request.query_params.get("post") == "1"
        # A payload key `action` (the button of a toast) travels as "@action".
        payload = {k: v for k, v in body.items() if k not in ("@action", "action")}
        if "@action" in body:
            payload["action"] = body["@action"]
        return _answer(action, payload, request.headers.get("host"), is_post=is_post)

    @app.get("/native-log")
    async def native_log() -> list[dict[str, Any]]:
        return LOG

    @app.delete("/native-log")
    async def clear_native_log() -> None:
        LOG.clear()
        STATE["user"] = ANNA
        _reset_surface_backend()

    @app.post("/test/app-user")
    async def set_app_user(request: Request) -> None:
        """Who is signed in to the emulated app from now on."""
        STATE["user"] = await request.json()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "page" / "index.html")

    app.mount("/pkg", StaticFiles(directory=DIST), name="pkg")
    return app
