# Native chrome for web app developers

This guide is for teams that embed their web app in the BMS app and want to
control their own native UI (hamburger menu, action buttons, bottom bar) on
top of it. Technical background and the other bridge actions
(document/barcode scanning): see [README.md](../README.md). Text scan and several barcodes at once (`scanText`, `scanBarcodes`, `scanBarcode` with options): [scan-guide.md](scan-guide.md).

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
flush left in the top bar of the menu, in place of the web app's name, and
without a card background:

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
| `height`       | number | no, default `44`             | Design height in points (24–120); a taller logo is scaled down to the bar's maximum height                             |
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

More callbacks exist for the newer parts of `setChrome` (title, menus of action buttons,
search, segments, sidebar, undo), the keyboard toolbar and key commands; they are listed in
[Title, search, segments, sidebar, undo](#title-search-segments-sidebar-undo-2026-11b), and
`on(…)` of the package dispatches all of them.

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

## Layout: bars, keyboard, size class, iPad

The web view sits **between** the native top bar and the native bottom bar. The bars
never overlay your content, so a `position: fixed; top: 0` header starts below the top
bar and a bottom input bar sits above the bottom bar.

**Safe areas.** With `<meta name="viewport" content="..., viewport-fit=cover">`
`env(safe-area-inset-*)` works, and it reports only what is **left** of the device
insets: the side insets in landscape, and the home indicator only when no native bottom
bar is shown. Do not add the insets of the native bars yourself.

```css
.composer {
  padding-bottom: env(safe-area-inset-bottom);
}
```

**Keyboard.** WebKit's default resizing of `visualViewport` for the on-screen keyboard
stays on. The app also keeps these on `<html>` up to date:

| What                                 | Values                                                                     |
| ------------------------------------ | -------------------------------------------------------------------------- |
| CSS property `--bms-keyboard-height` | the height of the keyboard that overlaps the web view, e.g. `0px`, `336px` |
| Attribute `data-bms-size-class`      | `"compact"` or `"regular"`: the horizontal size class                      |
| Attribute `data-bms-orientation`     | `"portrait"` or `"landscape"`                                              |

```css
.chat-input {
  margin-bottom: var(--bms-keyboard-height, 0px); /* keep the input above the keyboard */
}
html[data-bms-size-class='regular'] .detail {
  display: block; /* master/detail side by side on iPad */
}
```

**From script.** The event fires after the keyboard has been shown or hidden (the final
values), after a rotation and after multitasking resizes. `width` and `height` are the
size of the web view in CSS px.

```ts
import { getLayout, keyboardHeight, on } from '@bmsuisse/app-native'

const off = on(
  'layoutChange',
  ({ keyboardHeight, keyboardVisible, sizeClass, orientation, width, height }) => {
    chat.scrollToBottom()
  }
)

const layout = await getLayout() // { ok: true, keyboardHeight, keyboardVisible, sizeClass, orientation, width, height }
const px = await keyboardHeight() // getLayout in the app, visualViewport in the browser
```

- `getLayout()` and `window.onNativeLayoutChange` need the feature `layout`
  (`hasFeature('layout')`). In the browser and in an older app `getLayout()` answers
  `unavailable`, and no attribute or property is set: use media queries and
  `visualViewport` there. `keyboardHeight()` does that fallback for you (it never
  throws and returns `0` if it cannot tell).
- Prefer the CSS property and the attributes for styling and `on('layoutChange')` for
  logic.

### iPad and hardware keyboard

Web apps support all iPad orientations, **Split View, Slide Over and Stage Manager**:
the web view resizes, `layoutChange` fires, and `sizeClass` switches between `compact`
(narrow window) and `regular` (wide window). Build for the window size, not the device.

With a hardware keyboard or trackpad (nothing to call, it is how the app behaves):

- While a web app is shown, the app consumes **no** key events except **Cmd+W** (closes
  the web app) and system shortcuts. Cmd+K, Cmd+F, Cmd+Z, Option combinations, Esc and
  the arrow keys reach your page as normal DOM `keydown` events.
- Pointer hover and the secondary click (the `contextmenu` event) reach the page.
- Files dragged onto the web view from other apps arrive as a normal HTML `drop` event
  with `DataTransfer.files`. (Shared files go through the Share Extension instead, see
  [documents-guide.md](documents-guide.md).)

```ts
addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    openCommandPalette()
  }
})
addEventListener('dragover', (e) => e.preventDefault())
addEventListener('drop', (e) => {
  e.preventDefault()
  importFiles([...(e.dataTransfer?.files ?? [])])
})
```

## Intercepting the back button

By default the native back button closes the web app and the left-edge swipe goes back
in the web view's history. A page that has its own back steps (a dialog, a wizard, a
tab inside an editor) can take over, so the user does not lose their work:

```ts
import { onBackRequested } from '@bmsuisse/app-native'

const off = onBackRequested(async (source) => {
  // source: 'button' | 'swipe'
  if (dialogOpen) {
    closeDialog()
    return true
  } // handled: the app does nothing more
  if (dirty) {
    await confirmDiscard()
    return true
  }
  return false // not handled: the default (button closes the web app, swipe goes back)
})
// off() when the screen goes away
```

How it works (feature `backInterception`):

- Registering the first handler calls `setBackInterception({ enabled: true })`;
  removing the last one calls it with `enabled: false`. The setting lasts until it is
  called again or the page **fully reloads**. Route changes of a single-page app do
  **not** reset it: remove the handler when its screen goes away.
- While enabled, the back button and the swipe do nothing themselves. The app calls
  `window.onNativeBackRequested({ source })` and waits **800 ms** for
  `BMSNative.call('backResult', { handled })`. The package does that for you: it answers
  from the handler, and a handler that has not settled after about **700 ms** counts as
  `false` (so do not wait for the network in it).
- `handled: true`: the app does nothing more. `false`, an error, or no answer in time:
  the default.
- **A long press on the back button always closes the web app**, whatever the page says.
- With several handlers (a dialog on top of a page) the newest is asked first; the first
  to return `true` wins.
- In the browser and in an app without the feature `onBackRequested` does nothing and
  returns a no-op cleanup.

Without the package: `BMSNative.call('setBackInterception', { enabled: true })`, define
`window.onNativeBackRequested = ({ source }) => …` and answer with
`BMSNative.call('backResult', { handled })` within 800 ms.

## Title, search, segments, sidebar, undo (2026-11b)

The page can hand more of its header to the app: the navigation title with a menu, a
search field, segments, an iPad sidebar and undo. All are parts of `setChrome`, need
`customChrome`, and each has its own feature flag (`hasFeature`): an app that lacks it
**ignores** that part, and in the browser `setChrome` does nothing, so the page keeps its
own header, search field, segmented control, list and undo button where `hasFeature` is
`false`. Omitting a part in a later `setChrome` removes it again. Development builds check
the limits of every part (`chromeLimitWarnings`) and say which part the app does not list.

```ts
import { setChrome, on, hasFeature } from '@bmsuisse/app-native'

setChrome({
  title: {
    text: 'Offer 4711',
    subtitle: 'Müller AG',
    menu: [{ items: [{ id: 'rename', label: 'Rename' }] }],
  },
  search: { id: 'offers', placeholder: 'Search offers' },
  segments: {
    id: 'view',
    items: [
      { id: 'lines', label: 'Lines' },
      { id: 'docs', label: 'Documents' },
    ],
    selected: 'lines',
  },
  undo: { canUndo: true, canRedo: false, undoLabel: 'Delete line' },
})
```

| Part                   | Feature        | Events (`on(…)`)                                                                        |
| ---------------------- | -------------- | --------------------------------------------------------------------------------------- |
| `title`                | `titleMenu`    | `titleMenuSelect` `{ id }`                                                              |
| `actionButtons[].menu` | `menus`        | `actionButtonMenuSelect` `{ buttonId, id }`                                             |
| `search`               | `navSearch`    | `search` `{ id, query, scope, submitted, source }`, `searchCancel` `{ id }`             |
| `segments`             | `segments`     | `segmentSelect` `{ id, item }`                                                          |
| `sidebar`              | `sidebar`      | `sidebarSelect` `{ id }`, `sidebarAction` `{ itemId, id }`, `sidebarSearch` `{ query }` |
| `undo`                 | `undoGestures` | `undo` `{ action: 'undo' \| 'redo' }`                                                   |

Every text is shown as delivered: localize it. The events are the globals
`window.onNativeTitleMenuSelect`, `onNativeActionButtonMenuSelect`, `onNativeSearch`,
`onNativeSearchCancel`, `onNativeSegmentSelect`, `onNativeSidebarSelect`,
`onNativeSidebarAction`, `onNativeSidebarSearch` and `onNativeUndo`; `on(…)` installs and
dispatches them.

### Title and title menu

`title: { text, subtitle?, menu?: MenuSection[] }` replaces the web app's name in the
native navigation bar. With a `menu` the title becomes a title menu (the usual "Offer
4711 ▾"); a selection arrives as `on('titleMenuSelect', ({ id }) => …)`. The menu follows
the rules of [`showMenu`](menus-and-alerts-guide.md#showmenu): two levels, 80 items,
labels of 80 characters, unique ids. Give the sections themselves: the lazy mechanism
(`children: 'lazy'`) is described for `showMenu` only, because these menus have no `menuId`
to answer to (the package warns in development builds).

### Menus on action buttons

`actionButtons: [{ id, icon, label?, menu?: MenuSection[] }]`. A button with a `menu`
opens a pull-down menu when tapped **instead of firing `actionButtonTap`**; a selection
arrives as `on('actionButtonMenuSelect', ({ buttonId, id }) => …)`. In an app without the
feature `menus` the button simply fires `actionButtonTap`, so handle both:

```ts
on('actionButtonTap', (id) => id === 'more' && openMyOwnMenu())
on('actionButtonMenuSelect', ({ buttonId, id }) => run(buttonId, id))
```

### Search field in the navigation bar

`search: { id, placeholder, value?, scopes?: [{ id, label }], scope?, barcode? }` shows a
native search field. The page drops its own. Events: `search` with `source` `typing`
(debounced 250 ms), `submit` (the Search key) or `barcode`, and `searchCancel`.
`barcode: true` (needs `camera`) adds a scan button; the scanned code arrives as `query`
with `source: 'barcode'` and `submitted: true`.

### Segments

`segments: { id, items: [{ id, label, badge? }], selected }`: 2 to 5 items, `badge` a
short string. A segmented control directly under the navigation bar; a tap selects it and
calls `segmentSelect`. Replace the page's own tab/filter chips.

### iPad sidebar

`sidebar: { title, search?: { placeholder }, sections: [{ title?, items: [{ id, label,
subtitle?, icon?, badge?, selected?, trailingActions? }] }], footer? }`, at most 300 items.
A native, collapsible column with the web view to its right (a toggle button sits in the
navigation bar). **Only in the regular horizontal size class**: in compact width the app
ignores it and the page shows its own list, so decide with `data-bms-size-class` (or
`on('layoutChange')`) which UI to render:

```ts
const useNativeSidebar =
  hasFeature('sidebar') && document.documentElement.dataset.bmsSizeClass === 'regular'
```

Sending it again replaces the content and keeps the scroll position and the selection.
Swipe actions (`trailingActions`, `style: 'destructive'`) arrive as `sidebarAction`; typing
in the sidebar search as `sidebarSearch` (debounced 250 ms).

### Undo gestures

`undo: { canUndo, canRedo, undoLabel?, redoLabel? }` enables shake to undo, the iPad
three-finger undo/redo gestures and the Undo/Redo entries of the edit menu. Each calls
`on('undo', ({ action }) => …)` with `'undo'` or `'redo'`; the app shows the labels where
iOS shows an action name ("Undo Delete line"). Call `setChrome` again whenever
`canUndo`/`canRedo` change; omitting `undo` disables the gestures.

## Keyboard toolbar

`setKeyboardToolbar({ items: [{ id, label?, icon?, style?: 'plain' | 'prominent' }], done? })`
puts a native toolbar above the on-screen keyboard while a field of the page has focus: at
most 6 items, each with a `label` or an `icon`; `done: true` adds a trailing Done button
that blurs the field. A tap arrives as `on('keyboardToolbarTap', ({ id }) => …)` and
**keeps the focus**. `{ items: [] }` removes it; it is not shown with a hardware keyboard.
Feature `keyboardToolbar`, needs `customChrome`.

```ts
await setKeyboardToolbar({
  items: [
    { id: 'prev', icon: 'chevron.up' },
    { id: 'next', icon: 'chevron.down' },
    { id: 'add', label: 'Add line', style: 'prominent' },
  ],
  done: true,
})
on('keyboardToolbarTap', ({ id }) => run(id))
```

## Key commands

`setKeyCommands({ commands: [{ id, input, modifiers, title, group? }] })` registers
hardware key commands (an extension of the iPad section above): at most 60; `input` is one
character or `up`, `down`, `left`, `right`, `escape`, `return`, `tab`, `delete`;
`modifiers` a possibly empty list of `command`, `option`, `shift`, `control`.

- Only with a hardware keyboard. Registered commands appear in the iPad ⌘-hold overlay and
  the menu bar under `group`.
- **The app consumes a registered command** and calls `on('keyCommand', ({ id }) => …)`
  _instead of_ the DOM `keydown`. Keys that are not registered keep the behaviour above:
  they reach the page as `keydown`.
- A command **without modifiers** fires only while **no text field** of the page has
  focus (so an `escape` or `down` command does not steal keys from an input).
- `{ commands: [] }` removes them. Feature `keyCommands`, needs `customChrome`.

```ts
await setKeyCommands({
  commands: [
    { id: 'search', input: 'k', modifiers: ['command'], title: 'Search', group: 'Offers' },
    { id: 'next-line', input: 'down', modifiers: [], title: 'Next line', group: 'Navigate' },
  ],
})
on('keyCommand', ({ id }) => run(id))
// the browser has no feature: listen to keydown there, it does not fire in the app for these keys
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
  BMSNative.features // e.g. ["scanResult", "pickFiles", "layout", ...]; missing in older apps
}
```

`BMSNative.features` lists the contract features the app implements: `scanResult`,
`scanOptions`, `pickFiles`, `receiveDocuments`, `mediaCapture`, `dictate`, `layout`,
`backInterception`, `previewFile`, `tokenResources`, and since 2026-11b `menus`,
`titleMenu`, `alerts`, `toastActions`, `liveSurfaces`, `pageSearch`, `navSearch`,
`keyboardToolbar`, `segments`, `sidebar`, `documentViewer`, `undoGestures`, `pickers`,
`keyCommands`. What is not listed is not
supported; an older app has no `features` at all (treat it as an empty list). With the
package: `hasFeature('pickFiles')`. Every package function that depends on a feature
answers `unavailable` without asking an app that lacks it.

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
`"forbidden"`, `"notSignedIn"` and `"consentRequired"` for `getAccessToken`;
`"forbidden"`, `"busy"` and `"tooLarge"` for `showForm`/`showContent`; `"tooLarge"` for a
document beyond 25,000,000 bytes). Actions without a result of
their own respond immediately once the app has accepted them. `showForm` and
`showContent` resolve once the user is done.

```js
const { ok } = await BMSNative.call('biometricConfirm', { reason: 'Approve order 4711' })
```

### Overview

| Action                                                             | Fields                                                                                                                     | Capability                         | Effect                                                                                                                                                                                                                                                                                |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `share`                                                            | `title?`, `text?`, `url?` (at least one)                                                                                   | —                                  | Native share sheet. Responds with `ok: false, error: "cancelled"` if the user cancels                                                                                                                                                                                                 |
| `haptic`                                                           | `style`: `light` \| `medium` (default) \| `heavy` \| `soft` \| `rigid` \| `selection` \| `success` \| `warning` \| `error` | —                                  | Haptic feedback                                                                                                                                                                                                                                                                       |
| `toast`                                                            | `message`, `style?`: `info` \| `success` \| `warning` \| `error`, `duration?` (seconds, default 2.5)                       | —                                  | Short native banner at the bottom                                                                                                                                                                                                                                                     |
| `setBadge`                                                         | `count` (`0` removes it)                                                                                                   | —                                  | Red number badge on your tile in the Apps tab or — as a fixed tab — on your tab in the tab bar. Doesn't count toward the badge on the app icon — that only shows unread notifications. Persists across app restarts                                                                   |
| `openExternal`                                                     | `url`                                                                                                                      | —                                  | Deliberately opens the URL outside the app (in Safari or the responsible app)                                                                                                                                                                                                         |
| `biometricConfirm`                                                 | `reason?`                                                                                                                  | —                                  | Face ID/Touch ID, falling back to the device passcode. **Only a confirmation on the device, not proof for your backend** — keep securing security-critical approvals on the server side                                                                                               |
| `setWidgets` / `updateWidget` / `removeWidgets` / `refreshWidgets` | see guide                                                                                                                  | `.dashboardWidgets`                | Widgets on the Home dashboard — see [dashboard-widgets-guide.md](dashboard-widgets-guide.md)                                                                                                                                                                                          |
| `refreshApprovals`                                                 | —                                                                                                                          | `.approvals`                       | Immediately reloads your pending approvals on Home, e.g. after the page itself has approved something — see [approvals-guide.md](approvals-guide.md)                                                                                                                                  |
| `getAccessToken`                                                   | `refresh?`, `resource?`, `interactive?`                                                                                    | `.identity`                        | The Entra ID token of the app's sign-in, for the places where the browser cannot set a header (`WebSocket`, `EventSource`, a web worker, which gets the token from the page). `fetch`/XHR to your own backend get it automatically — see [entra-token-guide.md](entra-token-guide.md) |
| `scanDocument`                                                     | `context?`, `kind?`, `mode?`, `multiple?`                                                                                  | `.camera`                          | Document scanner; each document is a PDF, uploaded or returned — see [scan-guide.md](scan-guide.md)                                                                                                                                                                                   |
| `pickFiles`                                                        | `sources`, `accept?`, `multiple?`, `mode?`, `context?`, `kind?`                                                            | `.camera` for the camera source    | Picks files, photos or a camera shot; uploaded or returned — see [documents-guide.md](documents-guide.md)                                                                                                                                                                             |
| `consumeReceivedDocuments`                                         | —                                                                                                                          | —                                  | Documents shared into the web app while the page was not listening; clears the queue — see [documents-guide.md](documents-guide.md)                                                                                                                                                   |
| `previewFile`                                                      | `url`, `filename?`                                                                                                         | —                                  | Downloads a file of the web app's own origin and opens the native preview — see [documents-guide.md](documents-guide.md)                                                                                                                                                              |
| `dictate`                                                          | `locale?`, `maxSeconds?`, `contextualStrings?`                                                                             | `.microphone`                      | Native dictation sheet; resolves with the text — see [voice-guide.md](voice-guide.md)                                                                                                                                                                                                 |
| `getLayout`                                                        | —                                                                                                                          | —                                  | Keyboard height, size class, orientation and size of the web view (see "Layout" above)                                                                                                                                                                                                |
| `setBackInterception` / `backResult`                               | `enabled` / `handled`                                                                                                      | —                                  | The page takes over the back button and swipe (see "Intercepting the back button" above)                                                                                                                                                                                              |
| `showMenu`                                                         | `id?`, `anchor`, `preview?`, `sections`                                                                                    | `.customChrome`                    | Native menu at an anchor (context menu on iPhone), lazy submenus — see [menus-and-alerts-guide.md](menus-and-alerts-guide.md)                                                                                                                                                         |
| `menuItems`                                                        | `requestId`, `sections`                                                                                                    | `.customChrome`                    | The page's answer to `onNativeMenuExpand` within 5 s                                                                                                                                                                                                                                  |
| `showAlert`                                                        | `title`, `message?`, `style?`, `anchor?`, `actions`, `textField?`                                                          | `.customChrome`                    | Native alert or action sheet — see [menus-and-alerts-guide.md](menus-and-alerts-guide.md)                                                                                                                                                                                             |
| `toast` (with `call`)                                              | `message`, `style?`, `duration?`, `action?`                                                                                | —                                  | Resolves `{ ok, toastId }`; a tap on `action` calls `onNativeToastAction`                                                                                                                                                                                                             |
| `showPicker`                                                       | `kind`, `anchor?`, `title?`, `value?`, `min?`, `max?`, `options?`                                                          | `.customChrome`                    | Native date or option picker                                                                                                                                                                                                                                                          |
| `updateSurface` / `surfaceSearchResult`                            | see [native-surfaces-guide.md](native-surfaces-guide.md#live-surfaces)                                                     | `.customChrome` + a surface        | Changes the open surface; the page's answer to a page search                                                                                                                                                                                                                          |
| `setKeyboardToolbar`                                               | `items`, `done?`                                                                                                           | `.customChrome`                    | Toolbar above the on-screen keyboard (see "Keyboard toolbar" above)                                                                                                                                                                                                                   |
| `showDocument` / `updateDocument`                                  | `url`, `highlights?`, … / `id`, …                                                                                          | `.customChrome`                    | Native PDF viewer with highlights — see [documents-guide.md](documents-guide.md#showdocument-the-native-viewer)                                                                                                                                                                       |
| `setKeyCommands`                                                   | `commands`                                                                                                                 | `.customChrome`                    | Hardware key commands (see "Key commands" above)                                                                                                                                                                                                                                      |
| `navigate`                                                         | `destination` (place or text), `waypoints?`, `mode?`, `app?`                                                               | —                                  | Starts a route in Apple Maps, Google Maps or Waze — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                            |
| `addReminder`                                                      | `title`, `due?`, `allDay?`, `notes?`, `priority?`, `list?`, `url?`, `confirm?`                                             | `.deviceApps`                      | Creates a reminder in Apple Reminders (asks first) — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                           |
| `saveContact`                                                      | `givenName?`, `familyName?`, `organization?`, `jobTitle?`, `phones?`, `emails?`, `address?`, `url?`, `confirm?`            | `.deviceApps`                      | Saves a contact (system form first) — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                                          |
| `callPhone`                                                        | `number`                                                                                                                   | —                                  | Starts a phone call; iOS asks before dialing — see [device-actions-guide.md](device-actions-guide.md)                                                                                                                                                                                 |
| `showForm`                                                         | `id?`, `title?`, `size?`, `tint?`, `context?`, `text?`, `values?`, `fields?` or `pages?`, `submit?`                        | `.nativeForms`                     | Opens a native form as an iOS sheet; the call resolves once with the values — see [native-surfaces-guide.md](native-surfaces-guide.md)                                                                                                                                                |
| `showContent`                                                      | `id?`, `title?`, `subtitle?`, `size?`, `tint?`, `context?`, `blocks`, `actions?`                                           | `.nativeContent`                   | Opens native content (text, image, table, map, …) as an iOS sheet; resolves with the tapped action — see [native-surfaces-guide.md](native-surfaces-guide.md)                                                                                                                         |
| `closeSurface`                                                     | `id?`                                                                                                                      | `.nativeForms` or `.nativeContent` | Closes the open surface; the pending `showForm`/`showContent` resolves `cancelled`                                                                                                                                                                                                    |
| `surfaceResult`                                                    | `id`, `ok`, `message?`, `fieldErrors?`, `then?`                                                                            | `.nativeForms` or `.nativeContent` | The page's answer in a round trip (see below): `ok: true` closes the surface, `ok: false` keeps it open and marks the fields                                                                                                                                                          |

```js
window.webkit.messageHandlers.nativeBridge.postMessage({
  action: 'toast',
  message: 'Saved',
  style: 'success',
})
BMSNative.call('share', { title: 'Order 4711', url: location.href })
```

**Callback `window.onNativeSurfaceAction({ id, action, values?, context? })`:**
when a native form was submitted with `submit.wait: true`, or a content action
with `wait: true` was tapped, the app keeps the surface open and calls this
function. Answer within 60 seconds with `BMSNative.call('surfaceResult', …)`.
With the npm package you do not write this yourself: `showForm(def, { onSubmit })`
and `showContent(def, { onAction })` do it. See
[native-surfaces-guide.md](native-surfaces-guide.md).

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
