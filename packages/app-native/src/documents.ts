// Documents: `pickFiles`, files shared into the web app (`onDocumentsReceived`,
// `consumeReceivedDocuments`) and `previewFile`. The shared result shape
// `NativeDocument` is also what `scanDocument` (scan.ts) delivers. The backend
// side is `bmsdna.app_native.documents`. Details: docs/documents-guide.md

import { hasFeature, isNativeApp, type NativeFailure } from './bridge.js'
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
   * The JSON response of the backend verbatim (for the document router of
   * `bmsdna-app-native`: `{"ok": true, "id": "…"}`), `null` if it was not JSON.
   * It passes through the page: the backend must not put secrets into it.
   */
  body: Record<string, unknown> | null
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
 * `error` first.
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
  if (!isRecord(options) || typeof options.url !== 'string' || options.url === '') {
    return { problem: 'options.url has to be a URL on the web app’s own origin.' }
  }
  if (options.filename !== undefined && typeof options.filename !== 'string') {
    return { problem: 'filename has to be a string.' }
  }
  if (typeof location === 'undefined')
    return { problem: 'there is no page to resolve url against.' }
  let absolute: URL
  try {
    absolute = new URL(options.url, location.href)
  } catch {
    return { problem: 'url is not a valid URL.' }
  }
  if (absolute.origin !== location.origin) {
    return { problem: 'url has to be on the web app’s own origin.' }
  }
  return { absolute: absolute.href }
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
