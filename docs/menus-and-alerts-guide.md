# Menus, alerts, toasts and pickers

This guide is for web apps that want **every menu, confirmation, toast and picker that
iOS can draw natively to be native**: a context menu on a line, a "Delete this offer?"
alert, a toast with "Undo", a date picker. The page drops its own popovers and dialogs
wherever the app offers the native counterpart, and keeps them everywhere else.

Package: [`@bmsuisse/app-native`](../packages/app-native), file
[`menus.ts`](../packages/app-native/src/menus.ts) (and `toast` in
[`ui.ts`](../packages/app-native/src/ui.ts)). Menus of the navigation bar (the title
menu, the menu of an action button) are in the
[chrome guide](webapp-chrome-guide.md#title-and-title-menu).

```ts
import { showMenu, showAlert, showPicker, toast, anchorOf, hasFeature } from '@bmsuisse/app-native'
```

| Function                              | Feature        | Browser       |
| ------------------------------------- | -------------- | ------------- |
| `showMenu(options)`                   | `menus`        | `unavailable` |
| `setChrome({ actionButtons[].menu })` | `menus`        | ignored       |
| `setChrome({ title: { menu } })`      | `titleMenu`    | ignored       |
| `showAlert(options)`                  | `alerts`       | `unavailable` |
| `toast(message, { action, … })`       | `toastActions` | `unavailable` |
| `showPicker(options)`                 | `pickers`      | `unavailable` |

All of them need the capability **`customChrome`** (else `capability`) and answer
`unavailable` outside the app and in an app that does not list the feature
(`hasFeature(…)`), **without asking the app**. An app that answers `unknownAction` is
`unavailable` too. Nothing throws, and **nothing falls back to `window.confirm`,
`prompt`, `<input type="date">` or any other browser UI**: the page keeps its own UI for
those cases.

```ts
async function confirmDelete(): Promise<boolean> {
  if (!hasFeature('alerts')) return await myOwnConfirmDialog()
  const res = await showAlert({
    title: 'Delete offer?',
    message: 'This cannot be undone.',
    actions: [
      { id: 'cancel', label: 'Cancel', style: 'cancel' },
      { id: 'delete', label: 'Delete', style: 'destructive' },
    ],
  })
  return res.ok && res.id === 'delete'
}
```

**Every text is shown as delivered**: the app does not translate. Localize labels, titles
and messages yourself.

**Anchors.** `anchor` is `{ x, y, width, height }` in CSS px, relative to the visible
viewport of the web view: what `element.getBoundingClientRect()` returns. `anchorOf(element)`
does that.

**Validation.** The package checks every limit below **before** asking the app: a menu
over the limits, a toast with `duration: 0.5`, an alert with seven actions answer
`{ ok: false, error: 'invalid', message }` and the app is not called (development builds
also log a warning). The `message` is an English sentence for the developer.

## `showMenu`

```ts
const res = await showMenu({
  anchor: anchorOf(rowButton),
  preview: { title: 'Offer 4711', subtitle: 'Müller AG' },
  sections: [
    {
      title: 'Offer',
      items: [
        { id: 'open', label: 'Open', icon: 'doc' },
        { id: 'pinned', label: 'Pinned', checked: true },
        {
          id: 'export',
          label: 'Export as …',
          children: [{ items: [{ id: 'pdf', label: 'PDF' }] }],
        },
        { id: 'send', label: 'Send to …', children: 'lazy', lazyFailedLabel: 'Could not load' },
      ],
    },
    { items: [{ id: 'delete', label: 'Delete', icon: 'trash', destructive: true }] },
  ],
  loadChildren: async (itemId) => await api.recipients(itemId), // for the lazy items
})
if (res.ok) run(res.id)
```

| Option         | Meaning                                                                             |
| -------------- | ----------------------------------------------------------------------------------- |
| `id`           | Echoed in the lazy-children event; generated if missing and `loadChildren` is given |
| `anchor`       | Where the menu comes from                                                           |
| `preview`      | `{ title, subtitle? }`. iPhone: the card that is lifted from the anchor             |
| `sections`     | `{ title?, items }[]`                                                               |
| `loadChildren` | Package option, not sent: answers the lazy items, see below                         |

An item is `{ id, label, subtitle?, icon? (SF Symbol), destructive?, disabled?, checked?,
children?: MenuSection[] | "lazy", lazyFailedLabel? }`. The result is `{ ok: true, id }`
with the id of the chosen item.

**iPhone** shows a context menu at the anchor with a lifted preview card built from
`preview`; **iPad** shows a menu at the anchor, and a secondary (trackpad) click opens the
same menu.

| Limit                             | Value                              |
| --------------------------------- | ---------------------------------- |
| Levels of submenus below the root | 2                                  |
| Items in total (all levels)       | 80                                 |
| Characters of a label             | 80                                 |
| Ids                               | unique within the menu, all levels |

Errors: `cancelled` (dismissed), `invalid`, `busy` (a menu is already open), `capability`,
`unavailable`.

### Lazy submenus

An item with `children: 'lazy'` loads its submenu when the user opens it, for example a
list of recipients from your backend. With the package you pass `loadChildren(itemId)`;
it handles the rest:

1. The app calls `window.onNativeMenuExpand({ menuId, itemId, requestId })` and shows a
   loading row.
2. The package calls `loadChildren(itemId)` and answers
   `BMSNative.call('menuItems', { requestId, sections })`.
3. The app waits **5 seconds**. After that it shows one disabled row with the item's
   `lazyFailedLabel`, or `–` if none is set. A `loadChildren` that rejects, or returns
   sections that break the limits (together with the items the menu already has), is
   **not** answered, so the user sees that row; development builds log why.

Answer quickly: keep what you load small and cache it. Without the package: define
`window.onNativeMenuExpand`, read `menuId`, `itemId` and `requestId`, and call `menuItems`
with the same `requestId`.

## `showAlert`

```ts
const res = await showAlert({
  title: 'Rename',
  actions: [
    { id: 'cancel', label: 'Cancel', style: 'cancel' },
    { id: 'ok', label: 'OK', preferred: true },
  ],
  textField: { placeholder: 'Name', value: offer.name, keyboard: 'default', maxLength: 40 },
})
if (res.ok && res.id === 'ok') rename(res.text)
```

| Option      | Meaning                                                                                                |
| ----------- | ------------------------------------------------------------------------------------------------------ |
| `title`     | Required                                                                                               |
| `message`   | Optional                                                                                               |
| `style`     | `alert` (default) or `actionSheet`                                                                     |
| `anchor`    | iPad: an action sheet is a popover at the anchor. Required there; without it the app centres it        |
| `actions`   | 1 to 6 `{ id, label, style?: default \| cancel \| destructive, preferred? }`, at most one `cancel`     |
| `textField` | `{ placeholder?, value?, keyboard?: default \| decimal \| number \| email, maxLength? }`. `alert` only |

The result is `{ ok: true, id }`, with `text` when there was a `textField`. A tap outside
an action sheet counts as the `cancel` action, or `{ ok: false, error: 'cancelled' }` when
there is none. Errors: `cancelled`, `invalid`, `capability`, `unavailable`.

## Toasts with an action

`toast(message, style?, duration?)` is fire-and-forget, as it always was. The form with an
options object (feature `toastActions`) has a response and an optional button:

```ts
const res = await toast('Offer deleted', {
  style: 'success',
  action: { id: 'undo', label: 'Undo' },
  onAction: () => restore(),
})
```

- It resolves `{ ok: true, toastId }` once the toast is shown.
- `duration` is **1 to 10 seconds**, default 2.5, or 6 with an action.
- A tap on the action calls `onAction(action.id)` once and **closes the toast**.
- The toast sits above the native bottom bar and above the keyboard. **A new toast replaces
  the visible one**; the old one's `onAction` is dropped with it.
- Without the feature (and in the browser) the form with options is `unavailable`: show
  your own toast, or use the old form `toast(message, 'success')`, which the app ignores in
  the browser.

Without the package: `BMSNative.call('toast', { message, style, duration, action })` and
`window.onNativeToastAction = ({ toastId, id }) => …`.

## `showPicker`

```ts
const date = await showPicker({
  kind: 'date',
  title: 'Valid until',
  value: '2026-11-30',
  min: '2026-11-11',
})
if (date.ok) offer.validUntil = date.value // YYYY-MM-DD

const unit = await showPicker({
  kind: 'option',
  anchor: anchorOf(unitButton),
  options: [
    { value: 'pcs', label: 'Pieces' },
    { value: 'pal', label: 'Pallets', subtitle: 'à 48' },
  ],
})
```

| Option       | Meaning                                                       |
| ------------ | ------------------------------------------------------------- |
| `kind`       | `date` or `option`                                            |
| `anchor`     | iPad: a popover at the anchor. iPhone: a compact bottom sheet |
| `title`      | Optional                                                      |
| `value`      | The preselected value                                         |
| `min`, `max` | `date` only                                                   |
| `options`    | `option` only: 1 to 200 `{ value, label, subtitle? }`         |

Dates are `YYYY-MM-DD` strings, checked as real calendar dates. It resolves
`{ ok: true, value }` or `cancelled`.

## Building menus and search results on the backend

If your backend decides what a menu contains, it can serve it with the Pydantic models of
[`bmsdna-app-native`](../python/app-native/bmsdna/app_native/menus.py), which check the
limits above:

```python
from bmsdna.app_native import MenuItem, MenuSection, NativeMenu


@app.get(
    "/api/offers/{offer_id}/menu", response_model_by_alias=True, response_model_exclude_none=True
)
async def offer_menu(offer_id: str) -> NativeMenu:
    return NativeMenu(
        sections=[
            MenuSection(
                items=[
                    MenuItem(id="open", label="Open"),
                    MenuItem(id="send", label="Send to …", children="lazy"),
                ]
            )
        ]
    )
```

The page passes `{ ...menu, anchor }` to `showMenu`. `check_menu_sections(sections, depth=…,
taken_ids=…, taken_items=…)` checks the sections that answer a lazy item.
`SurfaceSearchOption` and `SurfaceSearchAnswer` are the models for the results of a search
field with `source: 'page'` (see the [surfaces guide](native-surfaces-guide.md#live-surfaces)).
