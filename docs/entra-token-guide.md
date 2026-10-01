# Sign-in with the Entra token

This guide is for backend and web app teams. The user signs in **once in the
app** (Microsoft Entra ID). After that, no web app asks again: the app sends
the Entra **ID token** to the backend of every web app that has the `identity`
capability, and attaches it to the `fetch`/XHR calls of its page. A session
cookie of your own is no longer needed for this.

| Who               | What                                                                                                                                |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **iOS app**       | Signs the user in, renews the token silently, sends it to your backend and into your page.                                          |
| **You (backend)** | Check the token, take the user from it, and exchange it for a short-lived session cookie. What the user may do stays your decision. |
| **You (web app)** | Nothing, as long as you call your own backend with `fetch`/XHR. `getAccessToken()` is for the rest.                                 |

Backend side:
[`python/app-native/bmsdna/app_native/entra.py`](../python/app-native/bmsdna/app_native/entra.py).
Web app side: [`getAccessToken`](../packages/app-native/src/identity.ts).

## What the app sends

```
Authorization: Bearer <Entra ID token (JWT)>
```

- **To where:** only the host of the web app's `apiBaseURL` (`https`/`wss`, never
  plain `http`), and only for web apps with the `identity` capability. Web apps
  without it (for example pages on SharePoint) get no token and keep their cookie.
- **Which calls:** every native call: device registration, location, document
  upload, notification actions, Live Activity reports, the widget feed,
  widget actions and options, the approvals feed and decisions. **And** the
  `fetch`/XHR calls of your page to the origin of `apiBaseURL`.
- **Lifetime:** about one hour. The app keeps a token until about two minutes before
  it expires and then renews it silently. If the backend answers **401**, the app
  repeats a native call once with a freshly renewed token (for the page, see "Limits
  in the web view").
- **`user_email` in bodies** still comes along (it is read from the token), but
  from your backend's point of view it is client input: it must **not** decide who
  the caller is. The identity is the token.

The token is an **ID token (OIDC v2.0)**, not an access token for an API. Its
audience (`aud`) is the client ID of the iOS app's registration, not your API. It
proves **who** the user is. It is no permission to call Microsoft Graph on the
user's behalf (there is no refresh token on your side); a backend that needs Graph
needs its own consent flow.

## What your backend has to check

| Check       | Value                                                                                                     |
| ----------- | --------------------------------------------------------------------------------------------------------- |
| Signature   | RS256, key from `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys` (`kid` in the header) |
| `iss`       | `https://login.microsoftonline.com/<tenant-id>/v2.0`                                                      |
| `tid`       | `<tenant-id>`                                                                                             |
| `aud`       | `<ios-client-id>`, the client ID of the iOS app's registration                                            |
| `exp`/`nbf` | as usual, with a small tolerance (60 s)                                                                   |

The user: `oid` (object ID, stable, use it as the key), `email` or otherwise
`preferred_username` (compare it without regard to case), `name` (optional). A
token without `oid` or without both `email` and `preferred_username` is refused.

Both IDs (`<tenant-id>` and `<ios-client-id>`) are **configuration**, nothing is
hard-wired. Get them from the team that runs the app.

## With the toolkit

```python
import os

from bmsdna.app_native import (
    EntraTokenVerifier,
    SignedSessionCookie,
    create_entra_auth_dependency,
    create_widget_feed_router,
)

verifier = EntraTokenVerifier.from_env()  # ENTRA_TENANT_ID, ENTRA_AUDIENCE

require_user = create_entra_auth_dependency(
    verifier,
    session=SignedSessionCookie(secret=os.environ["SESSION_SECRET"]),
    resolve_user=find_user,  # optional, see below
)

app.include_router(
    create_widget_feed_router(get_widgets=get_widgets, auth_dependency=require_user),
    prefix="/api",
)


@app.get("/api/me")
async def me(user=Depends(require_user)):
    return {"email": user.email, "name": user.name}
```

`require_user` is a normal FastAPI dependency: use it for **all** routers of the
package and for your own routes. `context.user` in your callbacks is what it returns.

- `ENTRA_TENANT_ID`: the directory (tenant) ID, a GUID. `common` and similar are
  refused, they would accept tokens of any tenant.
- `ENTRA_AUDIENCE`: the client ID of the iOS app's registration. Several, separated
  by commas, are fine.
- `SESSION_SECRET` (your own name): random, at least 32 bytes, e.g. `openssl rand -hex 32`.

### Your own users: `resolve_user`

A valid token says who the user is, not that your web app knows them. With
`resolve_user` you look the user up (by `oid`) and return **your** user object,
which then arrives as `context.user`:

```python
async def find_user(identity: EntraUser) -> User | None:
    return await users.by_oid(identity.oid)  # None = not one of ours
```

Returning `None` answers **403**. It is called for the token and for the cookie alike,
so a user you remove is out at once, even with a cookie that is still valid. Without
`resolve_user`, `context.user` is the `EntraUser` (`oid`, `email`, `name`, `tenant_id`).

## What the backend answers

| Request                                          | Answer                                                                              |
| ------------------------------------------------ | ----------------------------------------------------------------------------------- |
| Valid token                                      | accepted; the session cookie is set if you passed `session=` (see below)            |
| Invalid, expired or foreign token                | **401**, never a redirect to the Microsoft login. A valid cookie does not rescue it |
| No token, valid cookie                           | accepted                                                                            |
| No token, no valid cookie                        | **401**                                                                             |
| Valid token, but `resolve_user` returns `None`   | **403**                                                                             |
| Microsoft's signing keys cannot be loaded at all | **503**                                                                             |

Why **401** and not 403 or a redirect: the app treats 401 as "the token was not
accepted", fetches a renewed one and repeats the call **once**. A 403 or a redirect
to a login page would not trigger that. Use 403 only for "the token is fine, but this
user is not allowed in": a renewed token would not help there, and the app does not
retry.

On the widget feed and the approvals feed the app reads 401 and 403 the same way: it
clears that web app's widgets and approvals (they could belong to another user) and
shows a note to open the web app. So a 403 for a user your backend does not know looks
like "signed out" there. Only 401 makes the app renew the token and repeat the call.
A widget action or an approval decision that gets 401/403 shows "open the web app and
sign in" and clears nothing.

The signing keys are cached for an hour. An unknown `kid` (Microsoft rotated its
keys) reloads them, but at most once a minute, so nobody can make your backend call
Microsoft on every request with made-up tokens. While a reload runs, requests are
answered with the cached keys; only a token whose `kid` is not cached waits for it (at
most 10 seconds). Cached keys are used until a reload succeeds, however old they are:
a Microsoft outage does not stop your sign-in. The price is that a key Microsoft
withdrew stays trusted until the next successful reload.

## The session cookie

**Why:** the browser can attach the token to your `fetch` calls (the app does that),
but not to page navigation, `<img>`, `<script>`, downloads by link, `EventSource` or
`WebSocket`. A cookie, on the other hand, is sent by the browser everywhere, and a
`HttpOnly` cookie cannot be read by JavaScript, so an injected script cannot steal it
(it could steal the token your page holds in memory).

**How:** the app attaches the token to the first call of your page, for example
`GET /api/me`. The backend checks it, answers normally **and** sets the cookie.
The web view stores it because the call comes from the page itself. From then on the
cookie is enough for the page. Native calls of the app keep sending the token.

| Cookie attribute | Value                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------- |
| Name             | `bms_session` (`name=`)                                                                                     |
| `HttpOnly`       | always                                                                                                      |
| `Secure`         | yes (`secure=False` only for local development over plain http)                                             |
| `SameSite`       | `Lax` (`same_site='strict'` possible; `Lax` lets a link from Outlook or Teams open the app signed in)       |
| `Path`           | `/`                                                                                                         |
| `Domain`         | **none**: the cookie belongs to the host of your backend only                                               |
| Lifetime         | 8 hours (`max_age=`), **renewed with every call that carries a valid token**                                |
| Content          | the user (`oid`, `email`, `name`, tenant), signed (HS256) with your secret; nothing is stored on the server |

- **Short on purpose, but not instant.** Once Entra stops accepting the user (password
  change, Conditional Access, revoked access), no token reaches you any more and the
  renewal stops. The cookie then lives on for its `max_age` plus the rest of the last
  token (up to an hour), about nine hours in the worst case. The cookie is stateless,
  so there is **no revocation on the server** and signing out of the app only deletes
  it on the device. Let `resolve_user` check whether the account is still allowed.
- **The exchange lengthens a token's life.** A leaked ID token is good for about an
  hour; exchanged for a cookie it becomes a session of up to eight hours. Another
  reason to never log or forward a token.
- **Another user:** every call with a valid token issues a new cookie, so a cookie of a
  previous user is replaced. When the user signs out or another user signs in, the
  app deletes **all** cookies whose domain is exactly the host of the web app or of its
  backend, for every web app with `identity` (a cookie with `Domain=<that host>` too).
  A cookie set for a **parent domain** (`Domain=.example.com`) it cannot reach: that is
  why the cookie has no `Domain`. After a sign-out the app shows its sign-in screen;
  when a different person signs in, the page is reloaded.
- **Secret:** changing `SESSION_SECRET` signs everybody out. The app then exchanges its
  token again, which the user does not notice.
- **Same site:** the cookie only reaches your backend if page and backend are on the
  same **site**. Put `apiBaseURL` on the same origin as the page where you can.
- **Where the cookie arrives:** it is set through the response FastAPI builds from your
  return value (a dict, a model, `None`; also with `status_code=204`). A route that
  returns a `Response` itself (`JSONResponse`, `RedirectResponse`, `FileResponse`, a
  stream) loses the headers of the dependency **without an error**: call
  `copy_session_cookie(request, response)` on that response. A WebSocket handshake
  cannot set a cookie at all.
- **Hardening:**
  - `name='__Host-bms_session'` makes browsers accept the cookie only with `Secure`,
    `Path=/` and no `Domain`, so a sibling subdomain cannot plant a cookie of the same
    name.
  - Use another `SESSION_SECRET` for every environment; a cookie of another tenant is
    refused, one of another environment sharing the secret is not.
  - `SameSite=Lax` does not stop requests from a sibling subdomain of the same site. For
    cookie-authenticated requests that change data, and for WebSocket handshakes, check
    the `Origin` header against your own origins.
- **Outside the app** there is no token, and your normal login keeps working as before.

Your own cookie format? Pass an object with `issue(response, user)` and
`read(connection)` as `session=` instead of `SignedSessionCookie` (the
`SessionCookie` protocol). `read` may always return `None` if cookie-only requests are
handled by your own dependency; see the migration below.

## Limits in the web view

The page does not need code for the sign-in: it calls `GET /api/me`, gets the user
because the app attached the token, and shows itself signed in. The login popup does
not appear.

The app attaches the token to `fetch` and `XMLHttpRequest` of the **main frame**
to the origin of `apiBaseURL` and to nothing else (no CDN, no third-party API, no
iframe). A header your page sets itself stays as it is.

If the backend answers 401, the app repeats a **`fetch`** once with a renewed token
(not one with a stream body). An **`XMLHttpRequest`** is not repeated: it only drops the
cached token, so the next call gets a new one. Most HTTP libraries (axios, …) use XHR:
repeat such a call yourself. A synchronous XHR gets no token at all.

Where the browser does not allow your own headers, the token is **not** attached:

| What                                            | What to do                                                                                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Page navigation, form posts                     | Rely on the cookie. (A server-rendered page protected only by the cookie does not load before the first token call; the web apps are SPAs.) |
| `<img src>`, `<script src>`, links to downloads | Rely on the cookie, or load with `fetch` and show the blob                                                                                  |
| `EventSource`                                   | Cookie, or `fetch` with a stream                                                                                                            |
| `WebSocket`                                     | Cookie, or ask `getAccessToken()` and send the token as the **first message** (never in the URL, URLs end up in logs)                       |
| Web workers                                     | A worker cannot call the bridge: ask `getAccessToken()` on the main thread, hand the token over, set the header in the worker               |

```ts
import { getAccessToken } from '@bmsuisse/app-native'

const session = await getAccessToken() // { ok, token, expiresAt } (seconds since 1970)
if (session.ok) socket.send(JSON.stringify({ token: session.token }))
// after your backend answered 401: await getAccessToken({ refresh: true })
```

`getAccessToken` needs `identity` (`capability`). It works only from the main frame of
a page whose host is the host of your web app or of its `apiBaseURL`, over `https`
(`forbidden` otherwise, also from an iframe; ports are not compared). `notSignedIn`
means nobody is signed in **or** no token can be had right now, for example offline
with an expired token or when Microsoft asks for a new sign-in. Outside the app it
answers `{ ok: false, error: 'unavailable' }`. On the server side the same
dependency also works for WebSocket routes (the app sets the header in the handshake),
and `verifier.verify(token)` checks a token that arrived in a first message.

If your API is on **another origin** than the page, the `Authorization` header makes
the browser send a preflight request: your backend needs CORS that allows this header
and the origin of the page.

## Good to know

- **Home Screen widgets** run in a separate process and cannot renew the token. They
  use a copy the app keeps in the keychain for them, until about 30 seconds before it
  expires. After that a widget cannot load its feed and keeps showing its last content
  until the app has stored a fresh copy (it does that whenever it is in the foreground,
  after a background refresh and after every successful feed load). A 401/403 of the
  feed deletes the copy. Only a tap on a widget button then says "open the app once".
- **Calls without a connection:** device registration and identity, location, document
  upload, notification actions and Live Activity reports wait in a queue (up to 500,
  for 7 days) and get the token that is valid **when they are sent**; the queue never
  stores a token. Widget actions, widget options and approval decisions are not queued:
  without a connection they fail at once. (The keychain copy for the widgets above, and
  MSAL's own cache, do hold tokens.)
- **News images** in widgets: the app sends neither cookie nor token to your web app
  for them (web apps with `identity`), so the images must be loadable without sign-in.
  Images on a SharePoint site that your web app uses for its news still get the
  SharePoint cookie.
- **The same token goes to every backend** (its `aud` is the iOS app). A backend that
  receives it could replay it at another backend while it is valid. So use it only to
  identify the user, **never forward it, store it or write it to a log**. If every
  backend should get a token of its own, the app can ask for one scope per web app
  later (`aud` becomes `api://…`); `EntraTokenVerifier(audience=[…])` already takes
  several audiences.
- **Local development:** without the app there is no token. Keep a development switch of
  your own (for example a header with an email address that only works in development
  mode); nothing in this guide changes it.

## Migrating a backend that has a cookie login

You have a login with its own session cookie today (call it `session`) and want the
app's users in without a second login. The order matters:

1. **Backend first.** Accept the token **in addition** to the cookie. The token has
   priority. Nothing changes for browser users.
2. **Then** the app team enables `identity` for your web app, and the app starts
   sending the token.
3. Later, if you want, retire the cookie login.

Add the configuration (`ENTRA_TENANT_ID`, `ENTRA_AUDIENCE`, and a secret if you use
`SignedSessionCookie`) and put the check **in front of** your existing dependency, not
in place of it:

```python
entra = create_entra_auth_dependency(
    EntraTokenVerifier.from_env(),
    session=OwnSession(),  # sets YOUR cookie; see below
    resolve_user=find_user,  # your user, found by the oid
)


async def require_user(request: Request, response: Response) -> User:
    if settings.dev_mode and (email := request.headers.get("x-dev-user-email")):
        return await user_by_email(email)  # unchanged: local development
    if bearer_token(request) is not None:
        return await entra(request, response)  # the app: check the token, set the cookie
    return await legacy_cookie_user(request)  # unchanged: browser login, cookie `session`
```

Look users up by `oid` (and tenant), not by `email` or `preferred_username`: they can
change and are not guaranteed unique. If your users are keyed by email today, match by
email the first time, store the `oid` with the user, and use the `oid` from then on.

`OwnSession` is the `SessionCookie` protocol with your cookie format: `issue` sets
your `session` cookie for the user, `read` just returns `None`, because cookie-only
requests go through `legacy_cookie_user`. That way nothing about your existing cookie
changes, and a user who arrives with the token gets exactly the cookie your login
would have given them.

If you have an endpoint like `GET /api/me` that answers "nobody" for anonymous
callers, keep that, but let it see the token:

```python
async def optional_user(request: Request, response: Response) -> User | None:
    if bearer_token(request) is not None:
        return await entra(request, response)  # an invalid token is 401, not "nobody"
    return await legacy_optional_cookie_user(request)  # None when nobody is signed in
```

**Check it:** in a debug build of the app (and only when Entra is configured), the Info
tab has a section "Entra-Anmeldung (Test)". "Backends prüfen" calls the identity path of
each web app that has one configured (for example `api/me`) with **only the token and
no cookie**. Expected: `200`, and a field `email` (the app can be told another field
name) with the signed-in address in the JSON. Anything else shows "Token nicht
akzeptiert": a backend that ignores the header (`200` with `null`), or answers `401`.

**Do not forget:**

- An endpoint that is not behind `require_user` (and so not behind the dependency)
  does not see the token. All routers of this package, and your own API routes,
  should use it.
- Decide who is allowed in `resolve_user`, by the `oid`, never by what the body says.
- CORS, if the API is on another origin than the page (see above).
- Keep the cookie **host-only**: a cookie with `Domain` set to exactly your host is
  removed by the app too, but one on a parent domain (`Domain=.example.com`) is out of
  its reach when another user signs in.
