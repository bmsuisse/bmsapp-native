# Documents: pick, receive, preview

This guide is for web apps that work with files on the iPhone and iPad: the user
**picks** a PDF, a mail or a photo (`pickFiles`), **shares** one from another app
into your web app (`onDocumentsReceived`), or **opens** a file of yours in the native
preview (`previewFile`). Scanning with the camera is in the
[scan guide](scan-guide.md) (`scanDocument`); it delivers the same document shape.

Package: [`@bmsuisse/app-native`](../packages/app-native), file
[`documents.ts`](../packages/app-native/src/documents.ts). Backend:
[`bmsdna-app-native`](../python/app-native), file
[`documents.py`](../python/app-native/bmsdna/app_native/documents.py).

```ts
import {
  pickFiles,
  onDocumentsReceived,
  consumeReceivedDocuments,
  previewFile,
  hasFeature,
  type NativeDocument,
} from '@bmsuisse/app-native'
```

| Function                     | Capability                 | Feature            | Browser                                   |
| ---------------------------- | -------------------------- | ------------------ | ----------------------------------------- |
| `pickFiles(options)`         | `camera` for source camera | `pickFiles`        | `<input type="file">`, mode `return` only |
| `onDocumentsReceived(fn)`    | `receiveDocuments`         | `receiveDocuments` | registers `fn`, never called              |
| `consumeReceivedDocuments()` | –                          | `receiveDocuments` | `unavailable`                             |
| `previewFile(options)`       | –                          | `previewFile`      | opens a new tab                           |

`hasFeature(name)` tells whether the app implements a feature: it reads
`window.BMSNative.features`, which older apps do not have (treated as an empty
list). A function whose feature is missing answers `unavailable` **without asking
the app**, so one fallback covers old apps, apps that answer `unknownAction`, and the
browser. No call throws.

## `NativeDocument`

Every document that `pickFiles`, `scanDocument` and shared files deliver looks like
this:

| Field      | Type                 | Meaning                                                           |
| ---------- | -------------------- | ----------------------------------------------------------------- |
| `name`     | string               | File name including the extension                                 |
| `mime`     | string               | e.g. `application/pdf`                                            |
| `size`     | number               | Bytes                                                             |
| `pages`    | number, optional     | Scans only                                                        |
| `uploadId` | string               | A UUID v4 per file. The app reuses it when it retries an upload   |
| `upload`   | object, optional     | Mode `upload` only: `{ status, body }`, see below                 |
| `data`     | string, optional     | Mode `return` only: the file content, base64                      |
| `error`    | `failed`, `tooLarge` | This document failed. Only `name` and `uploadId` are certain then |

A **batch** is `{ ok: true, documents }` with at least one entry. A document that
failed does not fail the batch: check `error` of each. `{ ok: false, error }` only
comes when nothing was produced: `cancelled`, `capability`, `invalid`, `unavailable`.
The limit is **25,000,000 bytes** per document; larger files come back as
`error: 'tooLarge'`.

```ts
const res = await pickFiles({ sources: ['files'], accept: ['application/pdf'] })
if (res.ok) {
  for (const doc of res.documents) {
    if (doc.error) showProblem(doc.name, doc.error)
    else await useFile(doc)
  }
} else if (res.error !== 'cancelled') {
  openWebFilePicker() // unavailable, capability, invalid
}
```

### Mode `upload`: the app uploads, the page gets the answer

The app sends a multipart `POST` to the web app's `documentUploadPath` with the
fields `file`, `device_id`, `user_email`, `kind`, `upload_id` (= `uploadId`) and
`context` (a JSON string, left out without one). After a network error or an HTTP
5xx it retries **once** with the same `upload_id`. The page then gets
`upload = { status, body }`:

- `status` is the final HTTP status,
- `body` is the **JSON response of your backend, verbatim**, or `null` if it was not
  JSON (error responses too, so `{"detail": …}` of a 4xx/5xx).

**It passes through the page, so it must not contain secrets** (no tokens, no signed
URLs with credentials, nothing the web app's JavaScript should not see). With the
document router of `bmsdna-app-native` the body is `{"ok": true, "id": "<what your
callback returned>"}`; return an ID of your own, not a secret.

### Mode `return`: the page gets the bytes

`data` is the file content in base64. Use it for small files that the page itself
sends on (to a form, a chat, an API). For anything large prefer `upload`: the bytes
do not pass through JavaScript then.

## `pickFiles(options)`

| Option     | Type                                  | Meaning                                                              |
| ---------- | ------------------------------------- | -------------------------------------------------------------------- |
| `sources`  | `('files' \| 'photos' \| 'camera')[]` | Required, at least one. More than one: the app shows a chooser first |
| `accept`   | `string[]`                            | MIME types or extensions such as `.eml`. Default: any                |
| `multiple` | boolean                               | Default `false`                                                      |
| `mode`     | `'upload' \| 'return'`                | Default `return`                                                     |
| `context`  | object                                | Travels with an upload. A JSON object, at most 4096 bytes serialized |
| `kind`     | string                                | Default `pick`. 1 to 32 characters of `a-z0-9_-`                     |

- Photos are delivered as **JPEG**.
- `camera` needs the `camera` capability, else the whole call answers `capability`.
  `files` and `photos` need none.
- The package checks the options **before** it asks the app: a bad `context` (not an
  object, over 4096 bytes), `kind`, `mode`, empty `sources` and so on answer
  `invalid` right away, with an English `message` for the developer. In development
  builds the package also logs a warning.

### In the browser

Without the app, `pickFiles` opens a hidden `<input type="file">` (with `accept`,
`multiple`, and `capture` for the camera only) and returns `NativeDocument`s with
base64 `data` and a fresh `uploadId` each. Call it from a click handler, browsers
refuse the dialog otherwise. Mode `upload` is `unavailable` there. A closed dialog is
`cancelled`.

## Files shared into your web app

Users can send files from other apps (Mail, Files, Photos, a browser) to the BMS app:
via the share sheet (Share Extension) or "Open in". The app takes **PDF, `.eml`
(`message/rfc822`), `.msg` (`application/vnd.ms-outlook`), PNG, JPEG, HEIC (converted
to JPEG) and plain text**.

The targets are the web apps with the capability **`receiveDocuments`** and a
`documentUploadPath`. With one target there is no picker. The app uploads each file
exactly like mode `upload` above, with `kind: "shared"` and no `context`, then opens
the web app (or brings it to the front; if it is not open, at its start URL).

### Receiving the batch

```ts
const off = onDocumentsReceived(({ documents }) => {
  for (const doc of documents) {
    if (doc.error) continue
    importOffer(doc.upload?.body?.id)
  }
})
// off() when the screen goes away
```

`onDocumentsReceived` sets `window.onNativeDocumentsReceived`, then asks once for the
batches that arrived while the page was not listening and hands them to the handler.
Call it as early as you can, **once per page** (at startup, not per component).

The rules behind it, so nothing is lost and nothing arrives twice:

- If `window.onNativeDocumentsReceived` is a function, the app calls it with
  `{ documents }` and **drops** the batch.
- Otherwise the app **queues** the batch (it survives app restarts for 24 hours). The
  action `consumeReceivedDocuments` returns all queued documents (possibly an empty
  list) and clears the queue.
- The cleanup that `onDocumentsReceived` returns removes the handler. When the
  **last** handler is gone the package removes `window.onNativeDocumentsReceived`
  too, so the app queues again instead of calling a page that is not listening.
- With several handlers every one gets each batch the app delivers; a queued batch
  goes to the handler that was registered when it was fetched.

You rarely need `consumeReceivedDocuments()` yourself. If you call it, make sure you
do something with the result: the queue is cleared.

Your backend sees the uploads with `kind="shared"`; see below.

### Dropping files (iPad)

Files dragged onto the web view from other apps (Split View, Stage Manager) arrive as
a normal HTML `drop` event with `DataTransfer.files`; that needs no package function.
See [webapp-chrome-guide.md](webapp-chrome-guide.md).

## `previewFile({ url, filename? })`

Opens a file of your web app in the native preview (Quick Look: zoom, share, save,
markup). The app downloads it with the web view's cookies, and with the bearer token
if the web app has `identity`, so protected files work.

```ts
const res = await previewFile({ url: `/api/offers/${id}/file`, filename: 'Offer 4711.pdf' })
if (!res.ok && res.error === 'failed')
  toast(`Could not load the file (HTTP ${res.status})`, 'error')
```

- `url` must be on **the web app's own origin**, absolute or relative; anything else
  answers `invalid` (the package checks first and does not ask the app). A relative
  URL is resolved against the page and sent as an absolute one.
- It resolves `{ ok: true }` once the preview is shown. An HTTP status of 400 or more
  is `{ ok: false, error: 'failed', status }`.
- In the browser it opens the URL in a new tab and resolves `{ ok: true }`.

## `showDocument`: the native viewer

For a PDF whose **places matter** (the lines of an offer, the fields an assistant read),
`previewFile` is too little. `showDocument` opens a full-screen PDFKit viewer (pinch zoom,
page thumbnails, text search) with **highlights** you draw on the pages. Feature
`documentViewer`, needs `customChrome`.

```ts
import { showDocument, updateDocument, on } from '@bmsuisse/app-native'

const off = [
  on('documentTap', ({ highlightId, page }) => highlightId && selectLine(highlightId)),
  on('documentPage', ({ page }) => rememberPage(page)),
]
const closed = showDocument({
  id: 'offer-pdf',
  url: `/api/offers/${id}/file`,
  title: 'Offer 4711',
  highlights: [
    { id: 'l1', page: 1, x: 0.1, y: 0.4, w: 0.8, h: 0.05, style: 'primary', label: 'Pallet' },
  ],
  selected: 'l1',
})
// later, while it is open:
await updateDocument({ id: 'offer-pdf', selected: 'l2', highlights: lines.map(toHighlight) })
await closed // { ok: true } once the user closes the viewer
off.forEach((stop) => stop())
```

| Option       | Meaning                                                                          |
| ------------ | -------------------------------------------------------------------------------- |
| `id`         | Echoed in the events and used by `updateDocument`. Give one                      |
| `url`        | Same origin, loaded like `previewFile` (cookies, bearer with `identity`)         |
| `title`      | Optional                                                                         |
| `page`       | 1-based page to open                                                             |
| `highlights` | At most 500: `{ id, page, x, y, w, h, style: 'primary' \| 'secondary', label? }` |
| `selected`   | The id of a highlight; the viewer scrolls to it                                  |

`x`, `y`, `w`, `h` are **fractions (0 to 1) of the page**, the origin at the top left;
`page` is 1-based. Events: `documentTap` `{ id, highlightId, page, x, y }` (`highlightId`
is `null` outside a highlight) and `documentPage` `{ id, page }`.

`updateDocument({ id, highlights?, selected?, page? })` changes the open viewer and answers
`notFound` if it is not open. `showDocument` resolves `{ ok: true }` when the viewer is
closed, `failed` with `status` for an HTTP status of 400 or more (like `previewFile`),
`invalid` for a foreign origin or a bad highlight (not asked), and `unavailable` in the
browser and in an app without the feature: show your own PDF viewer (or `previewFile`).
The URL is sent as an absolute one.

## The backend

The uploads go to the document router, the same one that receives `scanDocument` and
the media of native forms:

```python
from bmsdna.app_native import InMemoryUploadResults, create_document_router, insecure_no_auth

app.include_router(
    create_document_router(
        on_document_received=on_document,
        auth_dependency=auth,
        upload_results=InMemoryUploadResults(),  # optional, see below
    ),
    prefix="/api",
)
```

| `kind`                | From                                                 |
| --------------------- | ---------------------------------------------------- |
| `scan`                | `scanDocument` (the default kind)                    |
| `pick`                | `pickFiles` with `mode: 'upload'` (the default kind) |
| `shared`              | A file shared into the web app. No `context`         |
| `form`                | The media of a native form                           |
| your own (`a-z0-9_-`) | The `kind` option of `scanDocument` / `pickFiles`    |

The router accepts every `kind` and passes it on in `metadata.kind`; decide in your
callback what to do for which. `context` arrives as a dict in `metadata.context`: it
is client input, check it like any other.

**Retries are idempotent per `upload_id`, for every kind.** The app repeats an upload
with the same `upload_id` after a network error or an HTTP 5xx, and the first attempt
may well have succeeded (only the answer was lost). Either make your callback
idempotent per `upload_id` (store by it), or pass `upload_results`: the router then
answers a repeated `upload_id` with the answer of the first time and does not call
your callback again. Only successful answers are remembered. `InMemoryUploadResults`
is for one process; implement `UploadResultStore` on your database or Redis if you
run more than one.

**What the router answers reaches the page** as `upload.body`, see above: keep
secrets out of the callback's return value and out of error details.

### When the page relays a result to you

If the page sends a `NativeDocument` (or a list of them) to an endpoint of yours, use
the model as the type of the field. It validates the shape the contract promises
(`uploadId` a UUID v4, `mime` and `size` unless the document failed, `data` valid
base64, `size` within 25,000,000 bytes) and decodes the content:

```python
from bmsdna.app_native import NativeDocument


class NewOffer(BaseModel):
    attachments: list[NativeDocument]


@app.post("/api/offers")
async def create_offer(body: NewOffer, user: User = Depends(auth)):
    for doc in body.attachments:
        if doc.error:
            continue
        content = doc.content()  # bytes from `data`, None without `data`
```

It is client input: do not trust `name` (reduce it to a base name) or `mime`.
`NativeDocumentContext` is the type for the `context` object (at most 4096 bytes
serialized), and `DocumentKind` the type for a `kind`.

The router's own limit (`max_bytes`, default 25 MiB) is a little above the 25,000,000
bytes of the contract: the app never sends a larger document.

## App versions without the feature

| App                                          | `pickFiles`                   | `onDocumentsReceived`   | `previewFile` |
| -------------------------------------------- | ----------------------------- | ----------------------- | ------------- |
| Browser                                      | `<input>`, mode `return` only | registers, never called | new tab       |
| App without `features` / without the feature | `unavailable`                 | registers, never called | `unavailable` |
| App with the feature                         | native picker                 | batches delivered       | Quick Look    |

Keep your own web file input as the fallback for `unavailable`; it keeps working in
every app version.
