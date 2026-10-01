# bmsdna-app-native

Python library for FastAPI backends: send push notifications to the BMS app
(iOS) and receive its data (location, documents, notification actions,
widgets, approvals) — **without a database or service of its
own**. Everything runs either as a direct
function call (`send_push`) or as an `APIRouter` that you mount in your own
backend; you decide how data is stored via callbacks.

Counterpart for the web page: [`@bmsuisse/app-native`](../../packages/app-native)
(npm). Formats and guides: [`docs/`](../../docs).

## Installation

```bash
uv add bmsdna-app-native
# or
pip install bmsdna-app-native
```

In code:

```python
from bmsdna.app_native import send_push, create_ingest_router
```

## Table of contents

- [send_push() — push with a banner](#send_push--push-with-a-banner)
- [Cleaning up dead device tokens](#cleaning-up-dead-device-tokens)
- [send_silent_push() — silent push (background refresh)](#send_silent_push--silent-push-background-refresh)
- [create_ingest_router() — receiving device tokens + location](#create_ingest_router--receiving-device-tokens--location)
- [create_document_router() — receiving file uploads (scans)](#create_document_router--receiving-file-uploads-scans)
- [create_notification_action_router() — receiving interactive push buttons](#create_notification_action_router--receiving-interactive-push-buttons)
- [Dashboard widgets: feed, actions, `send_widget_update()`](#dashboard-widgets-feed-actions-send_widget_update)
- [Live Activities: `send_live_activity_update()` & co.](#live-activities-send_live_activity_update--co)
- [Approvals: `create_approvals_router()`, `send_approvals_update()`](#approvals-create_approvals_router-send_approvals_update)
- [Urgent pushes and critical alerts: `send_critical_alert()`](#urgent-pushes-and-critical-alerts-send_critical_alert)
- [Auth: `auth_dependency`](#auth-auth_dependency)
- [Sign-in with the Entra token: `create_entra_auth_dependency()`](#sign-in-with-the-entra-token-create_entra_auth_dependency)
- [Setting up APNs access](#setting-up-apns-access)
- [Local example & tests](#local-example--tests)

---

## `send_push()` — push with a banner

```python
from bmsdna.app_native import send_push

sent, detail = await send_push(
    device_token="<apns-device-token>",  # from your on_device_registered callback
    title="New order",
    body="Order 123 is awaiting confirmation",
    data={"path": "/orders/123", "order_id": "123"},  # optional, see below
)
# sent: bool, detail: str | None (error description when sent=False)
```

A direct function call, not an endpoint — call it from anywhere in your
own code as soon as you have an APNs device token (you get it
from `create_ingest_router()`, see below). Raises `RuntimeError` if the
`APNS_*` environment variables are missing or the auth key cannot be found or
is not PEM text —
catch it if you call this for several devices in a loop.

**`data` conventions that the iOS app evaluates:**

| Key                                                              | Effect in the app                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `data={"webapp_id": "partner-tool"}`                             | Assigns the push to the web app with this `id` (your web app's `id` in the app) (home list, "Recently used" tabs, combined notifications tab). **If the app hosts several web apps**, every backend should include this field with every push — otherwise the notification still lands in the notifications tab, but as "Unknown app" with no way to navigate, and silent pushes (see below) are ignored entirely.                            |
| `data={"path": "/orders/123"}`                                   | When the user taps the notification, the WebView of the assigned web app navigates to this URL (relative to its `url`).                                                                                                                                                                                                                                                                                                                       |
| `data={"actions": [{"id": "confirm", "title": "Confirm"}, ...]}` | Shows these buttons below the notification in the app's notifications tab — no app-side configuration needed, entirely determined by the payload. When the user taps one, it arrives in `create_notification_action_router()` (`action` = the tapped `id`, `data` = the remaining fields of this push). There are **no** buttons directly on the system banner/Lock Screen (iOS would require a category registered with the app in advance). |

## Cleaning up dead device tokens

When `sent=False`, `send_push()`/`send_silent_push()` return Apple's
failure reason in `detail`. Two of them are **permanent**; retrying with
the same token is pointless:

```python
from bmsdna.app_native import PERMANENTLY_INVALID_TOKEN_REASONS

sent, detail = await send_push(device_token=device.push_token, title=..., body=...)
if not sent and detail in PERMANENTLY_INVALID_TOKEN_REASONS:
    my_store.delete(device_id)  # or at least set push_token=None
```

- `"BadDeviceToken"` — the token format does not match (or sandbox/production
  mixed up, see `APNS_USE_SANDBOX`).
- `"Unregistered"` — the app was uninstalled on this device.

**Important if you manage devices by `device_id`:** The iOS app
stores its `device_id` in the Keychain, not in `UserDefaults` — so it
survives an uninstall + reinstall on the same device
(the same `device_id` comes back). So if, on an
`"Unregistered"` failure, you do not delete the whole device entry (e.g. only the
`push_token`), a later reinstall is automatically matched to the
correct record again. If you do **not** clean up, on the other hand, your
device overview grows indefinitely with dead entries.

## `send_silent_push()` — silent push (background refresh)

```python
from bmsdna.app_native import send_silent_push

sent, detail = await send_silent_push(
    device_token="<apns-device-token>",
    data={"webapp_id": "partner-tool", "reason": "new_data"},
)
```

No banner/sound — sets `content-available: 1` + the
`apns-push-type: background`/`apns-priority: 5` headers required by Apple.
Briefly wakes the app, which then (throttled, by default at most every 15
minutes) reloads the WebView of the web app assigned via `webapp_id`.
**If the app hosts several web apps**, `webapp_id` is not optional here —
without a recognizable assignment, the app ignores the silent push entirely.

iOS delivers silent pushes only on a "best effort" basis — no real-time guarantee.
If your backend sends very frequently, throttle on the server side yourself anyway (the
toolkit deliberately keeps no state for this).

## `create_ingest_router()` — receiving device tokens + location

```python
from bmsdna.app_native import (
    DeviceRegistration,
    LocationUpdate,
    WidgetRequestContext,
    create_ingest_router,
)


async def on_device_registered(
    body: DeviceRegistration, context: WidgetRequestContext
) -> None: ...  # store push_token in your own DB, context.user is the caller


async def on_location_received(
    body: LocationUpdate, context: WidgetRequestContext
) -> None: ...  # process live or store in your DB


app.include_router(
    create_ingest_router(
        on_device_registered=on_device_registered,
        on_location_received=on_location_received,
        auth_dependency=require_user,  # required, see "Auth" below
    ),
    prefix="/api",
)
```

Creates two endpoints under the `prefix` you choose:

| Endpoint                  | Payload (Pydantic model) | Callback               |
| ------------------------- | ------------------------ | ---------------------- |
| `POST <prefix>/devices`   | `DeviceRegistration`     | `on_device_registered` |
| `POST <prefix>/locations` | `LocationUpdate`         | `on_location_received` |

**`DeviceRegistration`** (`bmsdna.app_native/models.py`):

| Field        | Type            | Required | Note                                                                                                       |
| ------------ | --------------- | -------- | ---------------------------------------------------------------------------------------------------------- |
| `device_id`  | `str`           | yes      | stable, anonymous device ID (UUID), generated by the app                                                   |
| `push_token` | `str \| null`   | no       | APNs device token                                                                                          |
| `platform`   | `"ios" \| null` | no       | currently always `"ios"`                                                                                   |
| `user_email` | `str \| null`   | no       | email the app reports for the signed-in user, **unverified** — `null` on logout is a **deliberate delete** |

Important: `push_token` and `user_email` arrive **independently of each other**
(push registration often happens before login). In your
callback, check `body.model_fields_set` (standard Pydantic attribute) to
see which fields were actually sent in this specific call,
instead of misreading missing fields as "delete":

```python
async def on_device_registered(body: DeviceRegistration, context: WidgetRequestContext) -> None:
    device = my_store.get_or_create(body.device_id)
    if "push_token" in body.model_fields_set:
        device.push_token = body.push_token
    if "user_email" in body.model_fields_set:
        device.user_email = body.user_email  # may deliberately be None here
    # Who is calling? Trust context.user (from your auth_dependency), not the body.
    my_store.save(device)
```

**`LocationUpdate`**:

| Field                    | Type               | Required                                                          |
| ------------------------ | ------------------ | ----------------------------------------------------------------- |
| `device_id`              | `str`              | yes                                                               |
| `latitude` / `longitude` | `float`            | yes                                                               |
| `accuracy`               | `float \| null`    | no                                                                |
| `recorded_at`            | `datetime \| null` | no                                                                |
| `user_email`             | `str \| null`      | no — sent if the app currently knows a signed-in user, unverified |

Arrives as soon as the iOS app reports a change of location
(significant location changes from iOS — no fixed time interval, rule of thumb
~500m).

But only within the **sending hours** that the employee sets in the Info tab of the
app (weekdays + time of day, default Mon–Fri 07:00–18:00). Outside of these, simply nothing arrives —
so a gap in the data does not necessarily mean that the device is offline
or the permission is missing.

## `create_document_router()` — receiving file uploads (scans)

```python
from bmsdna.app_native import ReceivedDocument, WidgetRequestContext, create_document_router


async def on_document_received(
    doc: ReceivedDocument, context: WidgetRequestContext
) -> None: ...  # store doc.data (bytes) in blob storage/DB


app.include_router(
    create_document_router(
        on_document_received=on_document_received,
        auth_dependency=require_user,
        max_bytes=25 * 1024 * 1024,  # default; larger uploads get 413
    ),
    prefix="/api",
)
```

| Endpoint                  | Content-Type          | Callback               |
| ------------------------- | --------------------- | ---------------------- |
| `POST <prefix>/documents` | `multipart/form-data` | `on_document_received` |

Form fields: `file` (required), `device_id` (required), `user_email`
(optional), `kind` (optional, a free-form distinguishing attribute such as
`"scan"`/`"signature"`/`"receipt"`).

`ReceivedDocument` (not a Pydantic model but a `dataclass` — it contains raw
bytes that do not go through JSON):

```python
@dataclass
class ReceivedDocument:
    metadata: DocumentMetadata  # device_id, user_email, kind
    filename: str  # base name only, `../` parts are stripped
    content_type: str
    data: bytes
```

Triggered when the web app in the WebView calls
`window.webkit.messageHandlers.nativeBridge.postMessage({action: "scanDocument"})`
(opens the native VisionKit document scanner), or
`scanDocument()` from `@bmsuisse/app-native`.

## `create_notification_action_router()` — receiving interactive push buttons

Receives the event when the user taps a button from
`data={"actions": [...]}` (see `send_push()` above) in the app's notifications tab.

```python
from bmsdna.app_native import (
    NotificationActionReceived,
    WidgetRequestContext,
    create_notification_action_router,
)


async def on_action_received(
    action: NotificationActionReceived, context: WidgetRequestContext
) -> None:
    if action.action == "confirm":
        ...  # e.g. mark the order from action.data["order_id"] as accepted


app.include_router(
    create_notification_action_router(
        on_action_received=on_action_received, auth_dependency=require_user
    ),
    prefix="/api",
)
```

| Endpoint                             | Payload                      | Callback             |
| ------------------------------------ | ---------------------------- | -------------------- |
| `POST <prefix>/notification-actions` | `NotificationActionReceived` | `on_action_received` |

| Field       | Type           | Note                                                                                                          |
| ----------- | -------------- | ------------------------------------------------------------------------------------------------------------- |
| `device_id` | `str`          |                                                                                                               |
| `action`    | `str`          | the `id` of the tapped entry from `data={"actions": [...]}` of the original push, e.g. `"confirm"`/`"reject"` |
| `data`      | `dict \| null` | the remaining custom data from the original push (including the `"actions"` field itself)                     |

Only actual button taps trigger this — if the user taps the notification
itself (no button), that does not count as an action.

## Dashboard widgets: feed, actions, `send_widget_update()`

Puts your web app's widgets on the app's native home dashboard (KPIs,
statistics, lists, charts, progress, text, actions). The app
must have the `.dashboardWidgets` capability enabled for your web app
and know the feed path (`widgetFeedPath`).
Full format, all fields and examples:
[docs/dashboard-widgets-guide.md](../../docs/dashboard-widgets-guide.md).

```python
from bmsdna.app_native import (
    KpiData,
    KpiWidget,
    WidgetActionReceived,
    WidgetActionResult,
    WidgetRequestContext,
    create_widget_action_router,
    create_widget_feed_router,
    send_widget_update,
)


async def get_widgets(context: WidgetRequestContext):
    return [
        KpiWidget(
            id="open-orders",
            title="Open orders",
            required=True,
            data=KpiData(value=12, unit="pcs"),
        )
    ]


async def on_action(
    action: WidgetActionReceived, context: WidgetRequestContext
) -> WidgetActionResult | None:
    ...  # action.widget_id / action_id / item_id / values
    return WidgetActionResult(message="Done")


app.include_router(
    create_widget_feed_router(get_widgets=get_widgets, auth_dependency=require_user), prefix="/api"
)
app.include_router(
    create_widget_action_router(on_action_received=on_action, auth_dependency=require_user),
    prefix="/api",
)

# Somewhere in your code, when something changes:
await send_widget_update(
    device_token=token, webapp_id="partner-tool", widgets=await build_widgets(user)
)
```

| Endpoint / function                                         | Purpose                                                                                                                                                                                                                                                                                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET <prefix>/widgets?device_id=…`                          | Feed. The app fetches it itself and uses it to replace all of your web app's widgets.                                                                                                                                                                                                                                         |
| `POST <prefix>/widget-actions`                              | Button tap on a widget → `on_action_received(WidgetActionReceived, WidgetRequestContext)`. Returns `WidgetActionResult` or `None` (= ok).                                                                                                                                                                                     |
| `POST <prefix>/widget-options`                              | Results for search fields (`type="search"`) and lazily loaded select fields (`select` with `remote=True`) in `action` forms → `on_options_requested(WidgetOptionsRequest, WidgetRequestContext)`. Returns `WidgetOptionsResult` or directly a list of `ActionOption`, e.g. from Meilisearch (`create_widget_options_router`). |
| `send_widget_update(device_token, webapp_id, widgets=None)` | Silent push: with `widgets`, they are sent inline (automatically falls back to a feed fetch above `MAX_INLINE_WIDGETS_BYTES`); without `widgets`, only a feed fetch.                                                                                                                                                          |
| `dump_widgets(widgets)`                                     | Widgets as JSON-ready dicts in the app format, e.g. for the JS bridge or an endpoint of your own.                                                                                                                                                                                                                             |

`WidgetRequestContext.user` is the return value of your `auth_dependency`
(see below). Unlike with the other routers, you get it here
directly, because widgets are almost always user-specific. The models (`KpiWidget`,
`ListWidget`, `ActionWidget`, …) validate the format and serialize to
camelCase. In Python you write snake_case (`default_enabled=False`).

The user can also place the widgets individually on their Home Screen
("web app widget", iOS 17 and later). This needs nothing extra. A
button tap from there arrives with `source="homeScreen"` in
`WidgetActionReceived`.

## Live Activities: `send_live_activity_update()` & co.

Ongoing processes (order, pickup, job) live on the
Lock Screen and in the Dynamic Island. The app must have the
`.liveActivities` capability enabled for your web app.
Full flow, format and
limits: [docs/live-activities-guide.md](../../docs/live-activities-guide.md).

| Endpoint / function                                                          | Purpose                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST <prefix>/live-activities`                                              | The app reports tokens → `on_token_received(LiveActivityTokenReceived, WidgetRequestContext)`: `event="token"` (token of an activity), `"push_to_start_token"` (one token per device, iOS 17.2 and later) or `"ended"` (`create_live_activity_router`). |
| `send_live_activity_update(push_token, state, alert_title=None, …)`          | New state (`LiveActivityState`), highlighted with `alert_title`.                                                                                                                                                                                        |
| `send_live_activity_end(push_token, state=None, dismiss_at=None)`            | Ends the activity.                                                                                                                                                                                                                                      |
| `send_live_activity_start(push_to_start_token, attributes, state, …)`        | Starts an activity without the app (iOS 17.2 and later).                                                                                                                                                                                                |
| `build_live_activity_message(...)`, `build_live_activity_start_message(...)` | Only the payload, e.g. for tests or your own APNs client.                                                                                                                                                                                               |

## Approvals: `create_approvals_router()`, `send_approvals_update()`

Pending approvals (vacation, expenses, orders) for the logged-in
user. The app shows them at the top of Home under "Waiting for you"; the user
approves or rejects with a swipe, without opening your web app. The app
must have the `.approvals` capability enabled for your web app.
Format, fields and example:
[docs/approvals-guide.md](../../docs/approvals-guide.md).

| Endpoint / function                              | Purpose                                                                                                                                                                                                                              |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET <prefix>/approvals`                         | `get_approvals(WidgetRequestContext)` returns a list of `Approval`. Replaces all of your web app's approvals on the device.                                                                                                          |
| `POST <prefix>/approval-decisions`               | `on_decision(ApprovalDecisionReceived, WidgetRequestContext)`: `decision` is `"approve"` or `"reject"`, plus an optional `comment`. Returns `None` or `ApprovalDecisionResult(ok=False, message=…)`. **Check permissions yourself.** |
| `send_approvals_update(device_token, webapp_id)` | Silent push; the app reloads the feed immediately.                                                                                                                                                                                   |

## Urgent pushes and critical alerts: `send_critical_alert()`

`send_push(..., interruption_level="time-sensitive")` also gets through a
Focus mode and the scheduled summary, e.g. "Driver waiting at the
loading dock". This does not need approval from Apple.

For real emergencies (evacuation, severe weather, security incident) there are
critical alerts. They ring even with the mute switch on and in "Do Not
Disturb", and in the app they additionally appear full-screen:

```python
from bmsdna.app_native import send_critical_alert

sent, detail = await send_critical_alert(
    device_token=token,
    webapp_id="partner-tool",
    title="Evacuate Building A",
    body="Leave immediately via the east stairwell. Assembly point: car park P2.",
    acknowledge_label="I am safe",  # None = no acknowledge button
    data={"alert_id": "evac-2026-09-27"},
)
```

When the user taps the acknowledge button, the app reports it to
`create_notification_action_router()` with `action="acknowledge"` and your
`data` fields. That way you see who has seen the alert.

Critical alerts only take effect once Apple has granted the app the
entitlement. Until then,
the push arrives as a normal notification; the full-screen alarm in
the app and the acknowledgement still work. The user can
turn off critical alerts in the iOS settings at any time.
Use them only for real emergencies, otherwise Apple will reject the entitlement
or revoke it.

## Auth: `auth_dependency`

Every `create_*_router()` **requires** `auth_dependency`, a normal FastAPI
dependency that is added to every route of the router. It either raises
`HTTPException(401/403)` or returns the authenticated user, which arrives in
your callbacks as `context.user`. What it checks is up to you: a session
cookie, an `Authorization: Bearer` token, an API key. For the Entra ID token of
the app there is a ready-made dependency, see the next section.

```python
from fastapi import Header, HTTPException


async def require_user(authorization: str = Header(...)) -> dict:
    claims = verify_access_token(authorization.removeprefix("Bearer "))  # your code
    if claims is None:
        raise HTTPException(status_code=401)
    return claims  # arrives as `context.user`
```

Only for local development and tests there is an explicit opt-out,
`auth_dependency=insecure_no_auth`. Without a check, anyone who can reach
the endpoints can register devices, upload data and act on behalf of any user.

**Identity comes from `context.user`, not from the request body.** The
`user_email` fields in the payloads are what the app reports. They are
client input and anyone can send any address. Use them at most as a hint and
take the caller from your `auth_dependency`. The same goes for ids in the
payload (`approval_id`, `data` of a push action, `widget_id`): check that
`context.user` may act on them.

**What the app sends along:** For web apps with the `identity` capability, the
iOS app sends the Entra ID token of the user's sign-in as
`Authorization: Bearer <token>` with every native call to your backend (and
attaches it to the `fetch`/XHR calls of your page). Web apps without `identity`
(for example pages on SharePoint) get no token; for them the app forwards the
cookies of the web app's host, as long as `apiBaseURL` has the same host as
the web app.

## Sign-in with the Entra token: `create_entra_auth_dependency()`

The user signs in once in the app, and no web app asks again: your backend
checks the token and takes the user from it. Everything is configurable, nothing
is hard-wired.

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
    resolve_user=find_user,  # optional: map the identity to your own user
)

app.include_router(
    create_widget_feed_router(get_widgets=get_widgets, auth_dependency=require_user),
    prefix="/api",
)


@app.get("/api/me")  # the app's "check backend" call and your page's first call
async def me(user=Depends(require_user)):
    return {"email": user.email}
```

| Setting                    | Meaning                                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `ENTRA_TENANT_ID`          | Directory (tenant) ID, a GUID. `common` and similar are refused.                                              |
| `ENTRA_AUDIENCE`           | Client ID of the iOS app's registration (the `aud` of the token); several separated by commas.                |
| `SESSION_SECRET`           | Signs the session cookie. Random, at least 32 bytes. Your own variable name, passed to the cookie.            |
| `EntraTokenVerifier(...)`  | `leeway` (60 s), `jwks_cache_seconds` (1 h), `jwks_min_refresh_seconds` (60 s), `jwks_timeout_seconds` (10 s) |
| `SignedSessionCookie(...)` | `name` (`bms_session`), `max_age` (8 h), `same_site` (`lax`), `secure` (`True`)                               |

What the dependency answers:

| Request                                        | Answer                                                                           |
| ---------------------------------------------- | -------------------------------------------------------------------------------- |
| Valid token                                    | accepted, `context.user` is the `EntraUser` (`oid`, `email`, `name`), cookie set |
| Invalid, expired or foreign token              | **401**, no redirect. A valid cookie does not rescue an invalid token            |
| No token, valid session cookie                 | accepted                                                                         |
| Nothing                                        | 401                                                                              |
| Valid token, but `resolve_user` returns `None` | **403**                                                                          |
| Microsoft's signing keys cannot be loaded      | **503**                                                                          |

A token is the proof of **who** it is, not of what the user may do: roles and
permissions stay in your backend, and `resolve_user` is the place to look the
user up. The dependency also works for WebSocket routes (the iOS app sets the
header in the handshake; a browser cannot, see the guide).

Two things to know about the cookie: it is set through the response FastAPI builds
from your return value, so a route that returns a `Response` itself
(`JSONResponse`, `RedirectResponse`, `FileResponse`) must call
`copy_session_cookie(request, response)`; and a WebSocket handshake cannot set one.
Use another `SESSION_SECRET` for every environment.

[`docs/entra-token-guide.md`](../../docs/entra-token-guide.md) explains what is
checked, the cookie exchange, the limits in the web view, and how to migrate a
backend that has a cookie login today.

## Setting up APNs access

Once, in the Apple Developer Portal:

1. **Register an App ID**: Certificates, Identifiers & Profiles →
   Identifiers → "+" → App IDs. Enable the **Push Notifications**
   capability.
2. **Create an auth key (.p8)**: Certificates, Identifiers & Profiles → Keys
   → "+" → check "Apple Push Notifications service (APNs)" → generate the key
   and **download it once** (it cannot be downloaded again).
   Put it straight into a secret store (see below), not into the repo.
3. Set environment variables (`cp .env.example .env` for the local example,
   otherwise your backend's real environment variables):
   - `APNS_KEY` — contents of the `.p8` file. Line breaks may be
     written as `\n`. To put it on a single line for a local `.env`:
     `awk 'NF {printf "%s\\n", $0}' AuthKey.p8`
   - `APNS_KEY_ID` — the 10-character key ID from the portal
   - `APNS_TEAM_ID` — your team ID (Portal → Membership)
   - `APNS_BUNDLE_ID` — the app's bundle ID
   - `APNS_USE_SANDBOX` — `true` for debug builds from Xcode, `false` for
     TestFlight/App Store

### Storing the key in production

The `.p8` key applies to the whole Apple team, not just one app. Whoever
has it can send pushes to any device with one of our apps. Therefore:

- **Storage:** Only in a secret store (e.g. Azure Key Vault), never in the
  repo, in plain-text pipeline variables or in chats. The backend
  gets it as `APNS_KEY` from the secret store, e.g. via a
  Key Vault reference in the app settings and a managed identity.
- **Access:** Only the backends that send pushes get read access
  to the secret (to the individual secret, not the whole store). People only need it
  for rotation.
- **Few keys:** Apple allows only two active APNs keys per team. All
  backends therefore share the same key. Every new backend that
  gets it is a deliberate decision.
- **Rotation** (if a leak is suspected, when people with access leave):
  1. Generate a second key in the Developer Portal.
  2. Store it in the secret store as a new version of the secret, update `APNS_KEY_ID`
     in all backends and restart them.
  3. Only once all backends send with the new key, revoke the old key in the
     portal. Device tokens remain valid; the apps notice
     nothing.
- **Not secret** are `APNS_KEY_ID`, `APNS_TEAM_ID` and `APNS_BUNDLE_ID`.
  Without the key they are of no use to anyone.

## Local example & tests

[`example/main.py`](example/main.py) shows the routers and send functions
end-to-end with in-memory storage (no Postgres/Docker
needed):

```bash
cp .env.example .env   # fill in APNs values
uv run --group dev granian --interface asgi example.main:app --port 8000 --reload
```

```bash
curl -X POST http://localhost:8000/api/devices \
  -H "Content-Type: application/json" \
  -d '{"device_id": "abc", "push_token": "<real-apns-token>"}'

curl -X POST "http://localhost:8000/api/notify/abc?title=Hello&body=Test"
curl -X POST "http://localhost:8000/api/notify/abc/order-request?order_id=123"
curl -X POST "http://localhost:8000/api/notify/abc/refresh"
```

Tests (fake callbacks, no real APNs credentials needed):

```bash
uv run python -m pytest
```

## License

[MIT](LICENSE)
