# Native forms and content for web app developers

A web app that runs inside the BMS app can open **native iOS screens** from a
button on its own page, as standard iOS sheets:

- a **form** to fill in (`showForm`): single or multi page, many field types,
  camera fields (photo, document scan, barcode), a signature, repeating
  groups, and a round trip to your backend for field errors;
- **content** (`showContent`): information built from blocks: text, image,
  facts, list, table, map, file, key figures, buttons.

Both are described as JSON by your page, rendered by the app, and answer
**once**: when the user submits, taps an action or dismisses the sheet.

When to use it:

| Example                                                              | Use                                                  |
| -------------------------------------------------------------------- | ---------------------------------------------------- |
| "Create customer" with a business card photo and a signature         | `showForm`, multi page, `photo` and `signature`      |
| An info card for a customer with phone, address, map and two buttons | `showContent`                                        |
| A small sheet next to a list: "Reject — why?" with one text field    | `showForm`, `size: 'fit'`                            |
| Show "Customer created" with a "New order" button after a form       | `showContent` in a chained flow                      |
| Anything that needs your own layout, scripts, or a sign-in           | your web UI, not this: it is not an embedded browser |

Package: [`@bmsuisse/app-native`](../packages/app-native), file
[`surfaces.ts`](../packages/app-native/src/surfaces.ts). Backend side (models for
the definitions, the document and option routers):
[`surfaces.py`](../python/app-native/bmsdna/app_native/surfaces.py),
[`documents.py`](../python/app-native/bmsdna/app_native/documents.py).

```ts
import {
  showForm,
  showContent,
  closeSurface,
  canShowNativeForms,
  canShowNativeContent,
  isNativeSurfaceUnsupported,
} from '@bmsuisse/app-native'
```

## At a glance

| Function                              | What it does                                                          | Capability                       |
| ------------------------------------- | --------------------------------------------------------------------- | -------------------------------- |
| `showForm(def, { onSubmit? })`        | Opens a native form                                                   | `nativeForms`                    |
| `showContent(def, { onAction? })`     | Opens a native content screen                                         | `nativeContent`                  |
| `closeSurface({ id? })`               | Closes the open surface of your web app                               | `nativeForms` or `nativeContent` |
| `surfaceResult({ id, ok, … })`        | The page's answer in a round trip (low level)                         | `nativeForms` or `nativeContent` |
| `on('surfaceAction', …)`              | The app asks the page in a round trip (low level)                     | –                                |
| `onSurfaceAction(id, handler)`        | Answers the round trip of one surface by its `id`, e.g. a chained one | –                                |
| `canShowNativeForms()` / `…Content()` | Is it available here? Use it to keep your web UI                      | –                                |
| `isNativeSurfaceUnsupported(result)`  | Did the call fail because the feature is not here?                    | –                                |

## Capabilities

The app must have enabled the capability for your web app (it is part of the
web app's configuration in the app, like `camera` or `deviceApps`):

| Capability      | Needed for                      |
| --------------- | ------------------------------- |
| `nativeForms`   | `showForm`                      |
| `nativeContent` | `showContent`                   |
| either of them  | `closeSurface`, `surfaceResult` |

Some parts need more, because they use other features of the iPhone:

| Part                                                             | Also needs                                                                         |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Form fields `photo` with the camera as source, `scan`, `barcode` | `camera`                                                                           |
| Media fields `photo`, `scan`, `signature` (they upload)          | the document router of your backend ([below](#media-fields-and-the-native-upload)) |
| Follow-up actions `saveContact` and `addReminder` (in `then`)    | `deviceApps`                                                                       |

A missing capability answers `{ ok: false, error: 'capability' }`.
`can('nativeForms')` tells you in advance, or `canShowNativeForms()`.

Opening a surface is further restricted to the **main frame of your web app's
own origin**: an iframe or a foreign page that ended up in the web view answers
`forbidden`.

## The four sizes

`size` is one of the standard iOS sheet sizes. There is no custom popover.

| `size`   | Looks like                                                                                                     | Good for                                    |
| -------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `full`   | A full-screen cover.                                                                                           | Long forms, long content                    |
| `large`  | A sheet that is almost as high as the screen, the previous screen peeking out above it. **Default for forms.** | Forms of normal length                      |
| `medium` | A sheet of half the screen height that the user can pull up to `large`. **Default for content.**               | Info cards, a few lines of content          |
| `fit`    | A sheet exactly as high as its content, at most `large`. The "small" size.                                     | 1–3 fields, a confirmation, a short message |

On iPad the sheets appear as the usual centered form sheets.

## `showForm`

```ts
const result = await showForm({
  id: 'new-customer',
  title: 'New customer',
  size: 'large',
  text: 'Fill in the basic data.', // intro text on the first page
  values: { type: 'b2b' }, // prefill by field id
  pages: [
    {
      title: 'Company',
      fields: [
        { id: 'name', type: 'text', label: 'Company name', required: true },
        {
          id: 'type',
          type: 'segmented',
          label: 'Type',
          options: [
            { value: 'b2b', label: 'B2B' },
            { value: 'b2c', label: 'B2C' },
          ],
        },
        {
          id: 'vat',
          type: 'text',
          label: 'VAT number',
          visibleIf: { field: 'type', equals: 'b2b' },
        },
      ],
    },
    {
      title: 'Contact',
      fields: [
        { id: 'email', type: 'email', label: 'Email', required: true },
        { id: 'owner', type: 'search', label: 'Account manager', minQueryLength: 2 },
        { id: 'card', type: 'photo', label: 'Business card', max: 1 },
        { id: 'notes', type: 'textarea', label: 'Notes', maxLength: 500 },
      ],
    },
  ],
  submit: { label: 'Create customer', confirm: 'Create this customer?' },
})

if (result.ok) {
  // result.values, result.labels
} else if (result.error === 'cancelled') {
  // the user dismissed the form
}
```

### Definition

| Field     | Type                                              | Meaning                                                                                                                                                                                                                     |
| --------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`      | `string`                                          | Echoed in results and events; used by `closeSurface`, `surfaceResult` and as `form_id` towards your backend. The app generates one if missing.                                                                              |
| `title`   | `string`                                          | Title in the navigation bar.                                                                                                                                                                                                |
| `size`    | `full` `large` `medium` `fit`                     | Default `large`.                                                                                                                                                                                                            |
| `tint`    | `#rrggbb`                                         | Accent color of the surface.                                                                                                                                                                                                |
| `context` | `object`                                          | Opaque to the app: echoed in results and sent along with option lookups and uploads (`context` there).                                                                                                                      |
| `text`    | `string`                                          | Intro text on the first page.                                                                                                                                                                                               |
| `values`  | `object`                                          | Prefill by field id.                                                                                                                                                                                                        |
| `fields`  | `Field[]`                                         | Single-page form. Or:                                                                                                                                                                                                       |
| `pages`   | `{ title?, text?, fields }[]`                     | Multi-page form (not both). The user pages through with "Continue"; "Step n of m" counts visible pages.                                                                                                                     |
| `submit`  | `{ label?, confirm?, biometric?, style?, wait? }` | The submit button: its `label`, a `confirm` prompt, Face ID first (`biometric`, UX only, no proof for your backend), `style` `primary` / `destructive`, and `wait` for the [round trip](#round-trip-onsubmit-and-onaction). |

The surface always shows your web app's **name and icon**; you cannot remove
that. Titles and texts are shown as you deliver them: the app does not
translate them.

### Field types

The fields are the same as in the forms of
[dashboard widgets](dashboard-widgets-guide.md#action--form--buttons-default-medium).
An older app shows a type it does not know as `text`: see
[Old app versions](#fallback-browsers-and-old-app-versions).

| `type`        | Shows                                                                                                                                                                                                                            | In the result `values`                          |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `text`        | Single-line text (the default type)                                                                                                                                                                                              | `string`                                        |
| `number`      | Number                                                                                                                                                                                                                           | `number`                                        |
| `select`      | One of `options`; with `remote: true` loaded from your backend                                                                                                                                                                   | `string` (the option `value`), text in `labels` |
| `toggle`      | Switch                                                                                                                                                                                                                           | `boolean`                                       |
| `date`        | Date                                                                                                                                                                                                                             | `string` `yyyy-MM-dd`                           |
| `search`      | Search field; results come from your backend (`minQueryLength`, default 2)                                                                                                                                                       | `string` (the option `value`), text in `labels` |
| `textarea`    | Multi-line text; `maxLength` shows a counter                                                                                                                                                                                     | `string`                                        |
| `email`       | Text with the email keyboard and a format check                                                                                                                                                                                  | `string`                                        |
| `phone`       | Text with the phone keyboard                                                                                                                                                                                                     | `string`                                        |
| `url`         | Text with the URL keyboard and a format check                                                                                                                                                                                    | `string`                                        |
| `multiselect` | Choose any number of `options`                                                                                                                                                                                                   | `string[]`                                      |
| `segmented`   | A few `options` as a segmented control                                                                                                                                                                                           | `string`                                        |
| `stepper`     | Whole number with + and −: `min`, `max`, `step`                                                                                                                                                                                  | `number`                                        |
| `time`        | Time of day                                                                                                                                                                                                                      | `string` `HH:mm`                                |
| `datetime`    | Date and time, device local, no time zone                                                                                                                                                                                        | `string` `yyyy-MM-ddTHH:mm`                     |
| `info`        | Read-only row (`label`, `value`)                                                                                                                                                                                                 | not part of the result                          |
| `photo`       | Camera and/or library. `max` 1–10 (default 5), `source` `camera` / `library` / `both`, `maxDimension` 256–4096 (default 2048)                                                                                                    | `NativeFileRef[]`                               |
| `scan`        | Document scanner. `format` `jpeg` (default, one file per page) or `pdf` (one file), `max` pages 1–20 (default 10)                                                                                                                | `NativeFileRef[]`                               |
| `signature`   | Drawn with finger or pencil, PNG                                                                                                                                                                                                 | `NativeFileRef[]` (one)                         |
| `barcode`     | Text field with a button that scans a barcode/QR code; `symbologies` restricts the scanner to some of `aztec`, `codabar`, `code39`, `code93`, `code128`, `dataMatrix`, `ean8`, `ean13`, `i2of5`, `itf14`, `pdf417`, `qr`, `upce` | `string`                                        |
| `repeat`      | Repeating group (order lines): `fields`, `min`, `max` (at most 50), `addLabel`. Inside only `text`, `number`, `select`, `toggle`, `date`, `textarea`, `stepper`; no nesting, and no `visibleIf` inside the group                 | array of objects, one per row                   |

There is deliberately **no password or secret field**: forms are not for
signing in.

Properties of every field: `id` (required, unique across all pages), `label`,
`placeholder`, `help` (a footnote under the field), `required`, `value`
(prefill), `valueLabel` (display text for a prefilled `search` or remote
`select`), `visibleIf`. Options: `{ value, label?, subtitle? }` (the subtitle
shows in search results and remote lists).

Validation, checked in the form and shown inline, blocking "Continue" and
submit; hidden fields never block:

| Property                    | For                                                                                                 |
| --------------------------- | --------------------------------------------------------------------------------------------------- |
| `required`                  | every field                                                                                         |
| `minLength`, `maxLength`    | `text`, `textarea`, `email`, `phone`, `url`, `barcode`                                              |
| `min`, `max`                | `number`, `stepper`; `photo` (`max` = pictures); `repeat` (rows)                                    |
| `pattern`, `patternMessage` | text fields: a regular expression the whole input has to match, and the text shown when it does not |

The shown texts are delivered by you, so put the language of your users in
`patternMessage`. `visibleIf` works as in widget forms: `{ field, equals? }`
with a value or a list of values, and the field may be on an earlier page.

### The result

```ts
type NativeFormResult =
  | {
      ok: true
      id: string
      action: 'submit'
      values: Record<string, string | number | boolean | string[] | NativeFileRef[] | object[]>
      labels: Record<string, string> // the shown text of search/select fields, by field id
      context?: object // as you sent it
      next?: NativeSurfaceResult // the last result of a chained flow
    }
  | { ok: false; error: NativeSurfaceError; message?: string }
```

Numbers arrive as numbers, toggles as booleans, dates as `yyyy-MM-dd`;
**empty and hidden fields are omitted**. `labels` saves you a second lookup:
for the field `owner` it holds the name that the user picked, while `values.owner`
holds the id.

When the user has entered something, the form can no longer be swiped away by
accident: "Cancel" asks "Discard input?" first.

## `showContent`

```ts
const result = await showContent({
  id: 'customer-123',
  title: 'Miller Ltd',
  size: 'medium',
  blocks: [
    { type: 'image', url: 'https://example.com/logo.png', height: 140 },
    { type: 'badges', items: [{ text: 'Key account', tint: '#2e4a62' }] },
    {
      type: 'facts',
      items: [
        { label: 'Phone', value: '+41 44 000 00 00', kind: 'phone' },
        { label: 'Address', value: 'Bahnhofstrasse 1, 8001 Zurich', kind: 'address' },
      ],
    },
    { type: 'text', markdown: 'Prefers **delivery on Tuesdays**.' },
  ],
  actions: [
    { id: 'new-order', label: 'New order', style: 'primary' },
    {
      id: 'route',
      label: 'Route',
      icon: 'location',
      then: [
        { device: { action: 'navigate', destination: { address: 'Bahnhofstrasse 1, Zurich' } } },
      ],
    },
  ],
})
// { ok: true, id: 'customer-123', action: 'new-order' | 'route' | 'dismiss', … }
```

### Definition

Same `id`, `title`, `size` (default `medium`), `tint` and `context` as for
forms, plus:

| Field      | Type       | Meaning                                                                     |
| ---------- | ---------- | --------------------------------------------------------------------------- |
| `subtitle` | `string`   | Line under the title.                                                       |
| `blocks`   | `Block[]`  | The content, top to bottom. At least 1, at most 100 (nested ones included). |
| `actions`  | `Action[]` | Buttons in the footer, at most 4.                                           |

### Blocks

| `type`                              | Fields                                                                                                                                                                                        |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `heading`                           | `text`, `level` 1–3, `icon` (SF Symbol)                                                                                                                                                       |
| `text`                              | `markdown` (paragraphs, lists, quotes, tables, bold/italic/links; **no HTML**), `style` `body` / `caption` / `footnote`, `align` `leading` / `center` / `trailing`                            |
| `image`                             | `url` (https) or `data` (`data:image/…`, at most 1 MB), `alt` (for VoiceOver), `caption`, `height`, `fit` `fit` / `fill`, `shape` `rounded` / `circle` / `none`, `tapToZoom`                  |
| `facts`                             | `items[{ label, value, kind, icon, copyable }]`, at least 1; `kind` `text` / `phone` / `email` / `address` / `url`: phone, email, address and url rows are tappable (call, mail, route, open) |
| `list`                              | `items[{ title, subtitle, trailing, icon, image, action }]`, at least 1; `image` is an `https` URL (not a `data:` URI); a row with an `action` is tappable                                    |
| `table`                             | `columns[{ key, label, align }]` (1–20; `align` `leading` / `center` / `trailing`), `rows[{ key: value }]` (at most 200), `caption`                                                           |
| `map`                               | `latitude`, `longitude`, `name`, `span` (visible area in meters), `height`                                                                                                                    |
| `file`                              | `url` (https), `name`, `mime`: a tap previews it (PDF, Office, images)                                                                                                                        |
| `video`                             | `url` (https), `poster`; no autoplay                                                                                                                                                          |
| `callout`                           | `style` `info` / `success` / `warning` / `error`, `title`, `text`                                                                                                                             |
| `badges`                            | `items[{ text, tint, icon }]`, at least 1                                                                                                                                                     |
| `buttons`                           | `items`: 1–6 actions in a row inside the content                                                                                                                                              |
| `kpi`, `stats`, `chart`, `progress` | `data`: the same `data` as the [dashboard widget](dashboard-widgets-guide.md) of that kind                                                                                                    |
| `fields`                            | `fields[]`: form fields inside the content (all `fields` blocks of one screen together at most 60); their values come back with an action that has `submit: true`                             |
| `card`                              | `title`, `blocks` (at least 1): a grouped container                                                                                                                                           |
| `row`                               | `blocks`: two or three blocks side by side                                                                                                                                                    |
| `divider`, `spacer`                 | `spacer` has a `height`                                                                                                                                                                       |

Blocks can be nested up to **3 levels**, counting the top level as 1:
`card > card > text` is fine, `card > card > card > text` is `tooLarge`. URLs on **your web app's own
backend** (`image`, `file`) are loaded with the Entra token of the app; images
on other hosts load without credentials.

Example: key figures, a table and a small chart in one card:

```ts
await showContent({
  title: 'Week 41',
  size: 'large',
  blocks: [
    {
      type: 'card',
      title: 'This week',
      blocks: [
        {
          type: 'row',
          blocks: [
            { type: 'kpi', data: { value: 14, caption: 'visits' } },
            { type: 'kpi', data: { value: "CHF 12'400", caption: 'revenue' } },
          ],
        },
        {
          type: 'chart',
          data: {
            type: 'line',
            series: [
              {
                points: [
                  { x: 'Mon', y: 3 },
                  { x: 'Tue', y: 5 },
                ],
              },
            ],
          },
        },
      ],
    },
    {
      type: 'table',
      columns: [
        { key: 'no', label: 'No.' },
        { key: 'amount', label: 'Amount', align: 'trailing' },
      ],
      rows: [
        { no: 'A-1001', amount: 240 },
        { no: 'A-1002', amount: "CHF 1'200" },
      ],
    },
    { type: 'callout', style: 'warning', text: 'Credit limit almost reached.' },
  ],
})
```

### Actions

Actions are the footer `actions`, the items of a `buttons` block and the
`action` of a `list` row:

| Field         | Meaning                                                                                                        |
| ------------- | -------------------------------------------------------------------------------------------------------------- |
| `id`, `label` | Required. `id` comes back as `action` in the result.                                                           |
| `style`       | `primary` / `secondary` / `destructive`                                                                        |
| `icon`        | SF Symbol                                                                                                      |
| `confirm`     | Confirmation prompt before running                                                                             |
| `biometric`   | Face ID first. UX only, **not** proof for your backend                                                         |
| `submit`      | `true`: validate the `fields` blocks first and return their `values` in the result                             |
| `wait`        | `true`: round trip, the surface stays open until the page answers ([below](#round-trip-onsubmit-and-onaction)) |
| `then`        | Steps that run in the app, in order, before the call resolves                                                  |

Tapping an action ends the surface and resolves the promise with its `id`,
unless it has `wait`. The user dismissing the sheet resolves with
`action: 'dismiss'` (content) or `cancelled` (form).

`then` steps:

| Step                                        | Does                                                                                                                                                               |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `{ openPath: '/orders/4711' }`              | Opens this path in your web app                                                                                                                                    |
| `{ openUrl: 'https://…' }`                  | Opens the URL outside the app. Schemes `https`, `tel`, `mailto` only                                                                                               |
| `{ copy: 'text' }`                          | Copies to the clipboard                                                                                                                                            |
| `{ share: { text?, url? } }`                | Native share sheet                                                                                                                                                 |
| `{ close: true }`                           | Closes the surface                                                                                                                                                 |
| `{ device: { action, … } }`                 | A [device action](device-actions-guide.md): `navigate`, `callPhone`, `saveContact` (needs `deviceApps`), `addReminder` (needs `deviceApps`), with the same payload |
| `{ showForm: def }`, `{ showContent: def }` | A chained flow, see [below](#chained-flows)                                                                                                                        |

### The result

```ts
type NativeContentResult =
  | {
      ok: true
      id: string
      action: string // the tapped action's id, or "dismiss"
      values?: object // the fields blocks, when the action had submit: true
      next?: NativeSurfaceResult
      context?: object
    }
  | { ok: false; error: NativeSurfaceError; message?: string }
```

## Results and error codes

Every call resolves **once** and never throws. Failures look like
`{ ok: false, error, message? }`; `message` is for developers, in English.

| `error`         | Meaning                                                                                                              | What to do                                                |
| --------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `cancelled`     | The user dismissed the surface, or `closeSurface` / a navigation closed it                                           | Accept it, do not ask again                               |
| `invalid`       | The definition does not parse. `message` names the field path, e.g. `pages[1].fields[3].type`                        | Fix the definition                                        |
| `tooLarge`      | A [limit](#limits) was exceeded. Nothing is cut silently                                                             | Shrink the definition                                     |
| `busy`          | A surface of your web app is already open (one at a time)                                                            | Wait for it, or `closeSurface` first                      |
| `capability`    | The capability is not enabled for your web app (or a camera field without `camera`)                                  | Fall back to your web UI; ask the app team                |
| `forbidden`     | Not the main frame on your web app's own origin                                                                      | Do not open it from an iframe                             |
| `unavailable`   | Nothing to present on right now (app in the background), the camera is not available, or you are **outside the app** | Fall back to your web UI                                  |
| `unknownAction` | The app is too old to know the call                                                                                  | **Treat it like `unavailable`**: fall back to your web UI |
| `failed`        | Something else went wrong                                                                                            | Show an error, let the user try again                     |

`isNativeSurfaceUnsupported(result)` is `true` for `unavailable`,
`unknownAction` and `capability`: the cases where the page should show its own
UI. It is `false` for `cancelled`, `busy`, `invalid`, `tooLarge` and `failed`:
those are answers, not a missing feature.

## Round trip: `onSubmit` and `onAction`

Without a round trip the form closes when the user submits, and you send the
values to your backend afterwards. Then a rejected value cannot be corrected in
the form: the user has to start again. With a round trip the surface stays open
with a spinner until **your page answers**:

```
user taps "Create customer"
  app → page    window.onNativeSurfaceAction({ id, action: 'submit', values })
  page → backend  fetch('/api/customers', …)                    (the token is attached)
  page → app    BMSNative.call('surfaceResult', { id, ok, fieldErrors?, message?, then? })
ok: true  → the surface closes (running `then`), showForm resolves with the values
ok: false → the surface stays open, the fields are marked, the user corrects
```

The package hides this. Give `showForm` an `onSubmit` (and `showContent` an
`onAction`) and answer by **returning or throwing**:

```ts
const result = await showForm(customerForm, {
  onSubmit: async (values, event) => {
    const res = await fetch('/api/customers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    })
    if (res.status === 422) {
      const { fieldErrors } = await res.json() // { email: 'Already registered' }
      return { fieldErrors } // the form stays open, the field is marked
    }
    if (!res.ok) throw new Error('The customer could not be saved.') // a banner, form stays open
    // returning nothing: success, the form closes
  },
})
```

| The handler …                                | The app gets                                                                                                                                                          |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| returns nothing                              | `ok: true`: the surface closes                                                                                                                                        |
| returns `{ then: […] }` and/or `{ message }` | `ok: true` with those: runs `then` (for example a "created" card), then closes                                                                                        |
| returns `{ fieldErrors: { field: 'text' } }` | `ok: false`: marks the fields and jumps to the first page that has an error                                                                                           |
| returns `{ ok: false, message }`             | `ok: false`: stays open with the message                                                                                                                              |
| throws an `Error`                            | `ok: false` with `message` set to the error's message — **shown to the user**, so throw readable messages. An error that carries `fieldErrors` marks those fields too |

`onSubmit(values, event)` gets the submitted `values` and the event
`{ id, action, values?, labels?, context? }` (`labels` are the shown texts of
`search` and `select` fields, as in the result); `onAction(event)` for content gets
`event.action` (the tapped action's `id`) and `event.values` (the `fields`
blocks, if the action had `submit: true`).

What the helper does for you:

- **`showForm`:** sets `submit.wait: true`, and an `id` if you gave none (the
  callback has to find the surface before the promise resolves). Your
  definition is not modified.
- **`showContent`:** sets `wait: true` on every action that has neither `wait`
  nor `then` itself. Give an action `wait: false` to keep it a plain tap.
- Registers the handler in one registry per loaded copy of the package, behind
  the single global `window.onNativeSurfaceAction`. **Do not assign that global
  yourself**: use `on('surfaceAction', …)` if you need the raw event. Several
  copies or versions of the package on one page work side by side; each answers
  only its own surfaces.
- Removes the handler when the promise settles.
- Drops the late answer of a handler when the surface is gone, or when the user
  triggered the action again in the meantime.
- Opening a second surface with the same `id` while one is still pending
  answers `busy` right away, without asking the app, so it cannot take over the
  handler of the open one.

**Answer within 60 seconds.** After that the app shows "No response, try
again" and re-enables the buttons. If `window.onNativeSurfaceAction` is not
defined at all, the promise resolves `unavailable` instead of leaving the
user stuck.

The low-level pieces are exported for special cases: `surfaceResult(payload)`,
`on('surfaceAction', event => …)` and `onSurfaceAction(id, handler)`. Typical
reason: a chained surface with a round trip of its own (see below).

## Chained flows

A `then` step can replace the surface with the next one, in the same sheet:

```ts
await showContent({
  id: 'customer-123',
  title: 'Miller Ltd',
  blocks: [{ type: 'text', markdown: 'Customer **123**' }],
  actions: [
    {
      id: 'reject',
      label: 'Reject',
      style: 'destructive',
      then: [
        {
          showForm: {
            id: 'reject-reason',
            title: 'Why?',
            size: 'fit',
            fields: [{ id: 'reason', type: 'textarea', label: 'Reason', required: true }],
          },
        },
      ],
    },
  ],
})
// { ok: true, id: 'customer-123', action: 'reject',
//   next: { ok: true, id: 'reject-reason', action: 'submit', values: { reason: '…' } } }
```

The original promise resolves when the **whole flow** has ended; the last
result is in `next` (nested, if several surfaces followed each other). A flow
has at most **5 screens in total**: the first one and 4 chained ones.

The page can also chain from its own answer: `onSubmit` returns
`{ then: [{ showContent: createdCard }] }`.

### A round trip in a chained surface

A chained surface with a round trip of its own (`submit.wait` or an action with
`wait`) calls the page with **its** `id`. The app generates an id if the
definition has none, and then the page cannot know it: **a chained definition
that wants a round trip needs an explicit `id`**, and it has to switch the round
trip on itself (`submit: { wait: true }`; the helper only rewrites the root
definition). Register the handler with `onSurfaceAction`, which answers like
`onSubmit` / `onAction` (return, `{ fieldErrors }`, throw):

```ts
const off = onSurfaceAction('reject-reason', async ({ values }) => {
  await api.reject(order.id, values?.reason) // a thrown error keeps the form open
})
try {
  await showContent({
    id: 'order',
    blocks: [{ type: 'text', markdown: `Order **${order.number}**` }],
    actions: [
      {
        id: 'reject',
        label: 'Reject',
        then: [
          {
            showForm: {
              id: 'reject-reason', // explicit
              submit: { wait: true }, // switched on by you
              fields: [{ id: 'reason', type: 'textarea', required: true }],
            },
          },
        ],
      },
    ],
  })
} finally {
  off() // the handler stays until you remove it
}
```

A later registration for the same `id` replaces the earlier one. Outside the
app nothing is registered.

## Fallback: browsers and old app versions

The same page also runs in a normal browser, and in app versions that do not
know the feature. **Keep your web UI** and use the native surface where it is
there:

```ts
async function createCustomer() {
  if (canShowNativeForms()) {
    const res = await showForm(customerForm, { onSubmit: saveCustomer })
    // Done, or an answer such as `cancelled` / `busy`: nothing more to do.
    if (res.ok || !isNativeSurfaceUnsupported(res)) return
  }
  openWebCustomerForm() // browser, old app, no capability
}
```

- `canShowNativeForms()` / `canShowNativeContent()` check `window.BMSNative`
  and its `capabilities`. They are `false` outside the app, in an app build
  that predates the feature, and without the capability.
- Outside the app the calls answer `{ ok: false, error: 'unavailable' }`. They
  never throw.
- An old app that does know `BMSNative` but not the call answers
  `unknownAction`: treat it like `unavailable`. `isNativeSurfaceUnsupported`
  does.
- **Never rely on a field type or block type being known by an older app.** An
  unknown field `type` is shown as a text field; an unknown block `type` is not
  shown. If the surface is business-critical, keep the web UI as the
  fallback, and put the new types in only where you can live with that.

## Media fields and the native upload

`photo`, `scan` and `signature` give files, which never pass through the page.
The **app uploads them natively** to your backend's document router and the
page only receives a small reference per file:

```ts
type NativeFileRef = { name: string; mime: string; size: number; ref: string }
```

1. When the user picks, scans or draws, the app downscales (JPEG quality 0.8,
   `maxDimension`) and gives each file a client-generated `upload_id` (a
   UUID). Nothing is sent yet, so a cancelled form leaves nothing on the server.
2. On submit (after validation, **before** the round trip or the result) the
   app uploads every file that is not uploaded yet, with your web app's token
   and a progress indicator in the surface.
3. The files keep their state while the form is open: after a field error from
   the round trip, the user corrects and submits again, and only the files
   that are still missing are uploaded.
4. A failed upload (no network, 4xx/5xx, 120 s timeout per file) stays in the
   form with "Upload failed" and a retry. The offline queue is deliberately
   not used: a form without a page waiting would leave orphans.
5. The page receives the references in `values`, and sends them to **its own
   backend** with its normal request, which resolves them.

Limits: each file at most 25 MB after downscaling, all media of one form at most
100 MB. A web app without a reachable document router, or without `camera` for
the camera-based types, cannot use media fields: the call answers `capability`
or `invalid` and names the problem in `message`.

### The document router

The app uploads to the web app's `documentUploadPath` (default `api/documents`),
the same router that receives `scanDocument`:

```http
POST /api/documents
Content-Type: multipart/form-data

device_id, user_email, kind="form", upload_id, form_id, field_id, context, file
```

| Field                             | Meaning                                                                                 |
| --------------------------------- | --------------------------------------------------------------------------------------- |
| `device_id`, `user_email`, `file` | As for scans (`user_email` is client input; take the user from your `auth_dependency`)  |
| `kind`                            | `"form"` for these uploads (`"scan"` for `scanDocument`, which keeps working unchanged) |
| `upload_id`                       | A UUID the app generated for this file. **The same one again** after a failed attempt   |
| `form_id`                         | The `id` of the form definition                                                         |
| `field_id`                        | The `id` of the field (`photo`, `scan`, `signature`)                                    |
| `context`                         | The `context` object of the definition as JSON text (optional)                          |

Any 2xx is success. The response may carry an id: `{ "ok": true, "id": "doc-17" }`.
The `ref` that the page receives is that `id`, otherwise the `upload_id`:

| Your router answers              | `NativeFileRef.ref`                                         |
| -------------------------------- | ----------------------------------------------------------- |
| `{ "ok": true, "id": "doc-17" }` | `"doc-17"`                                                  |
| `{ "ok": true }`                 | the `upload_id`; your storage has to find the file under it |

With `bmsdna-app-native` the callback of `create_document_router` returns the
reference (a `str`, an `int`, or a dict with an `"id"`); returning nothing is
the second case. `doc.metadata` carries `upload_id`, `form_id`, `field_id` and
the parsed `context`. Backends that ignore unknown multipart fields keep
working.

```python
from bmsdna.app_native import ReceivedDocument, WidgetRequestContext, create_document_router


async def on_document_received(doc: ReceivedDocument, context: WidgetRequestContext) -> str | None:
    if doc.metadata.kind != "form":
        await store_scan(doc, context)  # scans: unchanged, nothing to return
        return None
    owner = context.user.oid  # from your auth_dependency, never from user_email
    # Idempotent per upload_id: the app repeats an upload after a failed attempt.
    return await uploads.put(owner=owner, upload_id=doc.metadata.upload_id, doc=doc)
```

Three things to take care of:

- **Idempotent per `upload_id`.** The app retries; a second upload with the
  same `upload_id` must not create a second file. The simplest way: use the
  `upload_id` as the key of your storage (blob name, or a unique `(owner,
upload_id)` constraint with `ON CONFLICT DO NOTHING`).
- **Keep the file addressable by the reference** until the page's own request
  names it. Check the **owner** when resolving: the reference comes from the
  page and is client input, so user A must not be able to attach the upload
  of user B by guessing it.
- **Delete unreferenced uploads after a while** (a TTL, for example 24 hours,
  from a scheduled job). A user who fills in the photo field and then drops
  the form leaves a file that no request will ever name.

### Resolving a reference in the page's POST handler

`NativeFileRef` is a Pydantic model for the body of your own endpoint, and
`resolve_file_refs` turns the references back into what you stored:

```python
from bmsdna.app_native import NativeFileRef, resolve_file_refs
from pydantic import BaseModel


class NewCustomer(BaseModel):
    name: str
    email: str
    card: list[NativeFileRef] = []  # the photo field `card`


@app.post("/api/customers")
async def create_customer(body: NewCustomer, user: EntraUser = Depends(auth)):
    if await email_taken(body.email):
        return JSONResponse(
            status_code=422, content={"fieldErrors": {"email": "Already registered"}}
        )
    # One entry per reference, in order. 422 naming the unknown ones if any is
    # missing (expired, or not this user's): the page asks the user to add it again.
    cards = await resolve_file_refs(body.card, lambda ref: uploads.get(owner=user.oid, ref=ref))
    customer = await customers.create(body, files=cards)
    await uploads.discard(owner=user.oid, refs=[c.ref for c in body.card])  # now stored for good
    return {"id": customer.id}
```

A small in-memory store with the three operations that matter (`put` idempotent,
`get` with owner check, `purge` for the TTL) is in
[`example/main.py`](../python/app-native/example/main.py); in a real backend this is
a table and blob storage.

## Option lookup (`search` and remote `select`)

Fields of type `search`, and `select` with `remote: true`, fetch their options
from your backend, with the same request and response as for
[widget forms](dashboard-widgets-guide.md#remote-fields-search-and-selection-from-your-backend)
to `widgetOptionsPath` (default `api/widget-options`). For a native form the
request carries `form_id` **instead of** `widget_id`, plus the `context` of
your definition:

```http
POST /api/widget-options
{"device_id": "…", "form_id": "new-customer", "field_id": "owner",
 "query": "mus", "values": {"type": "b2b"}, "context": {"source": "customer-list"},
 "user_email": "…"}
```

Exactly one of `widget_id` and `form_id` is set. `values` holds everything
entered so far, also on earlier pages. `context` is whatever the page put into
the definition, unchanged: use it for "which customer was this form opened
for". It is client input like the rest: check permissions with your
`auth_dependency`.

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
    if req.form_id == "new-customer" and req.field_id == "owner":
        # req.context, here: {"source": "customer-list"}
        users = await find_users(req.query, requested_by=context.user)
        return [ActionOption(value=u.id, label=u.name, subtitle=u.team) for u in users]
    if req.widget_id == "new-visit":  # an existing widget keeps working
        ...
    return []


app.include_router(
    create_widget_options_router(on_options_requested=on_options, auth_dependency=require_user),
    prefix="/api",
)
```

Callbacks written before native forms existed keep working: they read
`req.widget_id`, which is `None` for a native form, so they answer `[]`.

The app remembers the last results a user chose per form `id` (cleared on
sign-out), so give a form a stable `id`.

## Serving a definition from your backend

Models for both definitions exist in Python (`NativeForm`, `NativeContent`,
same shape as the TypeScript types), so a backend can serve a definition from
an endpoint and the page passes it to the app **unchanged**. The models
validate the format and the [limits](#limits), so a typo shows up in the
backend instead of as `invalid` on the device:

```python
from bmsdna.app_native import ActionField, ActionOption, NativeForm, NativeFormSubmit


@app.get(
    "/api/forms/new-customer",
    response_model=NativeForm,
    response_model_by_alias=True,  # camelCase, as the app expects it
    response_model_exclude_none=True,
)
async def new_customer_form(user: EntraUser = Depends(auth)) -> NativeForm:
    return NativeForm(
        id="new-customer",
        title="New customer",
        fields=[
            ActionField(id="name", label="Company name", required=True, max_length=80),
            ActionField(id="email", type="email", label="Email", required=True),
            ActionField(
                id="segment",
                type="segmented",
                label="Segment",
                options=[
                    ActionOption(value="b2b", label="B2B"),
                    ActionOption(value="b2c", label="B2C"),
                ],
            ),
            ActionField(id="card", type="photo", label="Business card", max=1),
        ],
        submit=NativeFormSubmit(label="Create customer"),
    )
```

```ts
const def = await fetch('/api/forms/new-customer').then((r) => r.json())
await showForm(def, { onSubmit: saveCustomer })
```

Use `dump_native_form(form)` / `dump_native_content(content)` where you need a
plain dict. A server-defined form lets you change fields without a release of
the web app, but keep the old app versions in mind: the definition may use
types an older app shows differently.

## Limits

The app enforces them; a call beyond a limit answers `tooLarge` or `invalid`,
nothing is cut silently. The Python models (`NativeForm`, `NativeContent`)
check them as well, and in **development builds** the npm package warns in the
console before the call (`formLimitWarnings(def)` and
`contentLimitWarnings(def)` return the same messages, and
`NATIVE_SURFACE_LIMITS` holds the numbers):

| What                                                    | Limit                          |
| ------------------------------------------------------- | ------------------------------ |
| The whole definition                                    | 256 KB as JSON                 |
| Form pages                                              | 10                             |
| Form fields (all pages; a `repeat` group counts as one) | 60                             |
| Inline `options` of one field                           | 200 (use `search` or `remote`) |
| Rows of a `repeat` group                                | 50                             |
| Content blocks (nested ones included)                   | 100                            |
| Levels of nested blocks (top level = 1)                 | 3                              |
| Footer actions                                          | 4                              |
| Buttons in one `buttons` block                          | 6                              |
| Table columns / rows                                    | 20 / 200                       |
| Fields in all `fields` blocks of one screen             | 60                             |
| Pages of a `scan` field                                 | 20                             |
| Inline image (`data:`)                                  | 1 MB each, 4 MB in total       |
| Chained surfaces after the first one                    | 4 (5 screens in a flow)        |
| One uploaded media file (after downscaling)             | 25 MB                          |
| All media of one form                                   | 100 MB                         |
| Time to answer a round trip                             | 60 seconds                     |

The Python models go further and reject what the app would answer `invalid`
for, so a backend catches it before the device does:

- `facts`, `list`, `badges` and `buttons` have at least one item; a `card` at
  least one block; a `row` two or three blocks; a content definition at least
  one block.
- A `select` has `options`, or `remote: true`, in a native form.
- A `photo` has `max_dimension` 256–4096, a `scan` `max` 1–20.
- A `repeat` group has no `visible_if` inside.
- An image `url`, `file`/`video` URL and list `image` is `https`, and
  `open_url` is `https`, `tel` or `mailto`; `tint` is `#rrggbb`.

The npm package's development warnings cover the **limits** above (and the
ranges of `photo.maxDimension` and `scan.max`), not these structural rules: the
app tells you with `invalid` and a field path.

Warnings are logged by `showForm` and `showContent` unless `NODE_ENV` is
`production` (or Vite's `import.meta.env.PROD` is set). Pass
`{ validate: true | false }` to decide yourself.

## Security and privacy

A native form looks more trustworthy than a web page, so it must not be usable
to imitate the app or the system:

- **Own origin only.** Only the main frame on your web app's own origin can open
  a surface; an iframe or a foreign page gets `forbidden`.
- **The attribution is fixed.** Every surface shows your web app's name and
  icon. Titles are your text; the chrome is the app's.
- **No password or secret fields.** There is no such field type; forms and
  content are not for signing in.
- **No HTML, no script.** Content is only the block vocabulary above. Links
  only through explicit actions and only the schemes `https`, `tel` and
  `mailto`; images `https` or `data:image/…` (the `image` of a list row: `https` only);
  videos and files `https`.
- **The token goes only to your own backend:** option lookups, uploads, and
  images and files on your own host. Never to another host.
- **The app stores nothing of the entered values.** It remembers recently
  chosen search results per form `id`, cleared on sign-out. Photos, scans and
  signatures live in memory (or a temporary file that is deleted when the
  surface closes) until they are uploaded to your own document router.
- **One surface at a time** per web app (`busy`). It is closed on page
  navigation, on sign-out and when the app locks, and never presented while the
  app is locked.
- **Face ID is UX only.** `submit.biometric` and `action.biometric` are no
  proof for your backend: check permissions there.
- **Everything in `values`, `context`, `form_id` and a file reference is client
  input.** Authenticate with the token (`auth_dependency`) and check that the
  user may do what the request says.

## Testing

Without the app, set up `window.BMSNative` with `vi.fn()` (or a fake that
scripts results) and the package works as it does in the app:

```ts
window.BMSNative = {
  capabilities: ['nativeForms'],
  postMessage: vi.fn(),
  call: vi.fn(async (action) =>
    action === 'showForm'
      ? {
          ok: true,
          id: 'new-customer',
          action: 'submit',
          values: { name: 'Miller Ltd' },
          labels: {},
        }
      : { ok: true }
  ),
}
```

In the browser tests of this repository ([`e2e/`](../e2e/README.md)) the fake
bridge also plays the round trip: it calls `window.onNativeSurfaceAction`,
takes the page's `surfaceResult` and uploads media to the real document
router.

## Checklist

- Keep the **web UI** as the fallback (`canShowNativeForms()`,
  `isNativeSurfaceUnsupported()`): browsers, old app versions and web apps
  without the capability.
- Treat `unknownAction` like `unavailable`.
- Never rely on a field or block type being known by an older app.
- Use the round trip (`onSubmit`) for anything the backend can reject, so the
  user can correct instead of starting over.
- Make the document router idempotent per `upload_id`, check the owner when
  resolving a reference, and delete unreferenced uploads after a while.
- Give a form a stable `id` (recent search results, `form_id` in lookups).
- The camera types (`photo` with the camera, `scan`, `barcode`) need `camera`
  as well; `saveContact` and `addReminder` in `then` need `deviceApps`.
