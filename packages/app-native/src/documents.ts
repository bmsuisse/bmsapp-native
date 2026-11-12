// Documents: `pickFiles`, files shared into the web app (`onDocumentsReceived`,
// `consumeReceivedDocuments`) and `previewFile`. The shared result shape
// `NativeDocument` is also what `scanDocument` (scan.ts) delivers. The backend
// side is `bmsdna.app_native.documents`. Details: docs/documents-guide.md

import { hasFeature, isNativeApp, type NativeFailure } from './bridge.js'
import { isDevelopment, warn } from './dev.js'
import {
  asFailure,
  badAnswer,
  booleanProblem,
  callFeature,
  contextProblem,
  invalid,
  isRecord,
  kindProblem,
  modeProblem,
  nonEmptyString,
  sameOriginUrl,
  unavailable,
} from './internal.js'

/** Limits of the contract. */
export const DOCUMENT_LIMITS = {
  /** Bytes per document. Beyond it a document fails with `tooLarge`. */
  bytes: 25_000_000,
  /** Bytes of `context` once serialized to JSON. */
  contextBytes: 4096,
} as const

/** What happens with the files: the app uploads them, or hands them to the page. */
export type DocumentMode = 'upload' | 'return'

/** The answer of your backend to an upload, as the app saw it. */
export type NativeDocumentUpload = {
  /** The final HTTP status (after the app's one retry). */
  status: number
  /**
   * The response of your backend as the app saw it: the parsed JSON if it was valid JSON
   * (for the document router of `bmsdna-app-native`: `{"ok": true, "id": "…"}`), otherwise
   * the raw response text as a string. It passes through the page: the backend must not put
   * secrets into it.
   */
  body: unknown
}

type NativeDocumentFields = {
  /** File name including the extension. */
  name: string
  /** A UUID v4 per file, reused when the app retries the upload. */
  uploadId: string
  /** Scans only: the number of pages. */
  pages?: number
  /** Mode `upload` only. */
  upload?: NativeDocumentUpload
  /** Mode `return` only: the file content, base64. */
  data?: string
}

/**
 * One document of a scan, a pick or a share.
 *
 * A document that failed carries `error` (`failed`, or `tooLarge` beyond
 * 25,000,000 bytes); only `name` and `uploadId` are certain then. Check
 * `error` first. An upload that ended with HTTP 400 or more is `failed` and still has
 * `upload: { status, body }`; after a network error there is no `upload` at all.
 */
export type NativeDocument =
  | (NativeDocumentFields & {
      /** e.g. `application/pdf`. */
      mime: string
      /** Bytes. */
      size: number
      error?: undefined
    })
  | (NativeDocumentFields & {
      mime?: string
      size?: number
      error: 'failed' | 'tooLarge'
    })

/**
 * A batch: at least one entry. Per-document failures are in `error` of the
 * document, `{ ok: false }` only comes when nothing was produced:
 * `cancelled`, `capability`, `invalid`, `unavailable`.
 */
export type DocumentsResult = { ok: true; documents: NativeDocument[] } | NativeFailure

// --- Parsing what the app answers ---------------------------------------------

function isDocument(value: unknown): value is NativeDocument {
  if (!isRecord(value)) return false
  if (typeof value.name !== 'string' || typeof value.uploadId !== 'string') return false
  if (value.error !== undefined) return typeof value.error === 'string'
  return typeof value.mime === 'string' && typeof value.size === 'number'
}

/** The documents of an answer, or `null` if it is not a list of documents. */
export function parseDocuments(raw: unknown, allowEmpty: boolean): NativeDocument[] | null {
  if (!Array.isArray(raw) || !raw.every(isDocument)) return null
  return raw.length === 0 && !allowEmpty ? null : raw
}

/** `{ ok: true, documents }` from an app answer, otherwise its failure. */
export function toDocumentsResult(answer: { ok: boolean }, allowEmpty = false): DocumentsResult {
  if (!answer.ok) return asFailure(answer as { ok: false })
  const documents = parseDocuments((answer as { documents?: unknown }).documents, allowEmpty)
  return documents ? { ok: true, documents } : badAnswer()
}

// --- pickFiles ----------------------------------------------------------------

export type PickSource = 'files' | 'photos' | 'camera'

const PICK_SOURCES: readonly string[] = ['files', 'photos', 'camera']

export type PickFilesOptions = {
  /**
   * Where the user can pick from; at least one. With more than one the app first
   * shows a chooser. Photos arrive as JPEG. `camera` needs the `camera`
   * capability (else `capability`), `files` and `photos` need none.
   */
  sources: readonly PickSource[]
  /** MIME types or extensions, e.g. `['application/pdf', '.eml']`. Default: any. */
  accept?: readonly string[]
  /** Default `false`. */
  multiple?: boolean
  /**
   * `return` (default): the files come back as base64 `data`. `upload`: the app
   * uploads them to `documentUploadPath` (not in the browser).
   */
  mode?: DocumentMode
  /** Sent along with an upload as `context`; a JSON object, at most 4096 bytes. */
  context?: Record<string, unknown>
  /** 1 to 32 characters of `a-z0-9_-`; default `pick`. */
  kind?: string
}

export type PickFilesResult = DocumentsResult

function pickProblem(options: unknown): string | undefined {
  if (!isRecord(options)) return 'options have to be an object with sources.'
  const { sources, accept } = options
  if (!Array.isArray(sources) || sources.length === 0) {
    return 'sources needs at least one of "files", "photos", "camera".'
  }
  if (!sources.every((s) => typeof s === 'string' && PICK_SOURCES.includes(s))) {
    return 'sources can only contain "files", "photos" and "camera".'
  }
  if (
    accept !== undefined &&
    !(Array.isArray(accept) && accept.every((a) => typeof a === 'string'))
  ) {
    return 'accept has to be a list of MIME types or extensions.'
  }
  return (
    booleanProblem('multiple', options.multiple) ??
    modeProblem(options.mode) ??
    kindProblem(options.kind) ??
    contextProblem(options.context)
  )
}

/**
 * Lets the user pick files: from the Files app, the photo library or the camera.
 *
 * - In the app (feature `pickFiles`): the native picker. The result is a batch
 *   of `NativeDocument`; mode `return` (default) delivers base64 `data`, mode
 *   `upload` uploads to the web app's `documentUploadPath` (document router of
 *   `bmsdna-app-native`) and reports the backend's answer in `upload`.
 * - In the browser: a hidden `<input type="file">` (`accept`, `multiple`,
 *   `capture` for the camera). Only mode `return`; `upload` is `unavailable`.
 *   Call it from a click handler, browsers refuse the dialog otherwise.
 * - In an app without the feature: `unavailable`.
 *
 * An invalid payload answers `invalid` without asking the app. Never throws.
 * Errors: `invalid`, `capability`, `cancelled`, `unavailable`.
 */
export async function pickFiles(options: PickFilesOptions): Promise<PickFilesResult> {
  const problem = pickProblem(options)
  if (problem) return invalid('pickFiles', problem)

  if (!isNativeApp()) {
    return options.mode === 'upload' ? unavailable() : pickInBrowser(options)
  }
  const payload: Record<string, unknown> = { sources: [...options.sources] }
  if (options.accept !== undefined) payload.accept = [...options.accept]
  if (options.multiple !== undefined) payload.multiple = options.multiple
  if (options.mode !== undefined) payload.mode = options.mode
  if (options.context != null) payload.context = options.context
  if (options.kind !== undefined) payload.kind = options.kind
  return toDocumentsResult(await callFeature('pickFiles', 'pickFiles', payload))
}

// --- Browser fallback of pickFiles ---------------------------------------------

function randomUuid(): string {
  const c = globalThis.crypto
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (typeof c?.getRandomValues === 'function') c.getRandomValues(bytes)
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error)
    reader.onload = () => {
      const url = String(reader.result)
      resolve(url.slice(url.indexOf(',') + 1))
    }
    reader.readAsDataURL(file)
  })
}

async function toDocument(file: File): Promise<NativeDocument> {
  const base = {
    name: file.name,
    uploadId: randomUuid(),
    mime: file.type || 'application/octet-stream',
    size: file.size,
  }
  if (file.size > DOCUMENT_LIMITS.bytes) return { ...base, error: 'tooLarge' }
  try {
    return { ...base, data: await readBase64(file) }
  } catch {
    return { ...base, error: 'failed' }
  }
}

function pickInBrowser(options: PickFilesOptions): Promise<PickFilesResult> {
  if (typeof document === 'undefined') return Promise.resolve(unavailable())
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.hidden = true
    input.multiple = options.multiple === true
    const withFiles = options.sources.includes('files')
    const accept = options.accept?.length ? options.accept.join(',') : withFiles ? '' : 'image/*'
    if (accept) input.accept = accept
    if (options.sources.every((s) => s === 'camera')) input.setAttribute('capture', 'environment')

    let settled = false
    const finish = (result: PickFilesResult) => {
      if (settled) return
      settled = true
      input.remove()
      resolve(result)
    }
    input.addEventListener('cancel', () => finish({ ok: false, error: 'cancelled' }))
    input.addEventListener('change', () => {
      const files = Array.from(input.files ?? [])
      if (files.length === 0) return finish({ ok: false, error: 'cancelled' })
      void Promise.all(files.map(toDocument)).then((documents) => finish({ ok: true, documents }))
    })
    try {
      ;(document.body ?? document.documentElement).appendChild(input)
      input.click()
    } catch {
      finish(unavailable())
    }
  })
}

// --- Files shared into the web app ---------------------------------------------

/** What the app delivers when files were shared into this web app. */
export type DocumentsReceivedEvent = { documents: NativeDocument[] }

export type ConsumeResult = { ok: true; documents: NativeDocument[] } | NativeFailure

/**
 * The batches the app kept while the page had no `onNativeDocumentsReceived`
 * (it keeps them for 24 hours, also across app restarts), and clears the queue.
 * Possibly an empty list. `unavailable` outside the app or in an app without the
 * feature `receiveDocuments`.
 *
 * You rarely need this: `onDocumentsReceived` does it for you.
 */
export async function consumeReceivedDocuments(): Promise<ConsumeResult> {
  const answer = await callFeature('receiveDocuments', 'consumeReceivedDocuments')
  return toDocumentsResult(answer, true)
}

type Receiver = (event: DocumentsReceivedEvent) => void | Promise<void>

const receivers = new Set<Receiver>()
let restore: (() => void) | null = null

function reportLater(error: unknown): void {
  // The handler of the page failed: do not stop the others, do not swallow it.
  setTimeout(() => {
    throw error
  })
}

function deliver(receiver: Receiver, event: DocumentsReceivedEvent): void {
  try {
    void Promise.resolve(receiver(event)).catch(reportLater)
  } catch (error) {
    reportLater(error)
  }
}

function installReceiver(): void {
  if (restore || typeof window === 'undefined') return
  const target = window as unknown as Record<string, unknown>
  const had = 'onNativeDocumentsReceived' in target
  const previous = target.onNativeDocumentsReceived
  target.onNativeDocumentsReceived = (payload: unknown) => {
    if (typeof previous === 'function') previous(payload)
    const documents = parseDocuments((payload as { documents?: unknown } | null)?.documents, true)
    if (!documents) return
    for (const receiver of [...receivers]) deliver(receiver, { documents })
  }
  restore = () => {
    if (had) target.onNativeDocumentsReceived = previous
    else delete target.onNativeDocumentsReceived
    restore = null
  }
}

/**
 * Receives the files that other apps share into this web app (Share Extension,
 * "Open in"; needs the capability `receiveDocuments`). The app has already
 * uploaded them (kind `shared`) when this is called; the page gets the
 * `NativeDocument`s with the backend's answer in `upload`.
 *
 * Sets `window.onNativeDocumentsReceived`, then asks once for the batches that
 * arrived while the page was not listening (`consumeReceivedDocuments`) and passes
 * them to `handler`. Call it as early as possible, once per page. A batch is
 * delivered exactly once: while at least one handler is registered the app calls
 * the page, otherwise it queues the batch. The returned function removes the
 * handler; when the last one is removed, `window.onNativeDocumentsReceived` is
 * removed too, so the app queues again.
 *
 * In the browser and in an app without the feature this only registers the
 * handler, which is never called. Never throws.
 */
export function onDocumentsReceived(handler: Receiver): () => void {
  const receiver: Receiver = (event) => handler(event)
  receivers.add(receiver)
  installReceiver()
  if (hasFeature('receiveDocuments')) {
    void consumeReceivedDocuments().then((res) => {
      if (res.ok && res.documents.length > 0 && receivers.has(receiver)) {
        deliver(receiver, { documents: res.documents })
      }
    })
  }
  return () => {
    receivers.delete(receiver)
    if (receivers.size === 0) restore?.()
  }
}

// --- previewFile ----------------------------------------------------------------

export type PreviewFileOptions = {
  /** A file on this web app's own origin, absolute or relative. */
  url: string
  /** Name for the preview and for "Save"; default: from the URL. */
  filename?: string
}

/** `status` is the HTTP status when the download failed (`error: 'failed'`). */
export type PreviewFileResult = { ok: true } | (NativeFailure & { status?: number })

function previewProblem(options: unknown): { problem?: string; absolute?: string } {
  if (!isRecord(options))
    return { problem: 'options.url has to be a URL on the web app’s own origin.' }
  if (options.filename !== undefined && typeof options.filename !== 'string') {
    return { problem: 'filename has to be a string.' }
  }
  const { problem, absolute } = sameOriginUrl(options.url, 'url')
  return problem ? { problem } : { absolute }
}

/**
 * Previews a file of this web app natively (Quick Look: zoom, share, save,
 * markup). The app downloads `url` with the web view’s cookies (and the bearer
 * if the web app has `identity`), so the file may be protected. Resolves once the
 * preview is shown.
 *
 * - `url` must be on the web app’s own origin, else `invalid` (nothing is asked).
 * - HTTP status >= 400: `{ ok: false, error: 'failed', status }`.
 * - Browser: opens the URL in a new tab and resolves `{ ok: true }`.
 * - App without the feature `previewFile`: `unavailable`. Never throws.
 */
export async function previewFile(options: PreviewFileOptions): Promise<PreviewFileResult> {
  const { problem, absolute } = previewProblem(options)
  if (problem || !absolute) return invalid('previewFile', problem ?? 'invalid url.')
  if (!isNativeApp()) {
    window.open(absolute, '_blank', 'noopener')
    return { ok: true }
  }
  const payload: Record<string, unknown> = { url: absolute }
  if (options.filename !== undefined) payload.filename = options.filename
  const answer = await callFeature('previewFile', 'previewFile', payload)
  if (answer.ok) return { ok: true }
  const failure: PreviewFileResult = asFailure(answer)
  const status = (answer as { status?: unknown }).status
  if (typeof status === 'number') failure.status = status
  return failure
}

// --- showDocument: the native viewer ---------------------------------------------

/** Limits of the viewer. */
export const VIEWER_LIMITS = { highlights: 500 } as const

/**
 * A marked area on a page. `x`, `y`, `w`, `h` are fractions (0 to 1) of the page, the
 * origin being the top left; `page` is 1-based.
 */
export type DocumentHighlight = {
  id: string
  page: number
  x: number
  y: number
  w: number
  h: number
  style: 'primary' | 'secondary'
  /** Shown as delivered. */
  label?: string
}

export type ShowDocumentOptions = {
  /** Echoed in the document events and used by `updateDocument`. */
  id?: string
  /** A PDF on this web app's own origin, loaded like `previewFile`. */
  url: string
  title?: string
  /** 1-based page to open. */
  page?: number
  /** At most 500. */
  highlights?: DocumentHighlight[]
  /** The id of a highlight; the viewer scrolls to it. */
  selected?: string
}

export type UpdateDocumentOptions = {
  id: string
  highlights?: DocumentHighlight[]
  selected?: string
  page?: number
}

/** `highlightId` is `null` outside a highlight; `x`, `y` are fractions of the page. */
export type DocumentTapEvent = {
  id: string
  highlightId: string | null
  page: number
  x: number
  y: number
}

export type DocumentPageEvent = { id: string; page: number }

export type ShowDocumentResult = PreviewFileResult

function fraction(value: unknown): boolean {
  return typeof value === 'number' && value >= 0 && value <= 1
}

function highlightProblem(highlights: unknown): string | undefined {
  if (!Array.isArray(highlights)) return 'highlights has to be a list.'
  if (highlights.length > VIEWER_LIMITS.highlights) {
    return `${highlights.length} highlights, the app takes at most ${VIEWER_LIMITS.highlights}.`
  }
  const ids = new Set<string>()
  for (const [i, h] of highlights.entries()) {
    const at = `highlights[${i}]`
    if (!isRecord(h) || !nonEmptyString(h.id)) return `${at} needs an id.`
    if (ids.has(h.id)) return `${at}: the id "${h.id}" is used twice.`
    ids.add(h.id)
    if (!(Number.isInteger(h.page) && (h.page as number) >= 1)) return `${at}.page is 1-based.`
    for (const key of ['x', 'y', 'w', 'h'] as const) {
      if (!fraction(h[key])) return `${at}.${key} has to be a fraction from 0 to 1.`
    }
    if (h.style !== 'primary' && h.style !== 'secondary')
      return `${at}.style has to be primary or secondary.`
    if (h.label !== undefined && typeof h.label !== 'string')
      return `${at}.label has to be a string.`
  }
  return undefined
}

function viewerProblem(options: unknown, update: boolean): { problem?: string; absolute?: string } {
  if (!isRecord(options)) return { problem: 'options have to be an object.' }
  if (options.id !== undefined && !nonEmptyString(options.id))
    return { problem: 'id has to be a non-empty string.' }
  if (update && !nonEmptyString(options.id))
    return { problem: 'id of the open viewer is required.' }
  if (
    options.page !== undefined &&
    !(Number.isInteger(options.page) && (options.page as number) >= 1)
  ) {
    return { problem: 'page is a whole number from 1.' }
  }
  if (options.selected !== undefined && !nonEmptyString(options.selected)) {
    return { problem: 'selected has to be the id of a highlight.' }
  }
  if (options.title !== undefined && typeof options.title !== 'string')
    return { problem: 'title has to be a string.' }
  if (options.highlights !== undefined) {
    const problem = highlightProblem(options.highlights)
    if (problem) return { problem }
  }
  if (update) return {}
  const { problem, absolute } = sameOriginUrl(options.url, 'url')
  return problem ? { problem } : { absolute }
}

/**
 * Opens a PDF of your web app in the native full-screen viewer (zoom, page
 * thumbnails, text search) with your **highlights** drawn on the pages, for example the
 * places an offer's line items were read from. Requires `customChrome` and the feature
 * `documentViewer`. Resolves `{ ok: true }` when the user closes the viewer.
 *
 * ```ts
 * const off = on('documentTap', ({ highlightId }) => highlightId && selectLine(highlightId))
 * await showDocument({
 *   id: 'offer-pdf',
 *   url: `/api/offers/${id}/file`,
 *   highlights: [{ id: 'l1', page: 1, x: 0.1, y: 0.4, w: 0.8, h: 0.05, style: 'primary' }],
 * })
 * off()
 * ```
 *
 * While it is open, `updateDocument` changes the highlights, the selection and the page.
 * Events: `on('documentTap')` and `on('documentPage')`.
 *
 * `url` must be on the web app's own origin, else `invalid` (nothing is asked); it is
 * sent as an absolute URL. An HTTP status of 400 or more is `{ ok: false, error:
 * 'failed', status }`. Unavailable in the browser and in an app without the feature:
 * show your own PDF viewer (or use `previewFile`).
 */
export async function showDocument(options: ShowDocumentOptions): Promise<ShowDocumentResult> {
  const { problem, absolute } = viewerProblem(options, false)
  if (problem || !absolute) return invalid('showDocument', problem ?? 'invalid url.')
  if (
    isDevelopment() &&
    options.selected !== undefined &&
    options.highlights &&
    !options.highlights.some((h) => h.id === options.selected)
  ) {
    warn('showDocument', [`selected "${options.selected}" is not one of the highlights.`])
  }
  const answer = await callFeature('documentViewer', 'showDocument', { ...options, url: absolute })
  if (answer.ok) return { ok: true }
  const failure: PreviewFileResult = asFailure(answer)
  const status = (answer as { status?: unknown }).status
  if (typeof status === 'number') failure.status = status
  return failure
}

/**
 * Updates the open viewer `id`: replaces `highlights`, selects one (`selected`, the
 * viewer scrolls to it) or goes to a `page`. Answers `notFound` if no such viewer is
 * open.
 */
export async function updateDocument(
  options: UpdateDocumentOptions
): Promise<{ ok: true } | NativeFailure> {
  const { problem } = viewerProblem(options, true)
  if (problem) return invalid('updateDocument', problem)
  const answer = await callFeature('documentViewer', 'updateDocument', { ...options })
  return answer.ok ? { ok: true } : asFailure(answer)
}
