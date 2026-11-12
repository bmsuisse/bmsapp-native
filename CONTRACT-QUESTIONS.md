# Contract questions: BMS native bridge 2026-11

Points where the contract is silent or ambiguous. Nothing here changes the contract:
the packages implement it as written and make the narrowest choice listed under
"Package does". The iOS team should confirm each point or say what the app does
instead, so both sides match.

## C1 / C2 / C3: a document whose upload failed over HTTP

- **Problem:** `upload.status` is "the final HTTP status", and `error: "failed"` marks a
  document that failed. It is not said whether a final status of 400 or more makes the
  document `failed`, and whether `upload` is still present then (a 5xx after the
  retry, a 413, a 401).
- **Package does:** passes the document through as the app sends it. The fake app of
  `e2e/` sends `error: "failed"` **together with** `upload: { status, body }` for a
  final status >= 400, and `error: "failed"` without `upload` after a network error.
- **Proposed fix:** state it: a final status >= 400 or no response means `error:
"failed"`; `upload` is present when there was an HTTP response (`body` verbatim, or
  `null`) and missing otherwise.

## C3: `accept` with wildcards

- **Problem:** `accept` takes "MIME types or extensions such as `.eml`". Wildcard types
  like `image/*` are not mentioned.
- **Package does:** passes every string through unchanged. In the browser fallback they
  go to the `accept` attribute of the `<input>`, where `image/*` works.
- **Proposed fix:** say that `type/*` is allowed, and what the app does with an entry it
  does not understand (ignore it, or answer `invalid`).

## C4: `consumeReceivedDocuments` without the capability

- **Problem:** targets are web apps with the capability `receiveDocuments`, and
  `consumeReceivedDocuments` has no stated error. For a web app without the capability
  it could answer `capability`, or `{ ok: true, documents: [] }`.
- **Package does:** calls it only if the app lists the feature `receiveDocuments`, and
  passes the answer on (`capability` reaches the page as `capability`). The fake app
  answers `{ ok: true, documents: [] }`.
- **Proposed fix:** answer `capability`, like every other action that needs one.

## C5: `dictate` option types

- **Problem:** `maxSeconds` is "1-120" without saying whether a fraction such as `30.5`
  is allowed, and `locale` is "BCP-47" without saying what the app does with a tag it
  cannot recognize.
- **Package does:** accepts any finite number from 1 to 120 for `maxSeconds` and any
  non-empty string for `locale`; everything else is `invalid`. A locale the device
  cannot recognize is left to the app (`unavailable` is the natural answer).
- **Proposed fix:** `maxSeconds` is a whole number (the package then rejects fractions
  too), and an unsupported locale answers `unavailable`.

## C7: several handlers and a late `backResult`

- **Problem:** the contract has one `window.onNativeBackRequested`. Two cases are not
  described: (1) a `backResult` that arrives after the 800 ms (what does the app
  answer to it?), (2) `backResult` with no request pending.
- **Package does:** answers within about 700 ms, so (1) does not happen in practice; it
  never sends (2). With several `onBackRequested` handlers the package asks the newest
  first inside the one global, so the app sees one page-level handler.
- **Proposed fix:** the app ignores both and answers `{ ok: true }`.

## C9: relative URLs in `previewFile`

- **Problem:** `url` may be "absolute or relative". A relative URL such as `file.pdf`
  resolves differently against the page URL than against the origin.
- **Package does:** resolves `url` against the page (`new URL(url, location.href)`),
  checks the origin, and **sends the absolute URL** to the app. The app still has to
  accept relative URLs for pages that call `BMSNative.call('previewFile')` directly.
- **Proposed fix:** the app resolves relative URLs against the URL of the page that
  sent the message.

## C10: `refresh` and `interactive` together with `resource`

- **Problem:** (1) `refresh` is described for the token without `resource`; whether it
  forces a new token for the resource as well is not said. (2) `interactive` is
  described only with `resource`.
- **Package does:** sends `refresh: true` together with `resource` (the app is
  expected to force a new token of that resource), and **drops `interactive` when there
  is no `resource`**, so the call without `resource` stays exactly as it was.
- **Proposed fix:** `refresh` applies to the requested resource too; `interactive`
  without `resource` is ignored.

## C0: capability check of `scanDocument` and `pickFiles` in the package

- **Problem:** the app checks `camera` (and answers `capability`); the package could
  check `BMSNative.capabilities` first, but the existing `scan*` functions do not.
- **Package does:** does **not** check capabilities, so the app stays the one place that
  decides (consistent with `scanText` and friends). `can('camera')` is there for hiding
  buttons.
- **Proposed fix:** none needed, listed so the app side knows it always gets the call.

# Contract questions: addendum 2026-11b

Same rules as above: nothing here changes the contract; "Package does" is the narrowest
choice the packages made. Section numbers are those of the addendum.

## C13: the toast key `action` collides with the key `action` of a message

- **Problem:** `BMSNative.call("toast", { message, action: { id, label } })` has a payload
  key named `action`. `BMSNative.call(action, payload)` is documented as sending "the same
  message as `postMessage`", and a flat message `{ action: "toast", …payload }` has its
  own `action` (the name of the call). One of the two wins, and the toast's button is lost
  or the call becomes `action: { … }`.
- **Package does:** calls `BMSNative.call("toast", { message, …, action: { id, label } })`
  with the name and the payload as separate arguments and assumes the app keeps them apart
  (the test bridge does). The fire-and-forget `post("toast", …)` is unchanged and does not
  carry an `action`. **No rename.**
- **Proposed fix:** confirm that `call` hands the payload over separately from the name, or
  rename the payload key (for example `toastAction`) in both teams' text at the same time.

## C11: lazy children outside `showMenu`

- **Problem:** the lazy mechanism is described with a `menuId` (`onNativeMenuExpand({ menuId,
itemId, requestId })`), which only `showMenu` has. `actionButtons[].menu` and
  `title.menu` are also `MenuSection[]`, and may contain `children: "lazy"`.
- **Package does:** `showMenu` supports it (`loadChildren`); for the menus of the navigation
  bar it warns in development builds and sends the payload unchanged.
- **Proposed fix:** lazy children are only valid in `showMenu`; elsewhere the app answers
  `invalid` or shows a disabled item.

## C11: `lazyFailedLabel`, empty menus, choosing a parent item

- **Problem:** (1) the text names "the item's `lazyFailedLabel`", but `MenuItem` does not
  list the field. (2) Empty `sections`, or a section without `items`, are not described.
  (3) What a tap on an item with `children` returns (it should open the submenu, not resolve).
- **Package does:** (1) has `lazyFailedLabel?: string` on `NativeMenuItem` and in the Python
  model; (2) accepts them and leaves the decision to the app; (3) nothing, it passes the
  app's `id`.
- **Proposed fix:** add `lazyFailedLabel?` to `MenuItem`; an empty menu answers `invalid`;
  items with `children` are never a result.

## C11: `showMenu` without an `id` when the page uses lazy children

- **Problem:** `menuId` in `onNativeMenuExpand` is the menu's `id`, which is optional. A
  page that does not give one cannot know which menu is meant.
- **Package does:** generates an `id` (a UUID) and sends it whenever `loadChildren` is given.
- **Proposed fix:** none needed; the app echoes the `id` it was given, or generates one when
  there is none.

## C12: duplicate action ids, `text` for an empty line

- **Problem:** two actions with the same `id`, and the `text` of an input line that the user
  left empty (`""` or missing) are not described.
- **Package does:** does not check ids of actions for duplicates; passes `text` through, and
  gives `text` to the page only when it is a string.
- **Proposed fix:** `invalid` for duplicate action ids; `text` is always present with a
  `textField`, `""` if empty.

## C14: which fields can be `live`, and the meaning of `updateSurface` keys

- **Problem:** (1) "any input field" is not enumerated: `photo`, `scan`, `signature`,
  `barcode`, `repeat` deliver files or rows, and the `value` of the event is not described for
  them. (2) For `updateSurface` it is not said whether `values` merges or replaces, whether
  `fields` replaces all fields of a single-page form, whether a block `id` must be unique
  within a surface, and what happens to a surface in the middle of a round trip (`wait`).
  (3) The `search` field `source: "page"` answers within 10 s: what the user sees without an
  answer or with a failure of the page. (4) Whether the 100 KB of an `image` are encoded or
  decoded bytes.
- **Package does:** (1) with `onChange` it sets `live: true` on every field except `info`;
  (2) sends the keys as given; (3) does not answer when the handler fails, the app times
  out after 10 s; (4) counts the **decoded** bytes of a `data:` URI. It cuts an answer of more
  than 50 options to 50 and leaves out an `image` that is not `https` or a small `data:`
  URI (development builds say so).
- **Proposed fix:** `live` for the scalar types only (`text`, `number`, `select`, `toggle`,
  `date`, `textarea`, `email`, `phone`, `url`, `multiselect`, `segmented`, `stepper`,
  `time`, `datetime`, `search`, `barcode` as text); `values` merges; `fields` replaces;
  ids unique within the surface; an update during a round trip is applied; after 10 s the
  app shows an empty result with a retry; the 100 KB are decoded bytes. An explicit error
  answer for a search (for example `surfaceSearchResult` with `error`) would help the app
  show a message.

## C15: scope change, `scope` without scopes, `value`

- **Problem:** (1) Does a change of the scope call `onNativeSearch`, with which `source` and
  `submitted`? (2) `scope` of the event without `scopes`: missing, `null` or `""`? (3) Does
  `value` in a later `setChrome` overwrite what the user typed?
- **Package does:** types `scope` as `string | null | undefined`; nothing else.
- **Proposed fix:** (1) a scope change calls `onNativeSearch` with the current query,
  `submitted: false` and `source: "typing"`; (2) `null`; (3) `value` is applied only when it
  differs from the last `value` the page sent.

## C16: toolbar and C22: key commands, the details

- **Problem:** C22: how the app treats a command that collides with a system shortcut or
  with Cmd+W of C8, two commands with the same input and modifiers, upper-case letters.
  C16: whether the toolbar needs `customChrome` only, and what a page without focus sees.
- **Package does:** checks the limits (60 commands, 6 items, one character or a named key,
  the four modifiers) and nothing else. Letters are compared by the app.
- **Proposed fix:** the app ignores a command that collides with Cmd+W or a system shortcut;
  the first of two identical commands wins; letters are case-insensitive.

## C17 / C18: types and wide-only behavior

- **Problem:** the type of `badge` and `footer` of the sidebar is not given (segments say "a
  short string"), nor how many `trailingActions` an item may have, nor whether several items
  may be `selected`. In compact width the sidebar is "ignored": the page cannot tell from
  `hasFeature('sidebar')`.
- **Package does:** `badge` and `footer` are `string`; no limit on `trailingActions`; the
  page decides with `data-bms-size-class` / `on('layoutChange')`.
- **Proposed fix:** `badge` is a short string, `footer` a string; at most 3 trailing actions;
  at most one `selected` item.

## C19: the viewer

- **Problem:** (1) a second `showDocument` while a viewer is open; (2) `showDocument`
  without `id` (the events carry an id the page cannot know); (3) `selected` that is not one
  of the `highlights`, and `selected` together with `page`; (4) a tap on overlapping
  highlights.
- **Package does:** sends the options as given (the URL as an absolute one), warns in
  development builds about (3).
- **Proposed fix:** (1) `busy`; (2) the app echoes a generated `id` in the events and the
  page gives its own; (3) `selected` wins over `page`, an unknown `selected` is ignored;
  (4) the topmost, last highlight in the list.

## C21: picker values

- **Problem:** a `value` of an `option` picker that is not among the `options`, a `min`
  above `max`, a `value` outside `min`/`max`.
- **Package does:** checks only that dates are real `YYYY-MM-DD` dates and that options are
  well formed.
- **Proposed fix:** the app ignores a `value` that is not selectable and answers `invalid`
  for `min` above `max`.
