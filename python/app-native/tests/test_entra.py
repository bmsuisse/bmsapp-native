from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.error
from collections.abc import Awaitable, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import jwt
import pytest
from bmsdna.app_native import (
    EntraKeysUnavailableError,
    EntraTokenError,
    EntraTokenVerifier,
    EntraUser,
    SignedSessionCookie,
    bearer_token,
    copy_session_cookie,
    create_entra_auth_dependency,
)
from bmsdna.app_native.entra import _download_json, _fetcher
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import Depends, FastAPI, Request, Response, WebSocket
from fastapi.requests import HTTPConnection
from fastapi.responses import JSONResponse
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# Placeholders, not real IDs.
TENANT = "00000000-0000-4000-8000-0000000000aa"
CLIENT = "11111111-1111-4111-8111-1111111111bb"
OID = "22222222-2222-4222-8222-2222222222cc"
OTHER_OID = "33333333-3333-4333-8333-3333333333dd"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
SECRET = "test-secret-with-at-least-32-bytes!"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwk(private_key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    data = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    return {**data, "kid": kid, "use": "sig", "alg": "RS256"}


class Issuer:
    """Stands in for Entra: signs tokens and serves the JWKS, counting the loads."""

    def __init__(self) -> None:
        self.keys: dict[str, rsa.RSAPrivateKey] = {
            "kid-1": rsa.generate_private_key(public_exponent=65537, key_size=2048)
        }
        self.fetches = 0
        self.failing = False
        self.delay = 0.0

    def add_key(self, kid: str) -> rsa.RSAPrivateKey:
        self.keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return self.keys[kid]

    async def fetch(self) -> dict[str, Any]:
        self.fetches += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failing:
            raise OSError("Microsoft is down")
        return {"keys": [_jwk(key, kid) for kid, key in self.keys.items()]}

    def mint(
        self,
        *,
        key: rsa.RSAPrivateKey | None = None,
        kid: str | None = "kid-1",
        algorithm: str = "RS256",
        headers: dict[str, Any] | None = None,
        **claims: Any,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT,
            "tid": TENANT,
            "oid": OID,
            "sub": "pairwise-id",
            "email": "anna@example.com",
            "name": "Anna Muster",
            "iat": now,
            "nbf": now,
            "exp": now + 3600,
        }
        payload.update(claims)
        payload = {name: value for name, value in payload.items() if value is not None}
        header = ({"kid": kid} if kid is not None else {}) | (headers or {})
        return jwt.encode(payload, key or self.keys["kid-1"], algorithm=algorithm, headers=header)


async def settle() -> None:
    """Lets a reload that runs in the background finish (the fake fetch does not wait)."""
    for _ in range(10):
        await asyncio.sleep(0)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def _issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def issuer(_issuer: Issuer) -> Issuer:
    # RSA keys are slow to generate: keep the first, reset the rest.
    _issuer.keys = {"kid-1": _issuer.keys["kid-1"]}
    _issuer.fetches = 0
    _issuer.failing = False
    _issuer.delay = 0.0
    return _issuer


def make_verifier(issuer: Issuer, **options: Any) -> EntraTokenVerifier:
    return EntraTokenVerifier(tenant_id=TENANT, audience=CLIENT, fetch_jwks=issuer.fetch, **options)


async def reason(verifier: EntraTokenVerifier, token: str) -> str:
    with pytest.raises(EntraTokenError) as error:
        await verifier.verify(token)
    return error.value.reason


def connection(headers: dict[str, str]) -> HTTPConnection:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return HTTPConnection({"type": "http", "headers": raw})


def cookie_value(response: httpx.Response | Response, name: str = "bms_session") -> str:
    header = response.headers["set-cookie"]
    assert header.startswith(f"{name}=")
    return header.split(";", 1)[0].split("=", 1)[1]


USER = EntraUser(oid=OID, email="anna@example.com", tenant_id=TENANT, name="Anna Muster")


# --- Token -------------------------------------------------------------------


async def test_valid_token(issuer: Issuer) -> None:
    user = await make_verifier(issuer).verify(issuer.mint())

    assert user == USER


async def test_preferred_username_replaces_a_missing_email(issuer: Issuer) -> None:
    token = issuer.mint(email=None, preferred_username="anna@example.com")

    assert (await make_verifier(issuer).verify(token)).email == "anna@example.com"


async def test_email_wins_over_preferred_username(issuer: Issuer) -> None:
    token = issuer.mint(email="anna@example.com", preferred_username="other@example.com")

    assert (await make_verifier(issuer).verify(token)).email == "anna@example.com"


async def test_name_is_optional(issuer: Issuer) -> None:
    user = await make_verifier(issuer).verify(issuer.mint(name=None))

    assert user.name is None


async def test_several_audiences(issuer: Issuer) -> None:
    verifier = EntraTokenVerifier(
        tenant_id=TENANT, audience=["other-client", CLIENT], fetch_jwks=issuer.fetch
    )

    assert (await verifier.verify(issuer.mint())).oid == OID


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"aud": "someone-else"}, "audience"),
        ({"aud": None}, "missing_claim"),
        ({"iss": "https://login.microsoftonline.com/other/v2.0"}, "issuer"),
        ({"iss": f"https://sts.windows.net/{TENANT}/"}, "issuer"),
        ({"iss": None}, "missing_claim"),
        ({"tid": "99999999-9999-4999-8999-9999999999ee"}, "tenant"),
        ({"tid": None}, "tenant"),
        ({"exp": int(time.time()) - 600}, "expired"),
        ({"exp": None}, "missing_claim"),
        ({"nbf": int(time.time()) + 600}, "not_yet_valid"),
        ({"oid": None}, "missing_oid"),
        ({"oid": "  "}, "missing_oid"),
        ({"oid": 42}, "missing_oid"),
        ({"email": None, "preferred_username": None}, "missing_email"),
        ({"email": "", "preferred_username": ""}, "missing_email"),
    ],
)
async def test_token_is_rejected(issuer: Issuer, claims: dict[str, Any], expected: str) -> None:
    assert await reason(make_verifier(issuer), issuer.mint(**claims)) == expected


async def test_leeway_forgives_small_clock_differences(issuer: Issuer) -> None:
    verifier = make_verifier(issuer, leeway=60)
    now = int(time.time())

    assert (await verifier.verify(issuer.mint(exp=now - 30))).oid == OID
    assert (await verifier.verify(issuer.mint(nbf=now + 30))).oid == OID
    assert await reason(verifier, issuer.mint(exp=now - 120)) == "expired"
    assert await reason(verifier, issuer.mint(nbf=now + 120)) == "not_yet_valid"


async def test_tampered_payload_is_rejected(issuer: Issuer) -> None:
    header, payload, signature = issuer.mint().split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["email"] = "boss@example.com"
    forged = ".".join([header, _b64(json.dumps(claims).encode()), signature])

    assert await reason(make_verifier(issuer), forged) == "signature"


async def test_token_signed_with_another_key_is_rejected(issuer: Issuer) -> None:
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert await reason(make_verifier(issuer), issuer.mint(key=stranger)) == "signature"


async def test_algorithm_none_is_rejected(issuer: Issuer) -> None:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT,
        "tid": TENANT,
        "oid": OID,
        "email": "a@b.c",
        "exp": now + 60,
    }
    header = _b64(json.dumps({"alg": "none", "kid": "kid-1"}).encode())
    token = f"{header}.{_b64(json.dumps(claims).encode())}."

    assert await reason(make_verifier(issuer), token) == "algorithm"


async def test_hs256_signed_with_the_public_key_is_rejected(issuer: Issuer) -> None:
    # The classic confusion attack: sign with HS256, using the public key as secret.
    public_pem = (
        issuer.keys["kid-1"]
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT,
        "tid": TENANT,
        "oid": OID,
        "email": "a@b.c",
        "exp": now + 60,
    }
    header = _b64(json.dumps({"alg": "HS256", "kid": "kid-1"}).encode())
    body = f"{header}.{_b64(json.dumps(claims).encode())}"
    signature = hmac.new(public_pem, body.encode(), hashlib.sha256).digest()

    assert await reason(make_verifier(issuer), f"{body}.{_b64(signature)}") == "algorithm"


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "....", "x" * 20_000])
async def test_garbage_is_rejected(issuer: Issuer, token: str) -> None:
    assert await reason(make_verifier(issuer), token) == "malformed"


async def test_token_without_kid_is_rejected(issuer: Issuer) -> None:
    assert await reason(make_verifier(issuer), issuer.mint(kid=None)) == "no_kid"


async def test_token_with_an_unknown_kid_is_rejected(issuer: Issuer) -> None:
    assert await reason(make_verifier(issuer), issuer.mint(kid="nobody")) == "unknown_kid"


# --- Configuration -------------------------------------------------------------


@pytest.mark.parametrize(
    "tenant", ["common", "organizations", "consumers", "contoso.com", "", "1234"]
)
def test_tenant_must_be_a_directory_id(tenant: str) -> None:
    with pytest.raises(ValueError, match="tenant"):
        EntraTokenVerifier(tenant_id=tenant, audience=CLIENT)


@pytest.mark.parametrize("audience", [[], [""], ["  "], ""])
def test_audience_is_required(audience: str | list[str]) -> None:
    with pytest.raises(ValueError, match="audience"):
        EntraTokenVerifier(tenant_id=TENANT, audience=audience)


def test_from_env() -> None:
    verifier = EntraTokenVerifier.from_env(
        {"ENTRA_TENANT_ID": TENANT, "ENTRA_AUDIENCE": f" {CLIENT} , other "}
    )

    assert verifier.issuer == ISSUER


@pytest.mark.parametrize(
    "environ",
    [{}, {"ENTRA_TENANT_ID": TENANT}, {"ENTRA_AUDIENCE": CLIENT}, {"ENTRA_AUDIENCE": ","}],
)
def test_from_env_requires_both_values(environ: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="ENTRA_TENANT_ID and ENTRA_AUDIENCE"):
        EntraTokenVerifier.from_env(environ)


# --- Signing keys ------------------------------------------------------------


async def test_keys_are_loaded_once_and_cached(issuer: Issuer) -> None:
    verifier = make_verifier(issuer, clock=Clock())

    for _ in range(5):
        await verifier.verify(issuer.mint())

    assert issuer.fetches == 1


async def test_keys_are_reloaded_when_the_cache_runs_out(issuer: Issuer) -> None:
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_cache_seconds=3600)
    await verifier.verify(issuer.mint())

    clock.now += 3599
    await verifier.verify(issuer.mint())
    assert issuer.fetches == 1

    clock.now += 2
    await verifier.verify(issuer.mint())  # answered with the cached key, reload in the background
    await settle()
    assert issuer.fetches == 2


async def test_a_key_rollover_is_noticed_through_the_kid(issuer: Issuer) -> None:
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_min_refresh_seconds=60)
    await verifier.verify(issuer.mint())
    new_key = issuer.add_key("kid-2")
    token = issuer.mint(key=new_key, kid="kid-2")

    assert await reason(verifier, token) == "unknown_kid"  # too soon after the last load
    assert issuer.fetches == 1

    clock.now += 61
    assert (await verifier.verify(token)).oid == OID
    assert issuer.fetches == 2


async def test_made_up_kids_cannot_flood_microsoft(issuer: Issuer) -> None:
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_min_refresh_seconds=60)
    await verifier.verify(issuer.mint())

    for number in range(50):
        await reason(verifier, issuer.mint(kid=f"made-up-{number}"))
    assert issuer.fetches == 1

    clock.now += 61
    for number in range(50):
        await reason(verifier, issuer.mint(kid=f"made-up-again-{number}"))
    assert issuer.fetches == 2


async def test_parallel_requests_share_one_load(issuer: Issuer) -> None:
    issuer.delay = 0.02
    verifier = make_verifier(issuer, clock=Clock())

    users = await asyncio.gather(*(verifier.verify(issuer.mint()) for _ in range(20)))

    assert {user.oid for user in users} == {OID}
    assert issuer.fetches == 1


async def test_without_keys_the_server_is_at_fault_not_the_token(issuer: Issuer) -> None:
    issuer.failing = True
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_min_refresh_seconds=60)

    with pytest.raises(EntraKeysUnavailableError):
        await verifier.verify(issuer.mint())
    with pytest.raises(EntraKeysUnavailableError):
        await verifier.verify(issuer.mint())
    assert issuer.fetches == 1  # not hammering a broken endpoint

    issuer.failing = False
    clock.now += 61
    assert (await verifier.verify(issuer.mint())).oid == OID


async def test_cached_keys_keep_working_while_microsoft_is_down(issuer: Issuer) -> None:
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_cache_seconds=3600)
    await verifier.verify(issuer.mint())

    issuer.failing = True
    clock.now += 7200

    assert (await verifier.verify(issuer.mint())).oid == OID


async def test_unusable_keys_in_the_document_are_skipped() -> None:
    issuer = Issuer()
    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_jwk = json.loads(ECAlgorithm.to_jwk(ec_key.public_key()))

    async def fetch() -> dict[str, Any]:
        return {
            "keys": [
                {**ec_jwk, "kid": "ec"},
                _jwk(issuer.keys["kid-1"], "kid-1"),
                "garbage",
                {"kty": "RSA"},
            ]
        }

    verifier = EntraTokenVerifier(tenant_id=TENANT, audience=CLIENT, fetch_jwks=fetch)

    assert (await verifier.verify(issuer.mint())).oid == OID
    assert await reason(verifier, issuer.mint(kid="ec")) == "unknown_kid"


@pytest.mark.parametrize("document", [{}, {"keys": []}, {"keys": "x"}, {"keys": [{"kty": "oct"}]}])
async def test_a_broken_document_counts_as_no_keys(
    issuer: Issuer, document: dict[str, Any]
) -> None:
    async def fetch() -> dict[str, Any]:
        return document

    verifier = EntraTokenVerifier(tenant_id=TENANT, audience=CLIENT, fetch_jwks=fetch)

    with pytest.raises(EntraKeysUnavailableError):
        await verifier.verify(issuer.mint())


# --- bearer_token --------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, None),
        ({"Authorization": ""}, None),
        ({"Authorization": "Basic abc"}, None),
        ({"Authorization": "Bearer abc.def.ghi"}, "abc.def.ghi"),
        ({"Authorization": "bearer abc"}, "abc"),
        ({"Authorization": "BEARER   abc  "}, "abc"),
        ({"Authorization": "Bearer\tabc"}, "abc"),
        ({"Authorization": "Bearer"}, ""),
        ({"Authorization": "Bearer "}, ""),
    ],
)
def test_bearer_token(headers: dict[str, str], expected: str | None) -> None:
    assert bearer_token(connection(headers)) == expected


# --- Session cookie ------------------------------------------------------------


def test_cookie_round_trip() -> None:
    cookie = SignedSessionCookie(secret=SECRET)
    response = Response()
    cookie.issue(response, USER)

    read = cookie.read(connection({"Cookie": f"bms_session={cookie_value(response)}"}))

    assert read == USER


def test_cookie_without_a_name_round_trips() -> None:
    cookie = SignedSessionCookie(secret=SECRET)
    response = Response()
    cookie.issue(response, EntraUser(oid=OID, email="a@b.c", tenant_id=TENANT))

    read = cookie.read(connection({"Cookie": f"bms_session={cookie_value(response)}"}))

    assert read is not None
    assert read.name is None


def test_cookie_attributes() -> None:
    response = Response()
    SignedSessionCookie(secret=SECRET).issue(response, USER)

    attributes = {part.strip().lower() for part in response.headers["set-cookie"].split(";")}

    assert {"httponly", "secure", "samesite=lax", "path=/", "max-age=28800"} <= attributes
    # Host-only: with a Domain the app could not remove it when the user signs out.
    assert not any(part.startswith("domain") for part in attributes)


def test_cookie_options() -> None:
    response = Response()
    SignedSessionCookie(
        secret=SECRET, name="custom", max_age=60, secure=False, same_site="strict"
    ).issue(response, USER)

    header = response.headers["set-cookie"].lower()

    assert header.startswith("custom=")
    assert "max-age=60" in header
    assert "samesite=strict" in header
    assert "secure" not in header.replace("samesite", "")


def test_cookie_clear() -> None:
    response = Response()
    SignedSessionCookie(secret=SECRET).clear(response)

    header = response.headers["set-cookie"].lower()

    assert header.startswith('bms_session="";') or header.startswith("bms_session=;")
    assert "max-age=0" in header


@pytest.mark.parametrize("secret", ["", "short", b"x" * 31])
def test_cookie_secret_must_be_long(secret: str | bytes) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SignedSessionCookie(secret=secret)


def test_cookie_max_age_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_age"):
        SignedSessionCookie(secret=SECRET, max_age=0)


def _forge(secret: str | bytes = SECRET, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "aud": "bmsdna-app-native-session",
        "sub": OID,
        "email": "anna@example.com",
        "tid": TENANT,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm="HS256")


def test_a_cookie_that_checks_out_is_read() -> None:
    cookie = SignedSessionCookie(secret=SECRET)

    assert cookie.read(connection({"Cookie": f"bms_session={_forge()}"})) == EntraUser(
        oid=OID, email="anna@example.com", tenant_id=TENANT
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "garbage",
        _forge("another-secret-with-at-least-32-bytes"),
        _forge(exp=int(time.time()) - 120),
        _forge(exp=None),
        _forge(aud="another-audience"),
        _forge(aud=None),
        _forge(sub=None),
        _forge(email=None),
        _forge(tid=None),
    ],
)
def test_a_cookie_that_does_not_check_out_is_ignored(value: str) -> None:
    cookie = SignedSessionCookie(secret=SECRET)

    assert cookie.read(connection({"Cookie": f"bms_session={value}"})) is None


def test_a_tampered_cookie_is_ignored() -> None:
    cookie = SignedSessionCookie(secret=SECRET)
    header, payload, signature = _forge().split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = OTHER_OID
    forged = ".".join([header, _b64(json.dumps(claims).encode()), signature])

    assert cookie.read(connection({"Cookie": f"bms_session={forged}"})) is None


def test_an_unsigned_cookie_is_ignored() -> None:
    cookie = SignedSessionCookie(secret=SECRET)
    now = int(time.time())
    claims = {
        "aud": "bmsdna-app-native-session",
        "sub": OID,
        "email": "a@b.c",
        "tid": TENANT,
        "exp": now + 60,
    }
    header = _b64(json.dumps({"alg": "none"}).encode())
    unsigned = f"{header}.{_b64(json.dumps(claims).encode())}."

    assert cookie.read(connection({"Cookie": f"bms_session={unsigned}"})) is None


async def test_the_cookie_does_not_work_as_a_token(issuer: Issuer) -> None:
    # A cookie must never be accepted where a token is expected: other key, other algorithm.
    cookie = jwt.encode(
        {
            "iss": ISSUER,
            "aud": CLIENT,
            "tid": TENANT,
            "oid": OID,
            "email": "a@b.c",
            "exp": int(time.time()) + 60,
        },
        SECRET,
        algorithm="HS256",
        headers={"kid": "kid-1"},
    )

    assert await reason(make_verifier(issuer), cookie) == "algorithm"


# --- Dependency: requests ----------------------------------------------------


def make_app(
    issuer: Issuer,
    *,
    session: Any = "default",
    resolve_user: Callable[[EntraUser], Awaitable[Any | None]] | None = None,
    **verifier_options: Any,
) -> FastAPI:
    verifier = make_verifier(issuer, **verifier_options)
    cookie = SignedSessionCookie(secret=SECRET) if session == "default" else session
    auth = create_entra_auth_dependency(verifier, session=cookie, resolve_user=resolve_user)
    app = FastAPI()

    @app.get("/api/me")
    async def me(user: Any = Depends(auth)) -> Any:
        return {"oid": user.oid, "email": user.email} if isinstance(user, EntraUser) else user

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, user: Any = Depends(auth)) -> None:
        await websocket.accept()
        await websocket.send_json({"email": user.email})
        await websocket.close()

    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_valid_token_is_accepted_and_exchanged_for_a_cookie(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers=bearer(issuer.mint()))

    assert response.status_code == 200
    assert response.json() == {"oid": OID, "email": "anna@example.com"}
    attributes = {part.strip().lower() for part in response.headers["set-cookie"].split(";")}
    assert {"httponly", "secure", "samesite=lax", "path=/", "max-age=28800"} <= attributes
    assert not any(part.startswith("domain") for part in attributes)


async def test_without_credentials_the_answer_is_401(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer ", "Bearer garbage", "Bearer a.b.c"],
)
async def test_an_invalid_token_is_401_without_a_redirect(issuer: Issuer, header: str) -> None:
    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers={"Authorization": header})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert response.json() == {"detail": "Invalid token"}  # no reason for the client
    assert "location" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int(time.time()) - 600},
        {"aud": "other"},
        {"iss": "https://example.com"},
        {"oid": None},
    ],
)
async def test_a_token_that_does_not_check_out_is_401(
    issuer: Issuer, claims: dict[str, Any]
) -> None:
    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers=bearer(issuer.mint(**claims)))

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_another_scheme_counts_as_no_credentials(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers={"Authorization": "Basic YTpi"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_the_cookie_alone_works_afterwards(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        first = await client.get("/api/me", headers=bearer(issuer.mint()))
        second = await client.get(
            "/api/me", headers={"Cookie": f"bms_session={cookie_value(first)}"}
        )

    assert second.status_code == 200
    assert second.json() == {"oid": OID, "email": "anna@example.com"}
    assert "set-cookie" not in second.headers  # only a token renews the cookie


async def test_the_token_wins_over_the_cookie_of_another_user(issuer: Issuer) -> None:
    other = SignedSessionCookie(secret=SECRET)
    stale = Response()
    other.issue(stale, EntraUser(oid=OTHER_OID, email="boris@example.com", tenant_id=TENANT))

    async with client_for(make_app(issuer)) as client:
        response = await client.get(
            "/api/me",
            headers={**bearer(issuer.mint()), "Cookie": f"bms_session={cookie_value(stale)}"},
        )
        replaced = await client.get(
            "/api/me", headers={"Cookie": f"bms_session={cookie_value(response)}"}
        )

    assert response.json() == {"oid": OID, "email": "anna@example.com"}
    assert cookie_value(response) != cookie_value(stale)
    assert replaced.json() == {"oid": OID, "email": "anna@example.com"}


async def test_every_valid_token_renews_the_cookie(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        first = await client.get("/api/me", headers=bearer(issuer.mint()))
        second = await client.get(
            "/api/me",
            headers={**bearer(issuer.mint()), "Cookie": f"bms_session={cookie_value(first)}"},
        )

    assert "set-cookie" in second.headers


async def test_an_invalid_token_is_not_saved_by_a_valid_cookie(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        first = await client.get("/api/me", headers=bearer(issuer.mint()))
        response = await client.get(
            "/api/me",
            headers={
                **bearer(issuer.mint(exp=int(time.time()) - 600)),
                "Cookie": f"bms_session={cookie_value(first)}",
            },
        )

    assert response.status_code == 401


async def test_a_bad_cookie_is_401(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        for value in ["garbage", _forge("another-secret-with-at-least-32-bytes"), _forge(exp=1)]:
            response = await client.get("/api/me", headers={"Cookie": f"bms_session={value}"})
            assert response.status_code == 401


async def test_without_a_session_there_is_no_cookie_and_no_cookie_login(issuer: Issuer) -> None:
    async with client_for(make_app(issuer, session=None)) as client:
        with_token = await client.get("/api/me", headers=bearer(issuer.mint()))
        with_cookie = await client.get("/api/me", headers={"Cookie": f"bms_session={_forge()}"})

    assert with_token.status_code == 200
    assert "set-cookie" not in with_token.headers
    assert with_cookie.status_code == 401


# --- Dependency: your own users ----------------------------------------------


async def test_resolve_user_maps_the_identity(issuer: Issuer) -> None:
    async def resolve(identity: EntraUser) -> dict[str, Any] | None:
        return {"id": 7, "email": identity.email}

    async with client_for(make_app(issuer, resolve_user=resolve)) as client:
        first = await client.get("/api/me", headers=bearer(issuer.mint()))
        via_cookie = await client.get(
            "/api/me", headers={"Cookie": f"bms_session={cookie_value(first)}"}
        )

    assert first.json() == {"id": 7, "email": "anna@example.com"}
    assert via_cookie.json() == first.json()


async def test_an_unknown_user_is_403_and_gets_no_cookie(issuer: Issuer) -> None:
    async def resolve(identity: EntraUser) -> None:
        return None

    async with client_for(make_app(issuer, resolve_user=resolve)) as client:
        response = await client.get("/api/me", headers=bearer(issuer.mint()))

    assert response.status_code == 403
    assert "set-cookie" not in response.headers


async def test_a_user_removed_later_is_out_even_with_a_cookie(issuer: Issuer) -> None:
    allowed = {OID}

    async def resolve(identity: EntraUser) -> str | None:
        return identity.oid if identity.oid in allowed else None

    async with client_for(make_app(issuer, resolve_user=resolve)) as client:
        first = await client.get("/api/me", headers=bearer(issuer.mint()))
        allowed.clear()
        later = await client.get(
            "/api/me", headers={"Cookie": f"bms_session={cookie_value(first)}"}
        )

    assert first.status_code == 200
    assert later.status_code == 403


async def test_a_session_of_your_own(issuer: Issuer) -> None:
    class OwnSession:
        def __init__(self) -> None:
            self.issued: list[EntraUser] = []

        def issue(self, response: Response, user: EntraUser) -> None:
            self.issued.append(user)
            response.set_cookie("session", "own-format")

        def read(self, connection: HTTPConnection) -> EntraUser | None:
            return None  # cookie-only requests are not ours to judge

    own = OwnSession()
    async with client_for(make_app(issuer, session=own)) as client:
        with_token = await client.get("/api/me", headers=bearer(issuer.mint()))
        cookie_only = await client.get("/api/me", headers={"Cookie": "session=own-format"})

    assert with_token.status_code == 200
    assert with_token.headers["set-cookie"].startswith("session=own-format")
    assert own.issued == [USER]
    assert cookie_only.status_code == 401


# --- Dependency: Microsoft is down --------------------------------------------


async def test_without_keys_the_answer_is_503_not_401(issuer: Issuer) -> None:
    issuer.failing = True

    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers=bearer(issuer.mint()))

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert "set-cookie" not in response.headers


# --- Dependency: WebSocket -------------------------------------------------------


def test_websocket_handshake_with_a_token(issuer: Issuer) -> None:
    headers = bearer(issuer.mint())
    with (
        TestClient(make_app(issuer)) as client,
        client.websocket_connect("/ws", headers=headers) as socket,
    ):
        assert socket.receive_json() == {"email": "anna@example.com"}


def test_websocket_handshake_with_the_cookie(issuer: Issuer) -> None:
    with (
        TestClient(make_app(issuer)) as client,
        client.websocket_connect("/ws", headers={"Cookie": f"bms_session={_forge()}"}) as socket,
    ):
        assert socket.receive_json() == {"email": "anna@example.com"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer garbage"}])
def test_websocket_handshake_without_valid_credentials_is_refused(
    issuer: Issuer, headers: dict[str, str]
) -> None:
    with (
        TestClient(make_app(issuer)) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws", headers=headers),
    ):
        pass


# --- Keys: slow or unreachable Microsoft ------------------------------------------


async def test_a_stale_cache_does_not_hold_up_requests(issuer: Issuer) -> None:
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_cache_seconds=3600)
    await verifier.verify(issuer.mint())
    clock.now += 7200
    issuer.delay = 0.3  # Microsoft is slow

    started = time.perf_counter()
    users = await asyncio.gather(*(verifier.verify(issuer.mint()) for _ in range(5)))
    elapsed = time.perf_counter() - started

    assert {user.oid for user in users} == {OID}
    assert elapsed < 0.15  # nobody waited for the reload
    await asyncio.sleep(0.5)
    assert issuer.fetches == 2  # one reload, in the background


async def test_a_cancelled_first_request_does_not_lock_everybody_out(issuer: Issuer) -> None:
    issuer.delay = 0.1
    verifier = make_verifier(issuer, clock=Clock())
    first = asyncio.create_task(verifier.verify(issuer.mint()))
    await asyncio.sleep(0.02)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    # The load went on without the cancelled caller; the next one does not wait a minute.
    assert (await verifier.verify(issuer.mint())).oid == OID
    assert issuer.fetches == 1


async def test_a_hanging_reload_gives_up(issuer: Issuer) -> None:
    issuer.delay = 5
    verifier = make_verifier(issuer, jwks_timeout_seconds=0.05)

    started = time.perf_counter()
    with pytest.raises(EntraKeysUnavailableError):
        await verifier.verify(issuer.mint())

    assert time.perf_counter() - started < 1


async def test_an_empty_cache_tries_again_after_a_few_seconds(issuer: Issuer) -> None:
    issuer.failing = True
    clock = Clock()
    verifier = make_verifier(issuer, clock=clock, jwks_min_refresh_seconds=60)
    with pytest.raises(EntraKeysUnavailableError):
        await verifier.verify(issuer.mint())

    issuer.failing = False
    clock.now += 6  # far less than a minute
    assert (await verifier.verify(issuer.mint())).oid == OID


# --- Token: configuration and claims -----------------------------------------------


async def test_an_upper_case_tenant_in_the_configuration_works(issuer: Issuer) -> None:
    verifier = EntraTokenVerifier(
        tenant_id=TENANT.upper(), audience=CLIENT, fetch_jwks=issuer.fetch
    )

    user = await verifier.verify(issuer.mint())

    assert verifier.tenant_id == TENANT
    assert verifier.issuer == ISSUER
    assert user.tenant_id == TENANT


async def test_the_tenant_of_the_user_is_the_configured_one(issuer: Issuer) -> None:
    # The token says the same tenant in another spelling: accepted, reported as configured.
    user = await make_verifier(issuer).verify(issuer.mint(tid=f" {TENANT.upper()} "))

    assert user.tenant_id == TENANT


def test_a_tenant_with_a_trailing_newline_is_refused() -> None:
    with pytest.raises(ValueError, match="tenant"):
        EntraTokenVerifier(tenant_id=TENANT + "\n", audience=CLIENT)


async def test_an_access_token_is_not_an_id_token(issuer: Issuer) -> None:
    assert await reason(make_verifier(issuer), issuer.mint(scp="access_as_user")) == "access_token"


@pytest.mark.parametrize(
    "header",
    [
        {"jku": "https://evil.example/keys"},
        {"x5u": "https://evil.example/cert"},
        {"jwk": {"kty": "RSA", "n": "AQAB", "e": "AQAB"}},
    ],
)
async def test_key_hints_in_the_header_are_ignored(issuer: Issuer, header: dict[str, Any]) -> None:
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    token = issuer.mint(key=stranger, headers=header)

    assert await reason(make_verifier(issuer), token) == "signature"
    assert issuer.fetches == 1  # only the one load from the fixed address


async def test_from_env_passes_options_on(issuer: Issuer) -> None:
    verifier = EntraTokenVerifier.from_env(
        {"ENTRA_TENANT_ID": TENANT, "ENTRA_AUDIENCE": CLIENT},
        leeway=5,
        fetch_jwks=issuer.fetch,
    )

    # 10 s past: expired with this leeway, although fine with the default of 60 s.
    assert await reason(verifier, issuer.mint(exp=int(time.time()) - 10)) == "expired"


# --- Cookie: details -----------------------------------------------------------------


def test_a_cookie_from_a_replica_with_a_fast_clock_is_read() -> None:
    cookie = SignedSessionCookie(secret=SECRET)

    ahead = cookie.read(connection({"Cookie": f"bms_session={_forge(iat=int(time.time()) + 20)}"}))
    far_ahead = cookie.read(
        connection({"Cookie": f"bms_session={_forge(iat=int(time.time()) + 600)}"})
    )

    assert ahead is not None
    assert far_ahead is None


def test_a_host_prefixed_cookie_name() -> None:
    response = Response()
    SignedSessionCookie(secret=SECRET, name="__Host-bms_session").issue(response, USER)

    assert response.headers["set-cookie"].startswith("__Host-bms_session=")
    with pytest.raises(ValueError, match="Secure"):
        SignedSessionCookie(secret=SECRET, name="__Host-bms_session", secure=False)


# --- Dependency: details ---------------------------------------------------------------


async def test_a_cookie_of_another_tenant_is_refused(issuer: Issuer) -> None:
    # Another environment or tenant that shares the secret.
    foreign = _forge(tid="99999999-9999-4999-8999-9999999999ee")

    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers={"Cookie": f"bms_session={foreign}"})

    assert response.status_code == 401


async def test_another_scheme_does_not_hide_a_valid_cookie(issuer: Issuer) -> None:
    # Only a Bearer header is a token. This is what the guide says, so pin it down.
    headers = {"Authorization": "Basic YTpi", "Cookie": f"bms_session={_forge()}"}

    async with client_for(make_app(issuer)) as client:
        response = await client.get("/api/me", headers=headers)

    assert response.status_code == 200


async def test_a_tab_after_bearer_still_counts_as_a_token(issuer: Issuer) -> None:
    async with client_for(make_app(issuer)) as client:
        response = await client.get(
            "/api/me", headers={"Authorization": "Bearer\t" + issuer.mint()}
        )

    assert response.status_code == 200


def make_delivery_app(issuer: Issuer) -> FastAPI:
    auth = create_entra_auth_dependency(
        make_verifier(issuer), session=SignedSessionCookie(secret=SECRET)
    )
    app = FastAPI()

    @app.get("/model", response_model=dict[str, str])
    async def model(user: Any = Depends(auth)) -> dict[str, str]:
        return {"email": user.email}

    @app.post("/no-content", status_code=204)
    async def no_content(user: Any = Depends(auth)) -> None:
        return None

    @app.get("/own-response")
    async def own_response(user: Any = Depends(auth)) -> JSONResponse:
        return JSONResponse({"email": user.email})

    @app.get("/own-response-with-cookie")
    async def own_response_with_cookie(request: Request, user: Any = Depends(auth)) -> JSONResponse:
        response = JSONResponse({"email": user.email})
        copy_session_cookie(request, response)
        return response

    return app


@pytest.mark.parametrize(
    ("method", "path", "cookie_arrives"),
    [
        ("GET", "/model", True),
        ("POST", "/no-content", True),
        # FastAPI drops the headers of a dependency when the route returns a Response itself.
        ("GET", "/own-response", False),
        ("GET", "/own-response-with-cookie", True),
    ],
)
async def test_where_the_cookie_arrives(
    issuer: Issuer, method: str, path: str, cookie_arrives: bool
) -> None:
    async with client_for(make_delivery_app(issuer)) as client:
        response = await client.request(method, path, headers=bearer(issuer.mint()))

    assert response.status_code in (200, 204)
    assert ("set-cookie" in response.headers) is cookie_arrives


async def test_copy_session_cookie_sets_nothing_without_a_token(issuer: Issuer) -> None:
    async with client_for(make_delivery_app(issuer)) as client:
        first = await client.get("/model", headers=bearer(issuer.mint()))
        response = await client.get(
            "/own-response-with-cookie", headers={"Cookie": f"bms_session={cookie_value(first)}"}
        )

    assert response.status_code == 200
    assert "set-cookie" not in response.headers  # only a token renews the cookie


# --- Key download ----------------------------------------------------------------------


class _KeyServer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/keys")
            self.end_headers()
            return
        body = {
            "/ok": b'{"keys": []}',
            "/list": b"[]",
            "/big": b'{"keys": "' + b"a" * 2_000_000 + b'"}',
        }.get(self.path, b"{}")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # the client hangs up on purpose when it refuses an oversized document


@pytest.fixture
def key_server() -> Iterator[str]:
    server = _QuietServer(("127.0.0.1", 0), _KeyServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_key_document_is_read(key_server: str) -> None:
    assert _download_json(key_server + "/ok") == {"keys": []}


def test_a_key_document_that_is_not_an_object_is_refused(key_server: str) -> None:
    with pytest.raises(ValueError, match="not an object"):
        _download_json(key_server + "/list")


def test_a_redirect_of_the_key_endpoint_is_not_followed(key_server: str) -> None:
    with pytest.raises(urllib.error.HTTPError):
        _download_json(key_server + "/redirect")


def test_an_oversized_key_document_is_cut_off_and_refused(key_server: str) -> None:
    with pytest.raises(ValueError):
        _download_json(key_server + "/big")


def test_the_key_url_must_be_https() -> None:
    with pytest.raises(ValueError, match="https"):
        _fetcher("http://login.microsoftonline.com/keys")
