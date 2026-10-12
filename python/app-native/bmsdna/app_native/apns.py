"""APNs delivery via aioapns (HTTP/2 + JWT auth key, async-native).

Credentials come from, in this order per send: the explicit `config=`
argument, the provider registered with `set_apns_config_provider`, the
`APNS_*` environment variables. Clients are cached per credential set, so a
changed key is picked up on the next send without a restart.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from aioapns import APNs, NotificationRequest
from aioapns.common import PushType

if TYPE_CHECKING:
    from .widgets import Widget

#: Error descriptions (`aioapns`' `NotificationResult.description`, Apple's
#: `reason` field) that make a device token *permanently* invalid — unlike
#: transient errors (e.g. rate limiting), a retry is pointless here.
#: `"BadDeviceToken"` usually means a wrong format or a sandbox/production
#: mix-up, `"Unregistered"` practically always means the app was
#: uninstalled. Check `detail in PERMANENTLY_INVALID_TOKEN_REASONS` after a
#: failed `send_push`/`send_silent_push` and delete the device (or at least
#: its `push_token`) from your own storage — otherwise your device list keeps
#: growing without bound with dead entries that will never be delivered
#: successfully again.
PERMANENTLY_INVALID_TOKEN_REASONS = frozenset({"BadDeviceToken", "Unregistered"})


def _normalize_key(raw: str | None, name: str) -> str:
    """PEM text of an APNs auth key (.p8). Line breaks may be written as
    `\\n`, because many environments don't allow multi-line values."""
    key = (raw or "").replace("\\n", "\n").strip()
    if not key:
        raise RuntimeError(f"APNs is not configured. {name} is missing (see README).")
    if not key.startswith("-----BEGIN PRIVATE KEY-----"):
        raise RuntimeError(
            f"{name} is not PEM text (expected: -----BEGIN PRIVATE KEY-----, "
            "i.e. the contents of the .p8 file, not its path)."
        )
    return key


@dataclass(frozen=True)
class ApnsConfig:
    """APNs credentials for one send, e.g. loaded from a database.

    `key` is the PEM text of the `.p8` file (`\\n` escapes are accepted).
    It is excluded from `repr`, so a config can be logged safely.
    """

    key: str = field(repr=False)
    key_id: str
    team_id: str
    bundle_id: str
    use_sandbox: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _normalize_key(self.key, "ApnsConfig.key"))
        for name in ("key_id", "team_id", "bundle_id"):
            if not getattr(self, name):
                raise RuntimeError(f"APNs is not configured. ApnsConfig.{name} is empty.")


ApnsConfigProvider = Callable[[], Awaitable[ApnsConfig]]

_config_provider: ApnsConfigProvider | None = None

#: One client per credential set. The key enters the cache key only as a
#: SHA-256 digest.
_clients: dict[tuple[str, str, str, bool, str], APNs] = {}


def set_apns_config_provider(provider: ApnsConfigProvider | None) -> None:
    """Registers an async function that returns the `ApnsConfig` to use. It
    is called before every send (so it should be cheap, e.g. cache for a few
    seconds), which lets an admin change the key at runtime. An explicit
    `config=` still wins; `None` removes the provider again (environment
    variables apply)."""
    global _config_provider
    _config_provider = provider


def _load_key() -> str:
    """Contents of the APNs auth key (.p8) from `APNS_KEY`.

    The PEM text is stored directly in the variable (in production via a
    Key Vault reference in the App Service settings).
    """
    return _normalize_key(os.environ.get("APNS_KEY"), "APNS_KEY")


def _env_config() -> ApnsConfig:
    key_id = os.environ.get("APNS_KEY_ID")
    team_id = os.environ.get("APNS_TEAM_ID")
    bundle_id = os.environ.get("APNS_BUNDLE_ID")

    if not (key_id and team_id and bundle_id):
        raise RuntimeError(
            "APNs is not configured. Pass config=, register set_apns_config_provider(), "
            "or set APNS_KEY, APNS_KEY_ID, APNS_TEAM_ID and APNS_BUNDLE_ID as "
            "environment variables (see README)."
        )

    return ApnsConfig(
        key=_load_key(),
        key_id=key_id,
        team_id=team_id,
        bundle_id=bundle_id,
        use_sandbox=os.environ.get("APNS_USE_SANDBOX", "true").lower() == "true",
    )


async def _resolve_config(config: ApnsConfig | None = None) -> ApnsConfig:
    if config is not None:
        return config
    if _config_provider is not None:
        return await _config_provider()
    return _env_config()


def _client_for(config: ApnsConfig) -> APNs:
    digest = hashlib.sha256(config.key.encode()).hexdigest()
    cache_key = (config.key_id, config.team_id, config.bundle_id, config.use_sandbox, digest)
    client = _clients.get(cache_key)
    if client is None:
        # Drop clients that used an older key for the same app.
        for stale in [k for k in _clients if k[1:4] == cache_key[1:4]]:
            del _clients[stale]
        client = APNs(
            key=config.key,
            key_id=config.key_id,
            team_id=config.team_id,
            topic=config.bundle_id,
            use_sandbox=config.use_sandbox,
        )
        _clients[cache_key] = client
    return client


async def _deliver(
    request: NotificationRequest, config: ApnsConfig | None
) -> tuple[bool, str | None]:
    client = _client_for(await _resolve_config(config))
    response = await client.send_notification(request)
    return response.is_successful, getattr(response, "description", None)


def live_activity_topic(config: ApnsConfig | None = None) -> str:
    """APNs topic for Live Activity pushes: bundle ID plus
    `.push-type.liveactivity` (see `live_activities.py`). The bundle ID comes
    from `config`, otherwise from `APNS_BUNDLE_ID` (a provider is async and
    not consulted here)."""
    bundle_id = config.bundle_id if config is not None else os.environ.get("APNS_BUNDLE_ID")
    if not bundle_id:
        raise RuntimeError("APNS_BUNDLE_ID is not set (see README).")
    return f"{bundle_id}.push-type.liveactivity"


#: How strongly a push interrupts the user (Apple's `interruption-level`):
#:
#: - `"passive"`: silent, only lands in Notification Center.
#: - `"active"`: normal (default).
#: - `"time-sensitive"`: also breaks through a Focus mode or a scheduled
#:   summary. For urgent things that can't wait.
#: - `"critical"`: critical alert, rings even with the mute switch on and
#:   "Do Not Disturb". Only for real emergencies (evacuation, safety),
#:   preferably via `send_critical_alert`. Only takes effect once Apple has
#:   granted the app the entitlement; until then the push arrives as a
#:   normal one.
InterruptionLevel = Literal["passive", "active", "time-sensitive", "critical"]


def build_alert_message(
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    interruption_level: InterruptionLevel | None = None,
    critical_volume: float = 1.0,
) -> dict[str, Any]:
    """Pure payload construction, extracted separately from `send_push` so
    it can be tested without APNs credentials."""
    aps: dict[str, Any] = {"alert": {"title": title, "body": body}, "sound": "default"}
    if interruption_level is not None:
        aps["interruption-level"] = interruption_level
    if interruption_level == "critical":
        # Critical sound: rings even with the mute switch on, at this
        # volume (0.0 to 1.0).
        aps["sound"] = {
            "critical": 1,
            "name": "default",
            "volume": min(max(critical_volume, 0.0), 1.0),
        }

    message: dict[str, Any] = {"aps": aps}
    if data:
        message.update(data)
    return message


async def send_push(
    *,
    device_token: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    interruption_level: InterruptionLevel | None = None,
    config: ApnsConfig | None = None,
) -> tuple[bool, str | None]:
    """The actual "one-call" push: call it directly from your own code as
    soon as you have an APNs device token (from your own storage — see
    `create_ingest_router`).

    Returns (successful, error description) instead of raising — if you call
    this for several devices in a loop, a single failure shouldn't stop the
    others.

    For a deep link when the notification is tapped: pass
    `data={"path": "/orders/123"}` — the iOS app reads `path` from the
    notification user info and navigates there in the WebView (relative to
    `webAppURL`).

    For confirm/reject buttons that the user can tap in the notifications
    tab of the iOS app (without the app having to know about them
    beforehand): pass
    `data={"actions": [{"id": "confirm", "title": "Confirm"},
    {"id": "reject", "title": "Decline"}]}`.
    When the user taps one, its `id` arrives as `action` in
    `create_notification_action_router()`, together with the remaining
    `data` fields of this push (e.g. an order ID). There are **no** buttons
    directly on the system banner/Lock Screen — for that, iOS would require
    the app to know and register this category beforehand, which would need
    an App Store release for every new action.

    For urgent things that should also break through a Focus mode:
    `interruption_level="time-sensitive"` (see `InterruptionLevel`). For
    real emergencies there is `send_critical_alert`.

    On `sent=False`: check whether `detail in PERMANENTLY_INVALID_TOKEN_REASONS`
    — if so, the token is permanently dead (usually an uninstall) and should
    be removed from your storage instead of being retried next time.

    `config` overrides the APNs credentials for this call (see
    `ApnsConfig`, `set_apns_config_provider`); all `send_*` functions take it.
    """
    message = build_alert_message(
        title=title, body=body, data=data, interruption_level=interruption_level
    )

    request = NotificationRequest(device_token=device_token, message=message)
    return await _deliver(request, config)


async def send_silent_push(
    *, device_token: str, data: dict[str, Any] | None = None, config: ApnsConfig | None = None
) -> tuple[bool, str | None]:
    """Silent push (`content-available`, no banner/sound) — briefly wakes the
    app in the background, e.g. to reload the WebView before the user opens
    the app.

    Two things throttle this automatically, so you don't accidentally drain
    the battery:
    - **iOS itself** only delivers silent pushes "best effort" (no real-time
      guarantee, the system may delay/drop delivery, depending among other
      things on usage patterns).
    - The **iOS app additionally throttles on the client side**
      (default 15 minutes) — if
      several silent pushes arrive in quicker succession, the
      surplus ones are ignored instead of reloading the WebView every time.

    If your backend itself sends very frequently (e.g. on every record
    update), you should still throttle on the server side yourself (e.g. "at
    most every X minutes per device") — the toolkit deliberately keeps no
    state for this, that would be your own storage.

    On `sent=False`: see `PERMANENTLY_INVALID_TOKEN_REASONS` — for a
    permanently invalid reason, a retry is pointless.
    """
    message: dict[str, Any] = {"aps": {"content-available": 1}}
    if data:
        message.update(data)

    request = NotificationRequest(
        device_token=device_token,
        message=message,
        push_type=PushType.BACKGROUND,
        priority=5,
    )
    return await _deliver(request, config)


#: Upper limit for widgets sent directly in the push. APNs allows 4 KB per
#: payload, the rest is headroom for `aps` and `webapp_id`. Larger updates
#: are automatically sent by `send_widget_update` as a plain
#: `widgets_refresh`, and the app then fetches the feed itself.
MAX_INLINE_WIDGETS_BYTES = 3500


def build_widget_update_message(
    *, webapp_id: str, widgets: Sequence[Widget] | None = None
) -> dict[str, Any]:
    """Pure payload construction for `send_widget_update`, testable without
    APNs credentials."""
    from .widgets import dump_widgets

    message: dict[str, Any] = {"aps": {"content-available": 1}, "webapp_id": webapp_id}
    if widgets is not None:
        inline = {**message, "widgets": dump_widgets(widgets)}
        size = len(json.dumps(inline, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size <= MAX_INLINE_WIDGETS_BYTES:
            return inline
    message["widgets_refresh"] = True
    return message


async def send_widget_update(
    *,
    device_token: str,
    webapp_id: str,
    widgets: Sequence[Widget] | None = None,
    config: ApnsConfig | None = None,
) -> tuple[bool, str | None]:
    """Updates your web app's dashboard widgets on a device via silent push,
    without a banner and without your web app having to be open.

    - **With `widgets`**: The widgets are sent directly in the push and
      replace ALL widgets of your web app on the device. This is the same as
      your feed, so always send the complete list, not just the changed
      widget. If the list doesn't fit into a push
      (`MAX_INLINE_WIDGETS_BYTES`), only a feed fetch is triggered
      automatically.
    - **Without `widgets`**: The app reloads your feed
      (`create_widget_feed_router`) immediately. This requires the feed path
      to be configured in the app (`widgetFeedPath`).

    `webapp_id` is the `id` of your web app in the app. The app only
    accepts widgets from web apps that have `.dashboardWidgets`
    enabled.

    iOS only delivers silent pushes "best effort". For guaranteed up-to-date
    data the feed remains the source; the app fetches it anyway every time
    it returns to the foreground. Return value and error handling as for
    `send_silent_push`.
    """
    message = build_widget_update_message(webapp_id=webapp_id, widgets=widgets)
    data = {key: value for key, value in message.items() if key != "aps"}
    return await send_silent_push(device_token=device_token, data=data, config=config)


def build_critical_alert_message(
    *,
    webapp_id: str,
    title: str,
    body: str,
    acknowledge_label: str | None = "Got it",
    volume: float = 1.0,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure payload construction for `send_critical_alert`, testable without
    APNs credentials."""
    extra: dict[str, Any] = {**(data or {}), "webapp_id": webapp_id}
    if acknowledge_label:
        extra["ack_label"] = acknowledge_label
    return build_alert_message(
        title=title,
        body=body,
        data=extra,
        interruption_level="critical",
        critical_volume=volume,
    )


async def send_critical_alert(
    *,
    device_token: str,
    webapp_id: str,
    title: str,
    body: str,
    acknowledge_label: str | None = "Got it",
    volume: float = 1.0,
    data: dict[str, Any] | None = None,
    config: ApnsConfig | None = None,
) -> tuple[bool, str | None]:
    """Critical alert for real emergencies (evacuation, severe weather,
    security incident): rings even with the mute switch on and "Do Not
    Disturb", and additionally appears full-screen in the app.

    With `acknowledge_label` (e.g. "I am safe") the app shows a confirm
    button. When the user taps it, this arrives as
    `action="acknowledge"` in `create_notification_action_router()`,
    together with your `data` fields (e.g. pass an `alert_id`). This way
    you see who has seen the alert. `None` hides the button.

    The app side needs Apple's entitlement for critical alerts (see
    README). Until then the push arrives as a normal notification; the
    acknowledgement in the app still works. Return value and error
    handling as for `send_push`.
    """
    message = build_critical_alert_message(
        webapp_id=webapp_id,
        title=title,
        body=body,
        acknowledge_label=acknowledge_label,
        volume=volume,
        data=data,
    )
    request = NotificationRequest(device_token=device_token, message=message)
    return await _deliver(request, config)


def build_approvals_update_message(*, webapp_id: str) -> dict[str, Any]:
    """Pure payload construction for `send_approvals_update`, testable
    without APNs credentials."""
    return {
        "aps": {"content-available": 1},
        "webapp_id": webapp_id,
        "approvals_refresh": True,
    }


async def send_approvals_update(
    *, device_token: str, webapp_id: str, config: ApnsConfig | None = None
) -> tuple[bool, str | None]:
    """Makes the app reload your web app's pending approvals immediately
    (`create_approvals_router`), via silent push without a banner. E.g. when
    a new request comes in or someone else has handled one.

    For a visible notification ("New vacation request from Anna") you
    additionally send a normal `send_push`. iOS only delivers silent pushes
    "best effort"; the app reloads the feed anyway every time it returns to
    the foreground. Return value and error handling as for
    `send_silent_push`.
    """
    message = build_approvals_update_message(webapp_id=webapp_id)
    data = {key: value for key, value in message.items() if key != "aps"}
    return await send_silent_push(device_token=device_token, data=data, config=config)
