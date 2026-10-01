# Native chrome for web app developers

This guide is for teams that embed their web app in the BMS app and want to
control their own native UI (hamburger menu, action buttons, bottom bar) on
top of it. Technical background and the other bridge actions
(document/barcode scanning): see [README.md](../README.md).

## Presentation: every web app opens full screen

Regardless of everything below, every web app (from the app list,
favorites, a notification or a push deep link — the only exception: when
configured as a fixed tab of the app) always opens as a standalone
full-screen view on top of the rest of the app. The app's own navigation
(the app's tab bar) is never visible or reachable during that time — a web
app is left exclusively via the native back button at the top left. The
swipe-from-left gesture, on the other hand, goes back in the history of
**your** web app (like in Safari); it does not close the web app.

This applies to **every** web app, without any capability being enabled — so
it affects you too, even if you don't use native chrome at all. Only
`.customBottomBar` (see below) additionally lets you declare your own bottom
navigation within this full-screen view.

## The three building blocks — when to use which

| Building block     | Where                             | How many                                  | What for                                                                                 |
| ------------------ | --------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Hamburger menu** | Next to the back button, top left | any number (sections + items, scrollable) | Many/rarely used actions, navigation, settings                                           |
| **Action buttons** | Top right                         | max. 2                                    | 1–2 very frequently used actions (share, filter, search)                                 |
| **Bottom bar**     | At the very bottom                | max. 5                                    | Your own complete navigation **within** your web app — fully replaces the app navigation |

Rule of thumb: Start with 1–2 things the user needs all the time →
**action buttons**. If the list gets longer or contains rarer/dangerous
actions (e.g. sign out) → into the **hamburger menu**. Your web app has its
own self-contained navigation structure (several main areas) → **bottom
bar**.

## Prerequisite: enable the capability

None of this works until the app has enabled it for your web app. The
capabilities:

- **`.customChrome`** — for the hamburger menu and action buttons.
- **`.customBottomBar`** — additionally, separately, only for the bottom bar
  (deliberately separate: it lets you show a completely custom bottom
  navigation within your full-screen view, which is always your own anyway —
  see "Presentation" above — instead of simply staying empty/without a bar).

If a capability is missing, only the affected part of your `setChrome` call
is silently ignored (no error, no exception) — the rest keeps working.

## The call: `setChrome`

Everything goes through a single bridge call; all three fields are
optional:

```js
window.webkit.messageHandlers.nativeBridge.postMessage({
  action: 'setChrome',
  menu: [
    /* sections, see below */
  ],
  actionButtons: [
    /* max. 2, see below */
  ],
  bottomBar: [
    /* max. 5, see below */
  ],
})
```

Call `setChrome` again to change the state (e.g. on a route change in your
SPA) — the last call wins completely, nothing is merged. Omitting a field or
sending it as an empty array removes exactly that part again.

**Lifetime:** The state you set applies until the next real navigation of
this web app (full page load/reload). While the new page loads, the previous
chrome stays visible; as soon as the new page calls `setChrome`, its call
replaces it. If it doesn't call `setChrome` within about 1.5 s after it has
finished loading, the old chrome is removed. If the navigation fails or is
cancelled (download, external link), the chrome stays unchanged. In an SPA
without full page changes (`pushState`), it stays untouched until you change
it yourself. So it's best to call `setChrome` again right after every
`DOMContentLoaded`/route change, even if nothing has changed.

**Single-page web apps with different chrome per page:** Send
`scope: "route"` along; your chrome then additionally only applies until the
next client-side route change (`pushState`/`replaceState`/hash): if the new
route doesn't report its own within about 1.5 s, it is removed. For this,
call `setChrome` **after** the route change (e.g. in your router's
`afterEach` hook). Without `scope` (default `"page"`), everything stays as
described above.

### Making it robust: menu/bar should never disappear

If your hamburger menu or bottom bar is the same on all pages (the normal
case), send `scope: "app"` along. Your chrome then persists across **all**
navigations — reloads, page changes, redirects, route changes — until you
send a new one yourself. It can then no longer disappear just because a page
calls `setChrome` too late or not at all (e.g. an error or interstitial page
without your script).

| `scope`            | Applies until …                                                                             | What for                                       |
| ------------------ | ------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `"page"` (default) | the next full page load, if the new page doesn't send its own within about 1.5 s afterwards | Classic web apps whose chrome differs per page |
| `"route"`          | additionally, the next SPA route change (same 1.5 s grace period)                           | SPAs with chrome per route                     |
| `"app"`            | you send a new one yourself                                                                 | **Fixed menu/fixed bar — recommended**         |

Removing with `scope: "app"`: send `setChrome` with empty arrays (e.g. on
sign-out). If only part of it changes (such as a badge count), simply send
the complete chrome again with the new value — the last call wins.

Even more robust — regardless of `scope` — is to send the chrome again on
every event after which the page becomes visible (again). The call is cheap
and has no side effects; sending it twice does no harm:

```js
const CHROME = {
  action: 'setChrome',
  scope: 'app',
  menu: [
    /* … */
  ],
  bottomBar: [
    /* … */
  ],
}

function sendChrome() {
  window.webkit?.messageHandlers?.nativeBridge?.postMessage(CHROME)
}

sendChrome() // immediately (in the <head>)
document.addEventListener('DOMContentLoaded', sendChrome)
window.addEventListener('pageshow', sendChrome) // also from the back-forward cache
window.addEventListener('popstate', sendChrome) // back/forward in the SPA
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') sendChrome() // app back in the foreground
})
```

Include this as a small script of its own in **every** page of your layout
(including error and login interstitial pages that can appear in the app),
not just on the start page.

**So that icons/menu don't visibly "pop in" late:** Don't wait for data from
your backend before the first `setChrome` call — call it synchronously as
early as possible, e.g. in a small `<script>` at the very top of the
`<head>`, before the rest of the page even renders (the bridge doesn't need
a finished DOM for this, only running JS). An early call is NOT cleared again
by the page's own navigation — it counts as the chrome of the new page right
away. If data is still missing at this early point (e.g. a dynamic badge
count), a first, static `setChrome` call with the known menu items/icons and
a second, updated call once the data is available are enough — icons and
menu then appear immediately, only the badge may lag slightly behind.

### `menu` — hamburger menu

```js
menu: [
  {
    title: "Orders",              // optional — a section without a title is fine
    items: [
      { id: "new-order", label: "New order", icon: "plus.circle" },
      { id: "order-list", label: "Order list", icon: "list.bullet" },
    ],
  },
  {
    // Section without a title, e.g. for standalone items
    items: [
      { id: "settings", label: "Settings", icon: "gearshape" },
    ],
  },
  {
    items: [
      { id: "logout", label: "Sign out", icon: "rectangle.portrait.and.arrow.right", destructive: true },
    ],
  },
  {
    items: [
      { id: "invites", label: "Invitations", icon: "envelope", color: "#2e4a62", value: "10" },
    ],
  },
],
```

| Field                 | Type         | Required            | Meaning                                                                                                                                                                              |
| --------------------- | ------------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `items[].id`          | string       | yes                 | Passed back 1:1 to `onNativeMenuSelect`                                                                                                                                              |
| `items[].label`       | string       | yes                 | Visible text                                                                                                                                                                         |
| `items[].icon`        | string       | no                  | SF Symbol name (see the icon guide below)                                                                                                                                            |
| `items[].destructive` | bool         | no, default `false` | `true` colors icon+text red (for "Sign out", "Delete" or similar)                                                                                                                    |
| `items[].color`       | string (hex) | no                  | Custom color for this item's icon+text, e.g. `"#2e4a62"`. If omitted, the standard text color. Has no effect with `destructive: true` (its red takes precedence)                     |
| `items[].searchable`  | bool         | no, default `true`  | `false` keeps the item out of Spotlight/Siri (e.g. for items that only make sense in a specific context)                                                                             |
| `items[].value`       | string       | no                  | Right-aligned, subtle gray value at the end of the row — like the count/status ("10" or similar) in native Settings lists. Not a red number badge as in `bottomBar` — any short text |
| `sections[].title`    | string       | no                  | Heading above the section                                                                                                                                                            |

Opens as a native, scrollable sheet — any number of sections/items is no
problem.

#### `menuHeader` — your own logo at the top of the menu

Without `menuHeader`, the menu shows a tile at the top with the web app's
icon, name and group. With `menuHeader`, your logo appears there instead,
centered and without a card background:

```js
// One wordmark, built into the app and animated:
// the ring draws itself, the dot pops, then "ne" + suffix in red.
menuHeader: { logo: "one", suffix: "Business" },   // without suffix: name of the web app

// Custom image: PNG, JPG, SVG or GIF, absolute, relative to the page or as a data: URL
menuHeader: { image: "/static/logo.svg", alt: "Partner-Tool" },

// Custom HTML/CSS, e.g. for a different animated logo
menuHeader: { html: "<span class='logo'>…</span>", css: ".logo { … }" },
```

| Field          | Type   | Required                     | Meaning                                                                                                                |
| -------------- | ------ | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `logo`         | string | one of `logo`/`html`/`image` | `"one"`: the One wordmark, built into the app                                                                          |
| `suffix`       | string | no                           | Text after "One" in the One logo, default: name of the web app. With long texts, the logo shrinks so it fits the width |
| `html` / `css` | string |                              | Custom markup and CSS. **No JavaScript** (it doesn't run); CSS animations do run                                       |
| `image`        | string |                              | Image URL. Loads with your web app's cookies                                                                           |
| `height`       | number | no, default `44`             | Height of the header in points (24–120)                                                                                |
| `alt`          | string | no                           | Text for VoiceOver, default: the wordmark or the name of the web app                                                   |

Like the menu, it requires `.customChrome`. Tapping the logo does nothing.
In dark mode, the One logo has light gray instead of dark gray parts, and
with "Reduce Motion" it shows the final state directly. With your own
`html`/`css`, you take care of this yourself (`prefers-color-scheme`,
`prefers-reduced-motion`).

**Discoverable via Spotlight and Siri:** Every menu item your web app has
reported at least once shows up in iOS search (e.g. "New order") and can be
triggered via Siri ("New order in <app name>"). A result opens your web app
and, as soon as it has loaded and reported its menu via `setChrome`, calls
`onNativeMenuSelect(id)` — exactly like a tap in the menu. `destructive`
items and items with `searchable: false` are not included. Items that
haven't been reported for 30 days disappear again. So keep the `id`s stable
across releases.

Beyond your menu, the app offers a few shortcuts for Siri and the Shortcuts app. Their
names are German: "Freigaben anzeigen" (shows the dashboard with the approvals),
"Mitteilungen anzeigen" (only in the Shortcuts app, no Siri phrase) and "Dokument
scannen". The last one is offered for every web app but only works for those with the
`camera` capability: it opens the web app and starts the document scanner like
`scanDocument()` does, otherwise it says the web app takes no documents. You do not
have to do anything for those.

### `actionButtons` — max. 2, top right

```js
actionButtons: [
  { id: "share", icon: "square.and.arrow.up", label: "Share" },
  { id: "filter", icon: "line.3.horizontal.decrease.circle", label: "Filter" },
],
```

| Field   | Type   | Required | Meaning                                                                    |
| ------- | ------ | -------- | -------------------------------------------------------------------------- |
| `id`    | string | yes      | Passed back 1:1 to `onNativeActionButtonTap`                               |
| `icon`  | string | yes      | SF Symbol name                                                             |
| `label` | string | no       | Only for screen readers (accessibility) — no visible text next to the icon |

As soon as the first action button is set, the favorites and info buttons
automatically collapse into a single overflow icon (`•••`) so there's enough
room. More than 2 buttons are discarded — use the hamburger menu for that.

### `bottomBar` — max. 5, replaces the entire bottom bar

```js
bottomBar: [
  { id: "orders", icon: "list.bullet", label: "Orders" },
  { id: "scan", icon: "camera", label: "Scan", prominent: true },
  { id: "inbox", icon: "bell", label: "Notifications", badge: 3 },
],
bottomBarStyle: "prominent", // "normal" (default) | "prominent" | "hidden"
bottomBarColor: "#2e4a62", // optional
```

| Field                   | Type         | Required               | Meaning                                                                                                                                                                                                                                                      |
| ----------------------- | ------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `bottomBar[].id`        | string       | yes                    | Passed back 1:1 to `onNativeBottomBarTap`                                                                                                                                                                                                                    |
| `bottomBar[].icon`      | string       | yes                    | SF Symbol name                                                                                                                                                                                                                                               |
| `bottomBar[].label`     | string       | yes                    | Visible text below the icon                                                                                                                                                                                                                                  |
| `bottomBar[].badge`     | int          | no, default `0`        | Number in the red badge at the top right of the icon, `0`/omitted = no badge                                                                                                                                                                                 |
| `bottomBar[].prominent` | bool         | no, default `false`    | Only relevant with `bottomBarStyle: "prominent"` (see below)                                                                                                                                                                                                 |
| `bottomBarStyle`        | string       | no, default `"normal"` | Display style of the bar, see below                                                                                                                                                                                                                          |
| `bottomBarColor`        | string (hex) | no                     | Color of the bar's icons + text, e.g. `"#2e4a62"`. If omitted (or invalid), a neutral default gray (currently `#363636`) — for your own branding, simply specify your brand/accent color. The badge itself always stays red, regardless of `bottomBarColor`. |

**`bottomBarStyle` — three display styles:**

- **`"normal"`** (default) — all items side by side with equal weight, like
  normal tab bar icons.
- **`"prominent"`** — one item appears as a raised, round center button
  (visually like the center button in the app's tab bar), with the others
  shown normally next to it. Mark exactly one item with `prominent: true`
  for this; if you don't mark any, the app defensively picks the middle item
  automatically so that something sensible still appears. Suited for a
  particularly highlighted main action (e.g. "Scan" or "New order").
- **`"hidden"`** (synonym: `"none"`) — no bottom bar at all, not even the
  native standard bar as a fallback. `bottomBar` can stay empty or be
  omitted entirely. For screens that want to use the full screen without
  any bottom bar — the user then leaves the web app exclusively via the
  native back button at the top left.

**Important:** If you don't call `setChrome` with `bottomBar`/`bottomBarStyle`
at all (yet), the bottom bar of your full-screen view simply stays empty
(like `bottomBarStyle: "hidden"`) — no problem, since the app navigation
(see "Presentation" above) never serves as a fallback anyway: the user
leaves the web app only via the back button at the top left either way,
regardless of the state of your `setChrome` calls.

The app itself doesn't know the "selected" state of your items — you have
to reflect that yourself in your frontend (e.g. via URL/route).

## Callbacks: receiving taps

```js
window.onNativeMenuSelect = (id) => {
  if (id === 'new-order') window.location.href = '/orders/new'
  if (id === 'logout') {
    /* sign out */
  }
}

window.onNativeActionButtonTap = (id) => {
  if (id === 'share') {
    /* Web Share API or similar */
  }
}

window.onNativeBottomBarTap = (id) => {
  if (id === 'orders') window.location.href = '/orders'
  if (id === 'scan') window.location.href = '/scan'
}
```

The app itself runs **no** logic — it only displays what you give it and, on
a tap, only calls back with the matching `id`. What happens next is entirely
up to your own JS code.

## Icon guide: which SF Symbols work

`icon` is always an [SF Symbol](https://developer.apple.com/sf-symbols/) name
as a string (Apple's system-wide icon set; you can look up names e.g. with
the free "SF Symbols" Mac app). There is currently **no server-side
allowlist** — every valid name is passed through. A typo simply shows no
icon (no crash), so test it once.

**Compatibility:** The app supports iOS **16.2+**. SF Symbols that were only
added with SF Symbols 5 (iOS 17) or later may be missing on older devices.
When in doubt, stick to the curated list below — all of it has been
available since iOS 13.

### Curated, tested selection

**Actions**

| Symbol                                           | For                                  |
| ------------------------------------------------ | ------------------------------------ |
| `plus`, `plus.circle`                            | Create new                           |
| `pencil`, `square.and.pencil`                    | Edit                                 |
| `trash`                                          | Delete (usually `destructive: true`) |
| `checkmark`, `checkmark.circle`                  | Confirm, done                        |
| `xmark`, `xmark.circle`                          | Cancel, close                        |
| `magnifyingglass`                                | Search                               |
| `line.3.horizontal.decrease.circle`              | Filter                               |
| `slider.horizontal.3`                            | Sort/adjust                          |
| `arrow.clockwise`, `arrow.triangle.2.circlepath` | Refresh                              |
| `square.and.arrow.up`                            | Share                                |
| `square.and.arrow.down`                          | Download                             |
| `ellipsis.circle`                                | More options                         |

**Documents & lists**

| Symbol                                 | For              |
| -------------------------------------- | ---------------- |
| `doc`, `doc.text`                      | Document         |
| `doc.badge.plus`                       | Add document     |
| `folder`, `folder.fill`                | Folder           |
| `list.bullet`, `list.bullet.clipboard` | List, order list |
| `tray`, `tray.full`                    | Inbox/filing     |
| `archivebox`                           | Archive          |
| `paperclip`                            | Attachment       |
| `camera`, `camera.fill`                | Camera, scan     |
| `qrcode`, `barcode`                    | QR code/barcode  |
| `printer`                              | Print            |

**Status & notices**

| Symbol                     | For           |
| -------------------------- | ------------- |
| `bell`, `bell.badge`       | Notifications |
| `flag`                     | Flag          |
| `star`, `star.fill`        | Favorite      |
| `checkmark.seal`           | Verified      |
| `exclamationmark.triangle` | Warning       |
| `exclamationmark.circle`   | Error/notice  |
| `info.circle`              | Info          |
| `questionmark.circle`      | Help          |

**Navigation & places**

| Symbol                            | For                 |
| --------------------------------- | ------------------- |
| `house`, `house.fill`             | Home/start          |
| `square.grid.2x2`                 | Overview/apps       |
| `map`, `mappin.and.ellipse`       | Map, location       |
| `location`, `location.fill`       | Current location    |
| `building.2`                      | Company/building    |
| `briefcase`                       | Orders/business     |
| `cart`                            | Shopping cart/order |
| `creditcard`, `dollarsign.circle` | Payment             |
| `chart.bar`, `chart.pie`          | Statistics          |
| `calendar`                        | Appointments        |
| `clock`                           | History/time        |

**Communication**

| Symbol                   | For          |
| ------------------------ | ------------ |
| `envelope`               | Email        |
| `message`, `bubble.left` | Message/chat |
| `phone`, `phone.fill`    | Call         |
| `paperplane`             | Send         |

**Account & security**

| Symbol                               | For                                    |
| ------------------------------------ | -------------------------------------- |
| `person`, `person.crop.circle`       | Profile                                |
| `person.2`                           | Team/multiple users                    |
| `gearshape`, `gearshape.fill`        | Settings                               |
| `lock`, `lock.fill`                  | Locked/secure                          |
| `key`                                | Access/sign-in                         |
| `rectangle.portrait.and.arrow.right` | Sign out (usually `destructive: true`) |
| `faceid`, `touchid`                  | Biometrics                             |

If you need an icon that isn't listed here: look it up in the SF Symbols
app, copy the name, and briefly test it on a real device/simulator. Icons
with the `.fill` suffix are the filled variant of the same symbol (e.g.
`star` vs. `star.fill`) — for action icons, usually use the unfilled variant
(it visually matches the existing app icons); use filled variants rather for
"active/selected" states.

## Complete example

```js
function applyChrome() {
  window.webkit.messageHandlers.nativeBridge.postMessage({
    action: 'setChrome',
    menu: [
      {
        title: 'Orders',
        items: [
          { id: 'new-order', label: 'New order', icon: 'plus.circle' },
          { id: 'order-history', label: 'History', icon: 'clock' },
        ],
      },
      {
        items: [
          {
            id: 'logout',
            label: 'Sign out',
            icon: 'rectangle.portrait.and.arrow.right',
            destructive: true,
          },
        ],
      },
    ],
    actionButtons: [{ id: 'share', icon: 'square.and.arrow.up', label: 'Share' }],
    bottomBar: [
      { id: 'orders', icon: 'list.bullet', label: 'Orders' },
      { id: 'scan', icon: 'camera', label: 'Scan', prominent: true },
      { id: 'inbox', icon: 'bell', label: 'Notifications', badge: unreadCount },
    ],
    bottomBarStyle: 'prominent',
    bottomBarColor: '#2e4a62',
  })
}

window.onNativeMenuSelect = (id) => {
  if (id === 'new-order') navigateTo('/orders/new')
  if (id === 'order-history') navigateTo('/orders/history')
  if (id === 'logout') logout()
}

window.onNativeActionButtonTap = (id) => {
  if (id === 'share') shareCurrentOrder()
}

window.onNativeBottomBarTap = (id) => {
  if (id === 'orders') navigateTo('/orders')
  if (id === 'scan') navigateTo('/scan')
  if (id === 'inbox') navigateTo('/inbox')
}

// Call again after every load/route change (more robust: `scope: "app"`
// plus the events from "Making it robust" above):
document.addEventListener('DOMContentLoaded', applyChrome)
```

## More bridge actions

### Is my page running in the app? — `window.BMSNative`

Before every page load, the app sets `window.BMSNative` and the CSS class
`bms-native-app` on `<html>`. You can use this, for example, to hide your
own header or web navigation in the app:

```css
.bms-native-app .site-header {
  display: none;
}
```

```js
if (window.BMSNative) {
  BMSNative.platform // "ios"
  BMSNative.version // app version, e.g. "1.0" (also available as appVersion)
  BMSNative.webAppId // your web app ID in the app, e.g. "partner-tool"
  BMSNative.capabilities // e.g. ["camera", "customChrome", ...]
}
```

On the server side, you can recognize the app by the user agent suffix
`BMSMobile/<version>`.

### Default CSS

Without you having to do anything, the app applies the following in every
web app:

- no gray tap highlight on links and buttons,
- no link preview and no text selection menu on long press on buttons
  (`button`, `[role=button]`, submit inputs),
- no zooming in when tapping input fields with a font size below 16px: the
  app appends `maximum-scale=1` to your `<meta name="viewport">`. Pinch to
  zoom remains possible, and your font size doesn't change. Without a
  `<meta name="viewport">`, nothing happens,
- no horizontal overscroll; if pull-to-refresh is turned off for your web
  app, no vertical overscroll either.

The CSS is inserted as the first `<style>`, so your own rules always take
precedence. In the app, it can be turned off per web app
(`injectsDefaultStyles: false`).

**Calls with a response:** `BMSNative.call(action, payload)` sends the same
message as `postMessage` and returns a promise that resolves with
`{ ok: true }` or `{ ok: false, error: "..." }`
(`error`: `"capability"`, `"invalid"`, `"cancelled"`, `"unavailable"`,
`"failed"`, `"unknownAction"`; `"denied"` for the device actions;
`"forbidden"` and `"notSignedIn"` for `getAccessToken`). Actions without a result of their own respond
immediately once the app has accepted them.

```js
const { ok } = await BMSNative.call('biometricConfirm', { reason: 'Approve order 4711' })
```

### Overview

| Action                                                             | Fields                                                                                                                     | Capability          | Effect                                                                                                                                                                                                                                                                                |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `share`                                                            | `title?`, `text?`, `url?` (at least one)                                                                                   | —                   | Native share sheet. Responds with `ok: false, error: "cancelled"` if the user cancels                                                                                                                                                                                                 |
| `haptic`                                                           | `style`: `light` \| `medium` (default) \| `heavy` \| `soft` \| `rigid` \| `selection` \| `success` \| `warning` \| `error` | —                   | Haptic feedback                                                                                                                                                                                                                                                                       |
| `toast`                                                            | `message`, `style?`: `info` \| `success` \| `warning` \| `error`, `duration?` (seconds, default 2.5)                       | —                   | Short native banner at the bottom                                                                                                                                                                                                                                                     |
| `setBadge`                                                         | `count` (`0` removes it)                                                                                                   | —                   | Red number badge on your tile in the Apps tab or — as a fixed tab — on your tab in the tab bar. Doesn't count toward the badge on the app icon — that only shows unread notifications. Persists across app restarts                                                                   |
| `openExternal`                                                     | `url`                                                                                                                      | —                   | Deliberately opens the URL outside the app (in Safari or the responsible app)                                                                                                                                                                                                         |
| `biometricConfirm`                                                 | `reason?`                                                                                                                  | —                   | Face ID/Touch ID, falling back to the device passcode. **Only a confirmation on the device, not proof for your backend** — keep securing security-critical approvals on the server side                                                                                               |
| `setWidgets` / `updateWidget` / `removeWidgets` / `refreshWidgets` | see guide                                                                                                                  | `.dashboardWidgets` | Widgets on the Home dashboard — see [dashboard-widgets-guide.md](dashboard-widgets-guide.md)                                                                                                                                                                                          |
| `refreshApprovals`                                                 | —                                                                                                                          | `.approvals`        | Immediately reloads your pending approvals on Home, e.g. after the page itself has approved something — see [approvals-guide.md](approvals-guide.md)                                                                                                                                  |
| `getAccessToken`                                                   | `refresh?`                                                                                                                 | `.identity`         | The Entra ID token of the app's sign-in, for the places where the browser cannot set a header (`WebSocket`, `EventSource`, a web worker, which gets the token from the page). `fetch`/XHR to your own backend get it automatically — see [entra-token-guide.md](entra-token-guide.md) |
| `navigate`                                                         | `destination` (place or text), `waypoints?`, `mode?`, `app?`                                                               | —                   | Starts a route in Apple Maps, Google Maps or Waze — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                            |
| `addReminder`                                                      | `title`, `due?`, `allDay?`, `notes?`, `priority?`, `list?`, `url?`, `confirm?`                                             | `.deviceApps`       | Creates a reminder in Apple Reminders (asks first) — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                           |
| `saveContact`                                                      | `givenName?`, `familyName?`, `organization?`, `jobTitle?`, `phones?`, `emails?`, `address?`, `url?`, `confirm?`            | `.deviceApps`       | Saves a contact (system form first) — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                                          |
| `callPhone`                                                        | `number`                                                                                                                   | —                   | Starts a phone call; iOS asks before dialing — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                                 |

```js
window.webkit.messageHandlers.nativeBridge.postMessage({
  action: 'toast',
  message: 'Saved',
  style: 'success',
})
BMSNative.call('share', { title: 'Order 4711', url: location.href })
```

### What you no longer have to handle yourself

- **Links:** `tel:`, `mailto:`, `sms:`, map links and links to other domains
  automatically open outside your web app (other domains in the matching app
  or an in-app Safari). Which domains count as internal is configured in the
  app.
- **`target="_blank"` and `window.open`:** Links open in the same WebView;
  windows opened by script (e.g. an MSAL login popup) open in a sheet with
  working `window.opener` and `window.close()`.
- **`alert`/`confirm`/`prompt`** appear as native dialogs.
- **Downloads:** Responses with `Content-Disposition: attachment`, file types
  that can't be displayed and `<a download>` (including `blob:`) open in the
  iOS preview after downloading, with share/save options there.
- **`<meta name="theme-color">`** tints the bar at the top.
- **Pull-to-refresh, loading bar and error page** (with automatic reload as
  soon as the device is back online) are built into the app.

## Troubleshooting

- **Icon/menu doesn't appear at all** → `.customChrome` or
  `.customBottomBar` is not enabled for your web app.
  `BMSNative.capabilities` shows what your web app is allowed to do.
- **Bottom bar doesn't appear even though `.customBottomBar` is set** →
  `.customBottomBar` only takes effect if the web app is NOT configured as a
  fixed tab of the app (see "Presentation" above). Otherwise: `setChrome`
  with `bottomBar`/`bottomBarStyle` hasn't been called yet (see "Important"
  above) — going back still works at any time via the button at the top
  left.
- **Swipe-from-left gesture doesn't close the web app** → expected, see
  "Presentation" above: the gesture goes back in your web app's history; the
  web app is only left via the back button.
- **Tap does nothing** → check the callback function name
  (`onNativeMenuSelect`/`onNativeActionButtonTap`/`onNativeBottomBarTap`,
  exactly as written, on `window`), and that the `id` in the JS matches the
  one in the `setChrome` call.
- **Menu/buttons/bar disappear (after a reload, when navigating, sometimes
  about 1.5 s after loading)** → expected with the default `scope` if a page
  doesn't call `setChrome` (in time), see "Lifetime" above. Fix: send
  `scope: "app"` along and include the script from "Making it robust" in
  every page.
- **Icon is missing/shows nothing** → check the name in the SF Symbols app;
  it may be too new for iOS 16 (see the compatibility note above).
