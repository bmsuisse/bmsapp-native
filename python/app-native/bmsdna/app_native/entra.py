"""Sign-in with the Entra ID token of the app.

The user signs in **once in the app** (Microsoft Entra ID). The app then sends
the ID token as `Authorization: Bearer <JWT>` with every native call to your
backend, and attaches it to `fetch`/XHR calls of your web page. This module
turns that into an `auth_dependency` for the routers:

    verifier = EntraTokenVerifier.from_env()   # ENTRA_TENANT_ID, ENTRA_AUDIENCE
    auth = create_entra_auth_dependency(
        verifier,
        session=SignedSessionCookie(secret=os.environ["SESSION_SECRET"]),
    )
    app.include_router(create_widget_feed_router(get_widgets=..., auth_dependency=auth))

What is checked (an OIDC v2.0 ID token, not an access token of an API):

- the signature with the keys from Microsoft (JWKS, cached),
- `iss` = `https://login.microsoftonline.com/<tenant>/v2.0`, `tid` = tenant,
- `aud` = the client ID of the app registration of the iOS app,
- `exp`/`nbf` with a small tolerance,
- `oid` and `email` or `preferred_username` are present.

What the user may do in your web app stays your business (roles, groups,
your own user table, see `resolve_user`): the token only proves who it is.

A valid token is also exchanged for a short-lived session cookie, because the
browser cannot attach the token to navigation, `<img>`, downloads,
`EventSource` and `WebSocket`. Details: `docs/entra-token-guide.md`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.request
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPMessage
from typing import IO, Any, Literal, Protocol

import jwt
from fastapi import HTTPException, Response
from fastapi.requests import HTTPConnection

logger = logging.getLogger("bmsdna.app_native.entra")

#: Where Microsoft publishes the signing keys of a tenant.
JWKS_URL = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
#: `iss` of the v2.0 ID tokens of a tenant.
ISSUER = "https://login.microsoftonline.com/{tenant}/v2.0"

_TENANT_ID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
#: A real ID token is about 1–3 KB. Anything far beyond is not worth parsing.
_MAX_TOKEN_LENGTH = 16 * 1024
_MAX_JWKS_BYTES = 1_000_000
_COOKIE_AUDIENCE = "bmsdna-app-native-session"
#: Clock differences between replicas: a cookie issued by one may be read by another.
_COOKIE_LEEWAY = 30
#: While no key is cached, try again after this long instead of waiting a whole minute.
_EMPTY_RETRY_SECONDS = 5.0


class EntraTokenError(Exception):
    """The token is not acceptable. `reason` is for logs, never for the client."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EntraKeysUnavailableError(EntraTokenError):
    """The signing keys could not be loaded and none are cached. This is the
    server's problem, not the token's: answer 503, not 401."""

    def __init__(self) -> None:
        super().__init__("signing_keys_unavailable")


@dataclass(frozen=True)
class EntraUser:
    """The signed-in user as the token says."""

    #: Object ID of the user in the directory. Stable, so use it as the key
    #: to look up a user. An email address can change.
    oid: str
    #: `email`, otherwise `preferred_username` (the sign-in name, usually the
    #: email address). Compare it without regard to case.
    email: str
    #: Directory (tenant) ID, always the one the verifier is configured for.
    tenant_id: str
    #: Display name, if the token has one.
    name: str | None = None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


# --- Signing keys ------------------------------------------------------------

#: Returns the JWKS document (`{"keys": [...]}`). Replaceable for tests.
JwksFetcher = Callable[[], Awaitable[Mapping[str, Any]]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Microsoft's key endpoint does not redirect. urllib would follow a redirect
    to plain http or ftp; refuse them all."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _download_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "bmsdna-app-native"}
    )
    with _opener.open(request, timeout=5) as response:  # https only, see `_fetcher`
        data = json.loads(response.read(_MAX_JWKS_BYTES))
    if not isinstance(data, dict):
        raise ValueError("The JWKS document is not an object")
    return data


def _fetcher(url: str) -> JwksFetcher:
    if not url.startswith("https://"):
        raise ValueError("The JWKS URL must be https")

    async def fetch() -> Mapping[str, Any]:
        # urllib blocks: keep it off the event loop.
        return await asyncio.to_thread(_download_json, url)

    return fetch


def _parse_keys(document: Mapping[str, Any]) -> dict[str, jwt.PyJWK]:
    keys = document.get("keys")
    if not isinstance(keys, list):
        raise ValueError("The JWKS document has no `keys` list")
    usable = {
        key.key_id: key for key in jwt.PyJWKSet(keys).keys if key.key_id and key.key_type == "RSA"
    }
    if not usable:
        raise ValueError("The JWKS document has no usable RSA key")
    return usable


class _SigningKeys:
    """The keys of the tenant: cached, and reloaded at most once per
    `min_refresh` seconds, by one shared task.

    - A key that is cached is returned at once, also after it went stale: the
      reload then runs in the background, so a slow or unreachable Microsoft
      never holds up requests that could be answered.
    - Only a `kid` that is not cached (a key rollover, or nothing loaded yet)
      waits for the reload, for at most `timeout` seconds. The caller being
      cancelled does not cancel the reload.
    - Without the limit, anyone could make the backend call Microsoft on every
      request by sending tokens with made-up `kid`s.
    """

    def __init__(
        self,
        fetch: JwksFetcher,
        *,
        ttl: float,
        min_refresh: float,
        timeout: float,
        clock: Callable[[], float],
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._min_refresh = min_refresh
        self._timeout = timeout
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self._refresh: asyncio.Task[None] | None = None

    def _is_stale(self) -> bool:
        return self._fetched_at is None or self._clock() - self._fetched_at >= self._ttl

    def _start_refresh(self) -> asyncio.Task[None] | None:
        """The running reload, a new one, or `None` if one was tried too recently."""
        if self._refresh is not None and not self._refresh.done():
            return self._refresh
        now = self._clock()
        wait = self._min_refresh if self._keys else min(self._min_refresh, _EMPTY_RETRY_SECONDS)
        if self._last_attempt is not None and now - self._last_attempt < wait:
            return None
        self._last_attempt = now
        self._refresh = asyncio.get_running_loop().create_task(self._reload(now))
        return self._refresh

    async def _reload(self, started: float) -> None:
        try:
            async with asyncio.timeout(self._timeout):
                keys = _parse_keys(await self._fetch())
        except Exception:  # network, timeout, JSON, content: keep what we have
            logger.warning("Could not load the Entra signing keys", exc_info=True)
            return
        self._keys = keys
        self._fetched_at = started

    async def get(self, kid: str) -> jwt.PyJWK:
        key = self._keys.get(kid)
        if key is not None:
            if self._is_stale():
                self._start_refresh()  # in the background: this call does not wait
            return key
        task = self._start_refresh()
        if task is not None:
            await asyncio.shield(task)
        key = self._keys.get(kid)
        if key is not None:
            return key
        if not self._keys:
            raise EntraKeysUnavailableError
        raise EntraTokenError("unknown_kid")


# --- Token ------------------------------------------------------------------

_REASONS: tuple[tuple[type[Exception], str], ...] = (
    (jwt.ExpiredSignatureError, "expired"),
    (jwt.ImmatureSignatureError, "not_yet_valid"),
    (jwt.InvalidAudienceError, "audience"),
    (jwt.InvalidIssuerError, "issuer"),
    (jwt.MissingRequiredClaimError, "missing_claim"),
    (jwt.InvalidSignatureError, "signature"),
)


def _reason(error: jwt.PyJWTError) -> str:
    return next((reason for kind, reason in _REASONS if isinstance(error, kind)), "invalid")


class EntraTokenVerifier:
    """Checks the Entra ID token of the app and says who the user is.

    Nothing is hard-wired: the tenant and the audience (the client ID of the
    iOS app's registration) are parameters.

    - `tenant_id`: directory (tenant) ID, a GUID. `common`, `organizations`
      and `consumers` are refused: they would accept tokens of any tenant.
    - `audience`: the accepted `aud`, one client ID or several.
    - `leeway`: seconds of tolerance for `exp`, `nbf` and `iat`.
    - `jwks_cache_seconds`: how long Microsoft's signing keys are kept.
    - `jwks_min_refresh_seconds`: at most one reload per this time, whatever
      the reason (expired cache or unknown `kid`). Until a first load worked,
      a failed one is retried after 5 seconds.
    - `jwks_timeout_seconds`: the whole reload gives up after this long.
    - `fetch_jwks` and `clock` replace the download and the time source, for
      tests.

    Cached keys are used until a reload succeeds, however old they are: a
    Microsoft outage does not stop your sign-in.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        audience: str | Sequence[str],
        leeway: float = 60.0,
        jwks_cache_seconds: float = 3600.0,
        jwks_min_refresh_seconds: float = 60.0,
        jwks_timeout_seconds: float = 10.0,
        fetch_jwks: JwksFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not _TENANT_ID.fullmatch(tenant_id):
            raise ValueError(
                "tenant_id must be the directory (tenant) ID, a GUID. "
                "'common', 'organizations' and 'consumers' are not accepted."
            )
        audiences = [audience] if isinstance(audience, str) else list(audience)
        if not audiences or not all(a.strip() for a in audiences):
            raise ValueError("audience must name at least one client ID")
        # Entra writes the tenant ID in lower case, in `iss` and in `tid`.
        tenant_id = tenant_id.lower()
        self._tenant_id = tenant_id
        self._audiences = audiences
        self._leeway = leeway
        self._issuer = ISSUER.format(tenant=tenant_id)
        self._keys = _SigningKeys(
            fetch_jwks or _fetcher(JWKS_URL.format(tenant=tenant_id)),
            ttl=jwks_cache_seconds,
            min_refresh=jwks_min_refresh_seconds,
            timeout=jwks_timeout_seconds,
            clock=clock,
        )

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, **options: Any
    ) -> EntraTokenVerifier:
        """From `ENTRA_TENANT_ID` and `ENTRA_AUDIENCE` (several client IDs
        separated by commas). `options` are passed on to the constructor."""
        env = os.environ if environ is None else environ
        tenant_id = env.get("ENTRA_TENANT_ID", "").strip()
        audience = [a.strip() for a in env.get("ENTRA_AUDIENCE", "").split(",") if a.strip()]
        if not tenant_id or not audience:
            raise RuntimeError(
                "Entra sign-in is not configured: ENTRA_TENANT_ID and ENTRA_AUDIENCE "
                "must be set (see README)."
            )
        return cls(tenant_id=tenant_id, audience=audience, **options)

    @property
    def issuer(self) -> str:
        return self._issuer

    @property
    def tenant_id(self) -> str:
        """The configured directory (tenant) ID, in lower case."""
        return self._tenant_id

    async def verify(self, token: str) -> EntraUser:
        """The user of a valid token. Raises `EntraTokenError` for anything
        else, `EntraKeysUnavailableError` if Microsoft's keys cannot be had."""
        if not token or len(token) > _MAX_TOKEN_LENGTH:
            raise EntraTokenError("malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise EntraTokenError("malformed") from error
        # Only what Entra signs with. Rejecting everything else up front also
        # shuts out `none` and the HS256-with-the-public-key trick.
        if header.get("alg") != "RS256":
            raise EntraTokenError("algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise EntraTokenError("no_kid")

        key = await self._keys.get(kid)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as error:
            raise EntraTokenError(_reason(error)) from error
        # `scp` is in access tokens for an API, never in an ID token.
        if "scp" in claims:
            raise EntraTokenError("access_token")
        return self._user(claims)

    def _user(self, claims: Mapping[str, Any]) -> EntraUser:
        tid = _text(claims.get("tid"))
        if tid is None or tid.lower() != self._tenant_id:
            raise EntraTokenError("tenant")
        oid = _text(claims.get("oid"))
        if oid is None:
            raise EntraTokenError("missing_oid")
        email = _text(claims.get("email")) or _text(claims.get("preferred_username"))
        if email is None:
            raise EntraTokenError("missing_email")
        return EntraUser(
            oid=oid, email=email, tenant_id=self._tenant_id, name=_text(claims.get("name"))
        )


def bearer_token(connection: HTTPConnection) -> str | None:
    """The token of an `Authorization: Bearer <token>` header. `None` if there
    is no such header (or another scheme such as `Basic`), `""` if the header
    is there but empty. Works for requests and WebSocket handshakes."""
    header = connection.headers.get("authorization")
    if not header:
        return None
    parts = header.split(None, 1)  # any white space, not only a blank
    if not parts or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() if len(parts) > 1 else ""


# --- Session cookie -----------------------------------------------------------


class SessionCookie(Protocol):
    """What the cookie exchange needs from a session cookie.

    `SignedSessionCookie` is the ready-made one. A backend that already has
    its own session cookie implements this instead: `issue` sets its cookie
    for a verified user, `read` returns the user of a valid cookie (or `None`,
    also fine if your own dependency handles cookie-only requests, see
    `docs/entra-token-guide.md`). A user `read` returns must carry the
    `tenant_id` of the verifier, otherwise it is not accepted.
    """

    def issue(self, response: Response, user: EntraUser) -> None: ...

    def read(self, connection: HTTPConnection) -> EntraUser | None: ...


class SignedSessionCookie:
    """A stateless session cookie: the user, signed (HS256) with your secret
    and valid for `max_age` seconds. Nothing is stored on the server.

    The cookie is `HttpOnly`, `Secure` and `SameSite=Lax` (or `Strict`), has
    `Path=/` and **no `Domain`**: it belongs to the host of your backend only.
    The app deletes the session cookies of exactly these hosts when the user
    signs out or another user signs in, and it cannot reach one that is set
    for a parent domain.

    - `secret`: at least 32 bytes, random, kept like any other secret. Changing
      it signs everybody out; the app then exchanges its token again, which the
      user does not notice.
    - `max_age`: lifetime in seconds, default 8 hours. It is renewed with every
      call that carries a valid token. Once Entra stops accepting the user
      (password change, revoked access, ...) no token reaches you any more, and
      the cookie ends within `max_age` plus the rest of the last token (up to an
      hour). There is no revocation on the server: the cookie is stateless, so
      let `resolve_user` check whether the account is still allowed.
    - `secure`: only switch it off for local development over plain http.
    - `name`: `__Host-bms_session` is stricter: browsers then accept the cookie
      only with `Secure`, `Path=/` and no `Domain`, so a sibling subdomain cannot
      plant a cookie of the same name. It needs `secure=True`.
    - Use another `secret` for every environment (staging, production).
    """

    def __init__(
        self,
        *,
        secret: str | bytes,
        name: str = "bms_session",
        max_age: int = 8 * 3600,
        secure: bool = True,
        same_site: Literal["lax", "strict"] = "lax",
    ) -> None:
        raw = secret.encode() if isinstance(secret, str) else secret
        if len(raw) < 32:
            raise ValueError("secret must be at least 32 bytes")
        if max_age <= 0:
            raise ValueError("max_age must be positive")
        if name.startswith("__Host-") and not secure:
            raise ValueError("a __Host- cookie must be Secure")
        self._secret = raw
        self.name = name
        self.max_age = max_age
        self.secure = secure
        self.same_site = same_site

    def issue(self, response: Response, user: EntraUser) -> None:
        now = int(time.time())
        claims: dict[str, Any] = {
            "aud": _COOKIE_AUDIENCE,
            "sub": user.oid,
            "email": user.email,
            "tid": user.tenant_id,
            "iat": now,
            "exp": now + self.max_age,
        }
        if user.name:
            claims["name"] = user.name
        response.set_cookie(
            key=self.name,
            value=jwt.encode(claims, self._secret, algorithm="HS256"),
            max_age=self.max_age,
            path="/",
            secure=self.secure,
            httponly=True,
            samesite=self.same_site,
        )

    def read(self, connection: HTTPConnection) -> EntraUser | None:
        raw = connection.cookies.get(self.name)
        if not raw:
            return None
        try:
            claims = jwt.decode(
                raw,
                self._secret,
                algorithms=["HS256"],
                audience=_COOKIE_AUDIENCE,
                leeway=_COOKIE_LEEWAY,
                options={"require": ["exp", "sub", "aud"]},
            )
        except jwt.PyJWTError:
            return None
        oid, email, tid = (
            _text(claims.get("sub")),
            _text(claims.get("email")),
            _text(claims.get("tid")),
        )
        if not (oid and email and tid):
            return None
        return EntraUser(oid=oid, email=email, tenant_id=tid, name=_text(claims.get("name")))

    def clear(self, response: Response) -> None:
        """Deletes the cookie, for a sign-out route."""
        response.delete_cookie(
            key=self.name,
            path="/",
            secure=self.secure,
            httponly=True,
            samesite=self.same_site,
        )


# --- Dependency -------------------------------------------------------------

#: Maps the verified identity to your own user (or `None` if there is none).
UserResolver = Callable[[EntraUser], Awaitable[Any | None]]

_STATE_KEY = "bmsdna_entra_issue_cookie"


def copy_session_cookie(connection: HTTPConnection, response: Response) -> None:
    """Sets the session cookie on `response`, if the dependency decided on one.

    The dependency sets the cookie through the response FastAPI builds from your
    return value (a dict, a model, `None`). A route that returns a `Response`
    itself (`JSONResponse`, `RedirectResponse`, `FileResponse`, a stream) loses
    those headers silently: call this on your response. A WebSocket handshake
    cannot set a cookie at all.
    """
    issue = getattr(connection.state, _STATE_KEY, None)
    if issue is not None:
        issue(response)


def create_entra_auth_dependency(
    verifier: EntraTokenVerifier,
    *,
    session: SessionCookie | None = None,
    resolve_user: UserResolver | None = None,
) -> Callable[..., Awaitable[Any]]:
    """Builds the `auth_dependency` for the routers (also usable as a
    `Depends(...)` of your own routes and of WebSocket routes).

    - `Authorization: Bearer <token>` has priority: it must be valid, otherwise
      the answer is **401** (not 403 and no redirect: the app then fetches a
      renewed token and repeats the call once). Even a valid cookie does not
      rescue an invalid token. Another scheme (`Basic`, `Negotiate`) does not
      count as a token.
    - Without a token, the session cookie (`session`) is accepted. Without
      `session`, or without a valid cookie, the answer is 401.
    - A valid token also sets the session cookie: a new one with every
      such call, so a cookie of another user is replaced. Without `session`
      no cookie is set. It only reaches the client on routes whose return value
      FastAPI turns into the response; see `copy_session_cookie` for the others.
      A cookie of another tenant than the verifier's is not accepted.
    - `resolve_user` maps the identity to your own user, for the token and for
      the cookie alike (a user you removed is out at once). If it returns
      `None`, the answer is **403**: the token is genuine, but this user is
      not allowed in. What the dependency returns arrives as `context.user`;
      without `resolve_user` that is the `EntraUser`.

    Answers **503** if Microsoft's signing keys cannot be loaded at all.
    """

    async def resolve(identity: EntraUser) -> Any:
        if resolve_user is None:
            return identity
        user = await resolve_user(identity)
        if user is None:
            raise HTTPException(status_code=403, detail="Not allowed")
        return user

    async def entra_auth(connection: HTTPConnection, response: Response) -> Any:
        token = bearer_token(connection)
        if token is not None:
            try:
                verified = await verifier.verify(token)
            except EntraKeysUnavailableError as error:
                logger.warning("Token not checked: %s", error.reason)
                raise HTTPException(
                    status_code=503,
                    detail="Sign-in is temporarily unavailable",
                    headers={"Retry-After": "30"},
                ) from error
            except EntraTokenError as error:
                logger.debug("Token rejected: %s", error.reason)
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token",
                    headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                ) from error
            user = await resolve(verified)
            if session is not None:
                session.issue(response, verified)
                setattr(
                    connection.state,
                    _STATE_KEY,
                    lambda target: session.issue(target, verified),
                )
            return user

        identity = session.read(connection) if session is not None else None
        # A cookie of another tenant (another environment sharing the secret) is no cookie.
        if identity is not None and identity.tenant_id.lower() != verifier.tenant_id:
            identity = None
        if identity is None:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await resolve(identity)

    return entra_auth
