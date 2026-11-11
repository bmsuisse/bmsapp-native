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
