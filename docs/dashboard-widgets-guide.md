# Dashboard widgets for web app developers

The app's Home tab is a **native dashboard**. Every web app can place
widgets on it, similar to widgets on the iPhone Home Screen:

- Key figures
- Statistics
- Lists
- Charts
- Progress
- Text
- **News** with cover image, title and teaser, optionally straight from
  SharePoint (see [News from SharePoint](#news-from-sharepoint-without-a-backend))
- **Actions**, i.e. buttons and small forms that trigger your backend
  directly, without the user opening your web app

The responsibilities are split like this:

| Who                    | What                                                                                                                          |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **You (web app team)** | Which widgets exist, their content, whether they are required, what a button does. All declarative as JSON, all in your code. |
| **iOS app**            | Rendering, permission (`.dashboardWidgets`), order and visibility per user, Face ID confirmation, confirmation prompts.       |

New widgets or changed content do **not require an app update**.

Backend side:
[`python/app-native/bmsdna/app_native/widgets.py`](../python/app-native/bmsdna/app_native/widgets.py).

## Look: tiles like iOS widgets

Widgets appear as tiles in the style of iOS Home Screen widgets, with
strongly rounded corners and fixed sizes in a two-column grid:

| `size`   | Tile                                      | Good for                                     |
| -------- | ----------------------------------------- | -------------------------------------------- |
| `small`  | square, half width (two side by side)     | one key figure, progress, 1–2 stat values    |
| `medium` | full width, same height as `small`        | stats row, short list, small chart, action   |
| `large`  | full width, double height (2 × 2)         | charts, longer lists, longer texts, news     |
| `tall`   | full width, four times the height (2 × 4) | four news posts with cover image, long lists |
| `xlarge` | full width, six times the height (2 × 6)  | long content, especially a news feed         |

**Layout:** The tiles appear in the order the user has set. Small tiles
fill the rows in pairs so that no gap is left:

- If a `small` tile is not followed by a second one, **the next `small`
  tile** further down **moves up**. The order of the small tiles among
  themselves stays the same.
- If a `small` tile is left completely on its own, it is **stretched** to
  full width and rendered like `medium`, e.g. with your web app's name in
  the header and, for `stats`, with all values side by side.

The tile **never** grows with its content. Whatever does not fit is
truncated:

| Kind                                  | `small`                 | `medium`               | `large`          | `tall`           | `xlarge`         |
| ------------------------------------- | ----------------------- | ---------------------- | ---------------- | ---------------- | ---------------- |
| List (without / with buttons per row) | 2 / 1 row               | 2 / 1 row              | 5 / 3 rows       | 10 / 6 rows      | 16 / 10 rows     |
| Stats                                 | 2 values                | up to 4 side by side\* | up to 4 as 2×2\* | like `large`     | like `large`     |
| Text                                  | approx. 5 lines         | approx. 4 lines        | approx. 13 lines | approx. 28 lines | approx. 44 lines |
| Action (buttons)                      | 1                       | 2                      | 3                | 3                | 3                |
| News                                  | latest post, title only | 1 post                 | 2 posts\*\*      | 4 posts\*\*      | 6 posts\*\*      |

\*\* For news, the tile is then as tall as its content, not as the grid.

\* As with `kpi`, the values sit at the bottom of the tile, with large
numbers in wide tiles. Labels stay on a single line. If the values do not
fit side by side (long labels, large text size on the device), the numbers
get smaller, and as a last resort the row can be scrolled horizontally.

For lists with more entries, the tile shows the total count in the header;
a tap on the header opens your web app at the widget `path`. Prefer
delivering a few meaningful entries.

## Prerequisite: capability

The app must have the `.dashboardWidgets` capability enabled for your web
app. For each web app, the app stores these paths:

| Field               | Default              | Purpose                                               |
| ------------------- | -------------------- | ----------------------------------------------------- |
| `widgetFeedPath`    | –                    | Feed (recommended), relative to `apiBaseURL` or a URL |
| `widgetActionPath`  | `api/widget-actions` | Button taps                                           |
| `widgetOptionsPath` | `api/widget-options` | Search fields and remote fields                       |

Without `.dashboardWidgets`, the app discards all widgets of this web app,
no matter how they arrive. Nothing else is needed in the app.

## Three ways onto the dashboard

| Way                       | When                                               | How                                                                                                                                                                                            |
| ------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Feed** (recommended) | Always, even if your web app has never been opened | The app fetches `GET <apiBaseURL>/<widgetFeedPath>?device_id=…` itself: on launch, when returning to the foreground, after SSO login, via pull-to-refresh, and at most every 60 s per web app. |
| **2. Push**               | Immediately, when something changes in the backend | Silent push via `send_widget_update()` from the toolkit: either with the widgets in the push or as an instruction to reload the feed.                                                          |
| **3. JS bridge**          | Live, while your web app is open                   | `BMSNative.call('setWidgets', {widgets: [...]})` from the web page.                                                                                                                            |

All three use **the same format** and each **replaces all widgets of your
web app**. So a widget that is no longer delivered disappears. Exceptions
are `updateWidget` and `removeWidgets` (bridge) as well as `widget` in the
action response (see below). The app stores the last state, so after a
restart the dashboard is filled immediately.

> The JS bridge alone is not enough: a WKWebView only exists once the user
> opens your web app. Use it for live updates while the user is in your web
> app anyway, and the feed as the actual source.

### 1. Feed (toolkit)

```python
from bmsdna.app_native import KpiData, KpiWidget, WidgetRequestContext, create_widget_feed_router


async def get_widgets(context: WidgetRequestContext):
    user = context.user  # return value of your auth_dependency
    return [
        KpiWidget(
            id="open-orders",
            title="Open orders",
            icon="shippingbox",
            data=KpiData(value=await count_open_orders(user), unit="pcs"),
        ),
    ]


app.include_router(
    create_widget_feed_router(get_widgets=get_widgets, auth_dependency=require_user),
    prefix="/api",
)
```

The app authenticates the call: web apps with the `identity` capability get the
Entra token of the app's sign-in as `Authorization: Bearer …` (see
[entra-token-guide.md](entra-token-guide.md)), the others the cookie of their
origin (only if `url` and `apiBaseURL` have the same host). Your
`auth_dependency` decides what it accepts, see the README of the Python package.
On 401/403 the app clears your widgets (and the copy of the token for the Home Screen
widgets) and shows a note to open the web app. A web app that signs in with a cookie
first gets one invisible sign-in and a retry before the note appears; a web app with
`identity` does not: a 401 means the backend did not accept the token. If
the feed responds with 404, the app shows no error: your web app simply
has no widgets. For other errors, the last known widgets stay in place,
and a short notice appears at the bottom of the dashboard.

Your own backend without the toolkit? Then simply return
`{"schema": 1, "widgets": [...]}` or a bare array in the format below.

### 2. Push (toolkit)

```python
from bmsdna.app_native import send_widget_update

# Send the new list right away (replaces all widgets of your web app):
await send_widget_update(
    device_token=token, webapp_id="partner-tool", widgets=await build_widgets(user)
)

# Or just trigger a feed fetch:
await send_widget_update(device_token=token, webapp_id="partner-tool")
```

If the list is larger than a push allows (about 3.5 KB), the toolkit
automatically turns it into a plain feed fetch. iOS delivers silent pushes
only on a "best effort" basis, so the feed remains the reliable source. By
the way, unlike `send_silent_push()`, a widget push does **not** reload
your web app's WebView.

### 3. JS bridge

```js
// Replace all widgets of this web app. Response: {ok, accepted, rejected}
const result = await BMSNative.call('setWidgets', {
  widgets: [
    /* … */
  ],
})

// Replace/append one widget (same id)
await BMSNative.call('updateWidget', {
  widget: { id: 'open-orders', kind: 'kpi', data: { value: 13 } },
})

// Remove individual widgets or all of them (without ids)
await BMSNative.call('removeWidgets', { ids: ['open-orders'] })

// Reload the feed natively right away (e.g. after the page has saved something)
await BMSNative.call('refreshWidgets')
```

Without `.dashboardWidgets`, all four respond with
`{ok: false, error: "capability"}`. Please send dates as ISO strings, not
as JS `Date`.

## Format (schema v1)

```jsonc
{
  "id": "open-orders", // Required, unique within your web app, no "/". Keep it stable!
  "kind": "kpi", // Required: kpi | stats | list | chart | progress | text | action | news
  "size": "small", // small (half width) | medium | large | tall | xlarge (full width). Default depends on kind
  "title": "Open orders",
  "icon": "shippingbox", // SF Symbol, default: your web app's icon
  "tint": "#2e4a62", // Default: your web app's color
  "required": false, // Required widget: the user cannot hide it
  "defaultEnabled": true, // Initial state until the user makes a choice
  "path": "/orders", // Tap opens your web app here (default: start page)
  "updatedAt": "2026-09-24T08:00:00Z",
  "expiresAt": "2026-09-24T12:00:00Z", // afterwards grey + "Outdated"
  "data": {
    /* depends on kind, see below */
  },
}
```

The app discards invalid widgets **individually** (unknown `kind`, missing
required fields); the rest is still shown. The toolkit models validate the
same format in the backend already. Use them, so errors show up on your
side instead of silently on the device. A maximum of 20 widgets per web app
is allowed.

Numbers can be sent as a number (`12`, which the app formats according to
the device language) or as a pre-formatted string (`"CHF 1'200"`).

### `kpi` – key figure (default `small`)

```json
{
  "value": 12,
  "unit": "pcs",
  "caption": "3 of them overdue",
  "trend": { "direction": "up", "text": "+3", "positive": false }
}
```

`trend.direction`: `up` | `down` | `flat`. `positive` says whether the
direction is good (green) or bad (red). Default: rising is good.

### `stats` – 2 to 4 key figures (default `medium`)

```json
{
  "items": [
    { "label": "Visits", "value": 14, "trend": { "direction": "up", "text": "+2" } },
    { "label": "Quotes", "value": 6 }
  ]
}
```

### `list` – list, optionally with buttons per row (default `medium`)

```json
{
  "maxVisible": 3,
  "emptyText": "All done",
  "items": [
    {
      "id": "A-1001",
      "title": "Expenses M. Keller",
      "subtitle": "Trip to Zürich",
      "trailing": "CHF 240",
      "icon": "creditcard",
      "path": "/approvals/A-1001",
      "actions": [
        { "id": "approve", "label": "Approve" },
        {
          "id": "reject",
          "label": "Reject",
          "style": "destructive",
          "confirm": "Really reject?"
        }
      ]
    }
  ]
}
```

The row `id` is required and is passed as `item_id` on a button tap. At
most 2 buttons are shown per row, one in the small tile. How many rows are
visible depends on the tile size (see
[Look](#look-tiles-like-ios-widgets)). `maxVisible` can only restrict this
further. Icon and `trailing` are omitted in the small tile.

### `chart` – chart (default `medium`, works well as `large`)

```json
{
  "type": "bar",
  "unit": "CHF k",
  "series": [
    {
      "name": "2026",
      "points": [
        { "x": "Jan", "y": 42 },
        { "x": "Feb", "y": 51 }
      ]
    },
    {
      "name": "2025",
      "color": "#9aa5b1",
      "points": [
        { "x": "Jan", "y": 38 },
        { "x": "Feb", "y": 44 }
      ]
    }
  ]
}
```

`type`: `bar` | `line` | `area`. With multiple series, a legend appears.

### `progress` – progress (default `small`)

```json
{ "value": 68000, "total": 100000, "caption": "CHF revenue", "style": "ring" }
```

`style`: `bar` (default) | `ring`.

### `text` – notice/info (default `medium`)

```json
{
  "markdown": "On **Friday** the warehouse is closed from _2 pm_.",
  "linkLabel": "Learn more"
}
```

Only inline Markdown is allowed (bold, italic, links). `linkLabel` opens
your web app at the widget `path`.

### `news` – posts with cover image (default `large`)

```json
{
  "emptyText": "No news yet",
  "items": [
    {
      "id": "42",
      "title": "New location in Winterthur",
      "text": "From October, we are also represented in Eastern Switzerland.",
      "imageUrl": "/SiteAssets/location.jpg",
      "path": "/SitePages/New-Location.aspx",
      "date": "2026-09-20T08:00:00Z",
      "channels": ["Locations"]
    }
  ]
}
```

Newest first. Each row shows cover image, date (and `caption`), title and
teaser, with a chevron on the right. A tap opens the full post (`path`,
relative to your web app or as a full URL); a tap on the tile's header
opens the overview at the widget `path`.

From `large` upwards, the news tile shows a fixed **number** of posts (2, 4 or 6) and is exactly as tall as its content instead of filling the grid height.
The grid grows with the screen width; with a fixed height, there was empty
space at the bottom on large iPhones.

`imageUrl` can be absolute or relative to your web app. If the image is on
your web app's host and your web app signs in with a cookie (no `identity`
capability), the app sends the cookie along, so protected images work. With
`identity` the app sends **neither cookie nor token** to your web app's host for
images: they must load without sign-in. (Images on a SharePoint site that the web app
uses for its news still get the SharePoint cookie.) The app downsizes the images and caches them; still, do not
send huge originals. Without an image, a placeholder in your color
appears.

For news, the **user** chooses the number themselves (long press on the
tile › Number of posts: 2, 4 or 6). Your `size` (`large`/`tall`/`xlarge`)
is only the initial value.

**Channels:** If posts have `channels` (or, for short, `"channel": "IT"`),
the tile gets **tabs** at the top from 2 × 2 upwards: "All" plus one per
channel. The selected tab is remembered. The Home Screen widget has its
own tabs that switch directly within the widget.

Channels can be **subscribed to** (bell to the right of the tabs, or long
press › "Subscribe to channels …"). New posts in subscribed channels
appear as notifications, land in the Notifications tab and open the post
when tapped.
This works without a backend: after every fetch, the app compares which
posts are new, including via background fetch (`BGAppRefreshTask`). New
means: `id` not seen before and at most 3 days old. On the very first
fetch, everything counts as known. More than 3 new posts at once are
combined into a single summary notification.

> **Limit without a server:** iOS decides when the background fetch runs,
> typically every few hours. Once the app has been closed by swiping it
> away, it no longer runs at all. For notifications within seconds you need
> a real push: a backend (e.g. triggered via the Power Automate trigger
> "When an item is created" on "Site Pages") then sends
> `send_push(..., data={"webapp_id": ..., "path": ...})` to the devices that
> have subscribed to the channel. For that, the app would have to report
> the subscriptions to this backend.

### News from SharePoint (without a backend)

For web apps that are pure SharePoint (e.g. an intranet), the app can show
a site's news itself as a `news` widget, without any feed. This is set up
in the app. If your web app also delivers a feed with a widget of the same
`id`, the feed wins.

### `action` – form + buttons (default `medium`)

```json
{
  "text": "Order directly, without opening the app.",
  "fields": [
    {
      "id": "article",
      "type": "select",
      "label": "Item",
      "required": true,
      "options": [{ "value": "A1", "label": "Screws M6" }]
    },
    { "id": "qty", "type": "number", "label": "Quantity", "required": true },
    { "id": "date", "type": "date", "label": "Delivery date" },
    { "id": "express", "type": "toggle", "label": "Express", "value": false }
  ],
  "buttons": [{ "id": "order", "label": "Order", "icon": "paperplane" }]
}
```

- **Field types:** `text` | `number` | `select` | `toggle` | `date` |
  `search` (see [Remote fields](#remote-fields-search-and-selection-from-your-backend)).
- **`value`:** optional default value, dates as `"YYYY-MM-DD"`.
- **Display:** The tile only shows `text` and the buttons. If the action
  has fields, a button tap opens a native form sheet with the fields, which
  is submitted from there. Without fields, the action runs directly from
  the tile.
- **Required fields:** As long as a required field is empty, the submit
  button is disabled.
- **After success:** The sheet closes.
- **Discarding:** As soon as the user has entered something, the sheet can
  no longer be swiped away by accident. "Cancel" then asks first
  ("Discard changes?").
- **Keyboard:** There is a "Done" button above the keyboard. The Return
  key jumps to the next text field. If there is an empty text field at the
  top of a page, it gets focus right away.

#### Conditional fields

With `visibleIf`, a field only appears if another field of the same form
has a matching value. The other field may also be on an earlier page.

```json
{ "id": "express", "type": "toggle", "label": "Express" },
{ "id": "reason", "type": "text", "label": "Reason", "required": true,
  "visibleIf": { "field": "express", "equals": true } },
{ "id": "rack", "type": "number", "label": "Shelf",
  "visibleIf": { "field": "article", "equals": ["A1", "A2"] } },
{ "id": "note", "type": "text", "label": "Customer note",
  "visibleIf": { "field": "customer" } }
```

- `equals` is a value or a list of allowed values. The app compares
  numbers as numbers, so `"3"` also matches `3`.
- Without `equals`, the field appears as soon as `field` is filled in or
  switched on.
- Hidden fields are never required and do **not** arrive in `values`.
- If a page has no visible field, the app skips it. "Step x of n" only
  counts visible pages.
- If a field depends on a hidden field, it is hidden itself.

#### Multiple pages

Instead of `fields`, you can specify `pages` (not both). The user moves
through the pages with **Next** and goes back with the back button in the
navigation bar. They can only continue once the required fields of the
current page are filled in. Submission happens on the last page, and the
values from all pages arrive together in `values`. Field `id`s must
therefore be unique across all pages.

```json
{
  "text": "Record a customer visit in three steps.",
  "pages": [
    {
      "title": "Customer",
      "fields": [{ "id": "customer", "type": "search", "label": "Customer", "required": true }]
    },
    {
      "title": "Contact person",
      "text": "Contact persons of the selected customer.",
      "fields": [
        { "id": "contact", "type": "select", "label": "Contact", "remote": true, "required": true }
      ]
    },
    {
      "title": "Details",
      "fields": [
        { "id": "date", "type": "date", "label": "Date" },
        { "id": "note", "type": "text", "label": "Note" }
      ]
    }
  ],
  "buttons": [{ "id": "save", "label": "Save", "icon": "checkmark" }]
}
```

`title` appears in the navigation bar (default: widget title), `text`
above the fields (on the first page, the tile's `text` is used as a
fallback). Above that, the app shows "Step 2 of 3".

#### Remote fields: search and selection from your backend

Two field types fetch their options live from your backend. Where they
come from is up to you, e.g. Meilisearch, an SQL full-text search or
another API.

| Field                              | Behavior                                                                                                                                                                                              |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `"type": "search"`                 | Search field. As the user types, the app queries your backend with the search text (debounced). Only from `minQueryLength` characters on, default 2. With `0`, suggestions appear even before typing. |
| `"type": "select", "remote": true` | Selection list that is loaded once when opened and then filtered locally. Good for dependent fields, e.g. the contacts of the customer selected on page 1.                                            |

Both open a native selection list with a search bar. Results can have a
second line (`subtitle`). As long as nothing has been typed, search fields
show the five most recently selected results (stored per device).
The app remembers results once loaded while the form is open. The `value` of the selected
result is sent. For a default value, set `value` and optionally
`valueLabel` as display text. If the user changes a selection, the app
resets remote `select` fields on later pages, because their options may
depend on it.

The app queries `widgetOptionsPath` (default `api/widget-options`), authenticated
as for the feed. `user_email` is what the app reports, not verified: take the
user from your `auth_dependency`:

```http
POST /api/widget-options
{"device_id": "…", "widget_id": "new-visit", "field_id": "customer",
 "query": "mus", "values": {"date": "2026-09-26"}, "user_email": "…"}
```

`values` contains everything entered so far, including on earlier pages.
Response (at most 50 results are shown):

```json
{
  "options": [{ "value": "K-1", "label": "Muster AG", "subtitle": "Zürich" }],
  "emptyText": "No customer found"
}
```

With the toolkit, here using Meilisearch:

```python
from bmsdna.app_native import (
    ActionOption,
    WidgetOptionsRequest,
    WidgetRequestContext,
    create_widget_options_router,
)


async def on_options(
    req: WidgetOptionsRequest, context: WidgetRequestContext
) -> list[ActionOption]:
    if req.field_id == "customer":
        hits = (await meili.index("customers").search(req.query, {"limit": 20}))["hits"]
        return [ActionOption(value=h["id"], label=h["name"], subtitle=h["city"]) for h in hits]
    if req.field_id == "contact":
        return [
            ActionOption(value=c.id, label=c.name)
            for c in await contacts_of(req.values.get("customer"))
        ]
    return []


app.include_router(
    create_widget_options_router(on_options_requested=on_options, auth_dependency=require_user),
    prefix="/api",
)
```

Without a network connection or on an error, the list shows a message.
All other inputs are kept.

### Buttons (in `action` and `list`)

| Field         | Meaning                                                                                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`, `label` | Required. `id` arrives at your backend as `action_id`.                                                                                                        |
| `style`       | `primary` (default) \| `secondary` \| `destructive`                                                                                                           |
| `icon`        | SF Symbol                                                                                                                                                     |
| `confirm`     | Confirmation text. The app asks before executing.                                                                                                             |
| `biometric`   | `true`: confirmation via Face ID/Touch ID. This is only a UX confirmation on the device, **not** proof for the backend, so always check permissions yourself. |

## Actions: what happens on a button tap

The app sends the tap **natively** to `widgetActionPath`. Your web app
does not need to be open for this; the call is authenticated as for the
feed. `user_email` is not verified, take the user from your
`auth_dependency` and check that this user may perform the action:

```http
POST /api/widget-actions
{"device_id": "…", "widget_id": "approvals", "action_id": "approve",
 "item_id": "A-1001", "values": {"qty": 3, "express": true}, "user_email": "…"}
```

The response is optional. Empty or `{}` means success:

```jsonc
{
  "ok": true, // false = rejected, message is shown as an error
  "message": "Approved", // short banner in the app
  "style": "success", // info | success | warning | error
  "widget": {
    /* … */
  }, // replaces this one widget immediately (e.g. the list without the entry)
  "widgets": [
    /* … */
  ], // or: replaces all widgets of your web app
  "openPath": "/orders/123", // then opens your web app here
}
```

With the toolkit:

```python
from bmsdna.app_native import (
    WidgetActionReceived,
    WidgetActionResult,
    WidgetRequestContext,
    create_widget_action_router,
)


async def on_action(
    action: WidgetActionReceived, context: WidgetRequestContext
) -> WidgetActionResult | None:
    if action.widget_id == "approvals" and action.action_id == "approve":
        await approve(action.item_id, by=context.user)
        return WidgetActionResult(
            message="Approved", widget=await build_approvals_widget(context.user)
        )
    return WidgetActionResult(ok=False, message="Unknown action")


app.include_router(
    create_widget_action_router(on_action_received=on_action, auth_dependency=require_user),
    prefix="/api",
)
```

Actions do **not** go into the offline queue. The user waits for the
result and gets an error message immediately when offline, instead of the
action being carried out unnoticed hours later. The app shows HTTP errors
with `message` or FastAPI's `detail`, otherwise with the status code.

## What the user can configure

Via the slider icon at the top right of the dashboard ("Customize
dashboard") and by long-pressing a widget, the user can:

- **Show/hide** widgets. Required widgets (`"required": true`) show a lock
  and cannot be hidden.
- **Reorder** widgets, including required widgets.
- Choose the **number of posts** for news: 2, 4 or 6 (long press › Number of posts).
- **Reset** everything to your defaults.

The settings are keyed by `"<webappId>/<id>"`. So keep `id`s stable; a new
`id` counts as a new widget. New widgets appear at the end; with
`defaultEnabled: false`, only once the user shows them.

Use `required` sparingly, e.g. for a truly important key figure or open
approvals. The dashboard belongs to the user.

## On the Home Screen and Lock Screen

The user can also place each of your widgets individually on their
iPhone's Home Screen or Lock Screen, as the iOS widget
**"Web App Widget"** (iOS 17 and later). To do so, long-press the Home
Screen, tap **+**, search for the app, choose "Web App Widget", then tap
the widget and select yours under "Widget".

**You don't have to do anything for this.** It is the same widget as on
the dashboard, with the same data from feed, push and bridge.

| Size        | What is shown                                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------------------------------- |
| Small       | like `small` on the dashboard; list 2 rows, action 1 button, chart only the latest value                               |
| Medium      | like `medium`; list 3 rows (or 2 with buttons), action 2 buttons                                                       |
| Large       | like `large`; list 6 rows (or 4 with buttons), action 3 buttons, news 5 rows (4 with channel tabs)                     |
| Lock Screen | the main value: key figure, progress (as a ring), first stats value, number of list entries, for news the latest title |

In the small widget, news shows the latest post (a tap opens it); the
medium one shows two and the large one five rows with cover image, title
and teaser (channel tabs only in the large one). Each row opens its post.
The cover images come from the cache shared by the app and the widget.

**How it stays current:**

- Whenever something changes in the app (feed, push, bridge, response to
  an action), the widget is redrawn immediately.
- The widget also fetches your feed (or the SharePoint news) itself, roughly every 15 minutes,
  even when the app is not running. iOS decides exactly how often. For this
  it authenticates the same way as the app, with the credentials the app
  last successfully used to load your feed.
- For immediate updates, use `send_widget_update()`: the push wakes the
  app, which then updates the dashboard and the widget.
- From `expiresAt` on, the widget turns grey and fetches fresh data.

**Buttons run directly in the widget**, without the app opening, just like
on the dashboard: `POST <widgetActionPath>`, additionally with
`"source": "homeScreen"` in the body. Of your response, `message` (briefly
shown in the widget) as well as `widget` and `widgets` take effect.
`openPath` has no effect there. Exceptions that open the dashboard in the
app instead:

- Buttons with `confirm` or `biometric`, because confirmation prompts and
  Face ID are not available in the widget.
- All buttons of an `action` widget with form fields.

A tap next to the buttons opens your web app at the widget's `path`.

## Try it out

A local backend with feed and actions is in
[`python/app-native/example/main.py`](../python/app-native/example/main.py).
