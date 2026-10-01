# Live Activities for web app developers

A **Live Activity** shows an ongoing process prominently on the
Lock Screen and in the Dynamic Island, e.g.:

- "Order is being packed" → "Ready for pickup, counter 3"
- a countdown to pickup or to the next appointment
- the progress of a job in named steps

Unlike a notification, it stays in place and **updates itself** without
a new notification arriving. The layout is native and the same for all web apps;
you only supply the data.

Backend side:
[`python/app-native/bmsdna/app_native/live_activities.py`](../python/app-native/bmsdna/app_native/live_activities.py).

## Prerequisites

- The app must have the `.liveActivities` capability enabled for your web app.
  Without it, the app rejects all calls and does not report
  any tokens to you.
- iOS 16.2 or later. Starting via push without the app requires iOS 17.2 or later.
- The user can turn off Live Activities in the app's iOS settings.
  In that case `startLiveActivity` responds with `"disabled"`.

## Limits (imposed by iOS)

- An activity runs for **at most 8 hours**. After that, iOS ends it, and
  it stays on the Lock Screen for up to 4 more hours. Intended
  for processes with a beginning and an end, not for permanent information (for that there is the
  [web app widget](dashboard-widgets-guide.md)).
- About **4 KB** per update. Only text, numbers and SF Symbols, no images.
- iOS eventually throttles updates with priority 10. So send unimportant
  intermediate states with `priority=5`.

## Flow

| Step            | How                                                                                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Start**       | From the open web app: `BMSNative.call('startLiveActivity', …)`. From iOS 17.2, also without the app: `send_live_activity_start()` with the push-to-start token.   |
| **Store token** | For every activity, the app reports its push token to `POST <apiBaseURL>/<liveActivityPath>` (default `api/live-activities`, see `create_live_activity_router()`). |
| **Update**      | From the web app: `updateLiveActivity`. From the backend: `send_live_activity_update()` with the token.                                                            |
| **End**         | From the web app: `endLiveActivity`. From the backend: `send_live_activity_end()`. If the user swipes it away, the app reports `ended`.                            |

## State format (`state`)

Only `title` is required:

```jsonc
{
  "title": "Order is being packed", // main line
  "subtitle": "Zürich branch · Counter 3", // second line
  "status": "Packed", // short, for the compact Dynamic Island
  "progress": 0.5, // 0…1 as a bar, OR:
  "steps": ["Ordered", "Packed", "Ready for pickup"], // at most 5 steps
  "currentStep": 1, // index into steps, 0-based
  "timerEnd": "2026-09-27T14:30:00Z", // countdown (bridge: ISO or Unix seconds)
  "icon": "checkmark.circle.fill", // SF Symbol for this state only
  "tint": "#2e7d32", // color for this state only
}
```

The countdown is shown at the top right, otherwise `status`. Below it come the
steps, otherwise the bar from `progress`.

## JS bridge

```js
// Start (if the id already exists, it is updated)
await BMSNative.call('startLiveActivity', {
  id: 'A-123',                 // your id, e.g. the order number
  state: { title: 'Order is being packed', steps: ['Ordered', 'Packed', 'Ready for pickup'], currentStep: 0 },
  icon: 'shippingbox',         // default: your web app's icon
  tint: '#2e4a62',             // default: BMS red
  path: '/orders/A-123',       // a tap opens your web app here
  staleAt: '2026-09-27T18:00:00Z', // optional: from then on the state counts as outdated
});

// New state, additionally highlighted with alert (sound, Dynamic Island expands)
await BMSNative.call('updateLiveActivity', {
  id: 'A-123',
  state: { title: 'Ready for pickup', status: 'Ready', steps: [...], currentStep: 2 },
  alert: { title: 'Ready for pickup', body: 'Counter 3' },
});

// End: dismiss "immediate", an ISO timestamp, or omit it (iOS default)
await BMSNative.call('endLiveActivity', { id: 'A-123', state: { title: 'Picked up' }, dismiss: 'immediate' });

// Running activities of your web app: {ok: true, ids: ['A-123']}
const { ids } = await BMSNative.call('getLiveActivities');
```

Possible errors (`{ok: false, error}`): `capability`, `disabled` (turned off
by the user), `invalid` (missing `id` or `state.title`), `notFound`,
`failed` (e.g. too many simultaneous activities).

## Backend (toolkit)

```python
from bmsdna.app_native import (
    LiveActivityState,
    LiveActivityTokenReceived,
    WidgetRequestContext,
    create_live_activity_router,
    send_live_activity_end,
    send_live_activity_update,
)


async def on_token(body: LiveActivityTokenReceived, context: WidgetRequestContext) -> None:
    if body.event == "token":  # token of an activity (may change)
        await db.save_activity_token(body.device_id, body.activity_id, body.push_token)
    elif body.event == "push_to_start_token":  # one token per device, iOS 17.2 and later
        await db.save_start_token(body.device_id, body.push_token)
    elif body.event == "ended":
        await db.delete_activity_token(body.device_id, body.activity_id)


app.include_router(
    create_live_activity_router(
        on_token_received=on_token,
        auth_dependency=require_user,  # your own login check
    ),
    prefix="/api",
)

# Somewhere in your code:
await send_live_activity_update(
    push_token=token,
    state=LiveActivityState(
        title="Ready for pickup", steps=["Ordered", "Packed", "Ready for pickup"], current_step=2
    ),
    alert_title="Ready for pickup",
)
await send_live_activity_end(push_token=token, dismiss_at=datetime.now(UTC) + timedelta(minutes=30))
```

Starting without the app (iOS 17.2 and later):

```python
from bmsdna.app_native import LiveActivityAttributes, send_live_activity_start

await send_live_activity_start(
    push_to_start_token=start_token,
    attributes=LiveActivityAttributes(
        webapp_id="partner-tool",
        activity_id="A-123",
        webapp_name="Partner-Tool",
        path="/orders/A-123",
    ),
    state=LiveActivityState(title="Order received", steps=[...], current_step=0),
)
```

After that, the app reports the new activity's token as a `token` event; only
then do updates work. `webapp_id` must be your web app's `id` in the app.

The pushes go out with `apns-push-type: liveactivity` to the topic
`<APNS_BUNDLE_ID>.push-type.liveactivity`. The toolkit takes care of this; the
same APNs key as for normal pushes is sufficient.

## Trying it out

A local backend is in
[`python/app-native/example/main.py`](../python/app-native/example/main.py):
`POST /api/orders/A-123/advance` moves an activity with the `id` `A-123`
forward one step, as soon as the app has reported its token.
