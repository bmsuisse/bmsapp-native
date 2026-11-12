// Lowest layer: talks to `window.BMSNative`, which the app injects into every
// page (see `WebView.nativeEnvironmentScript` in the app repo). Older app
// builds only know the raw message handler
// `window.webkit.messageHandlers.nativeBridge` — enough for fire-and-forget,
// but it returns no responses.
//
// In a regular browser neither exists: `call` then responds with
// `{ ok: false, error: 'unavailable' }`, `post` does nothing.

/** Error codes from the app. Unknown codes are passed through unchanged as `string`. */
export type NativeError =
  | 'unavailable'
  | 'capability'
  | 'invalid'
  | 'cancelled'
  | 'failed'
  | 'disabled'
  | 'notFound'
  | 'notConfigured'
  | 'noFeed'
  | 'unknownAction'
  /** The user has not allowed access to Reminders or Contacts (`addReminder`, `saveContact`). */
  | 'denied'
  /** `getAccessToken` from a page or a frame that does not belong to this web app. */
  | 'forbidden'
  /** `getAccessToken` while nobody is signed in, or when no token can be had right now. */
  | 'notSignedIn'
  /** A document or a request is beyond the size limit (25,000,000 bytes per document). */
  | 'tooLarge'
  /** `getAccessToken` with a `resource`: the user has to consent first (see `interactive`). */
  | 'consentRequired'
  | (string & {})

export type NativeResult<T extends object = object> =
  | ({ ok: true } & T)
  | { ok: false; error: NativeError }

/**
 * A failed call of the 2026-11 contract (documents, voice, layout, preview,
 * resource tokens). `message` is an English sentence for the developer: never
 * show it to the user.
 */
export type NativeFailure = { ok: false; error: NativeError; message?: string }

/**
 * Capabilities the app can grant to a web app (`WebAppCapability`).
 *
 * - `identity`: the web app gets the Entra token of the app's sign-in: its
 *   backend receives `Authorization: Bearer …`, `fetch`/XHR to its own backend
 *   carry it automatically, and `getAccessToken()` works.
 * - `deviceApps`: needed for `addReminder` and `saveContact`. `navigate` and
 *   `callPhone` only open another app and need no capability.
 * - `nativeForms`: needed for `showForm`. The form field types `photo` (camera
 *   source), `scan` and `barcode` also need `camera`.
 * - `nativeContent`: needed for `showContent`. `closeSurface` and
 *   `surfaceResult` need either of the two. The follow-up actions
 *   `saveContact` and `addReminder` (in `then`) also need `deviceApps`.
 * - `receiveDocuments`: files shared from other apps (Share Extension, "Open
 *   in") are uploaded to this web app, which is then opened. Needs a
 *   `documentUploadPath` too. See `onDocumentsReceived`.
 * - `microphone`: `getUserMedia({ audio: true })` of the page is granted
 *   (after the iOS permission prompt), and `dictate` works.
 */
export type Capability =
  | 'location'
  | 'camera'
  | 'notifications'
  | 'identity'
  | 'customChrome'
  | 'customBottomBar'
  | 'dashboardWidgets'
  | 'liveActivities'
  | 'approvals'
  | 'deviceApps'
  | 'nativeForms'
  | 'nativeContent'
  | 'receiveDocuments'
  | 'microphone'
  | (string & {})

/**
 * The features of the 2026-11 contract that the app lists in
 * `window.BMSNative.features`. A feature that is not listed is not supported;
 * an older app has no list at all. Ask with `hasFeature`.
 *
 * - `scanResult`: `scanDocument` answers with `documents`.
 * - `scanOptions`: `scanDocument` honours `context`, `kind`, `mode`, `multiple`.
 * - `pickFiles`, `receiveDocuments`, `previewFile`: the function of the same name.
 * - `mediaCapture`: `getUserMedia({ audio: true })` works (needs `microphone`).
 * - `dictate`, `layout`: `dictate`, `getLayout` and the layout event.
 * - `backInterception`: `onBackRequested`.
 * - `tokenResources`: `getAccessToken({ resource })`.
 *
 * 2026-11b (these need `customChrome`, `liveSurfaces` also `nativeForms` or `nativeContent`):
 *
 * - `menus`: `showMenu` and menus on action buttons. `titleMenu`: `setChrome({ title })`.
 * - `alerts`: `showAlert`. `toastActions`: `toast` with an action.
 * - `liveSurfaces`: `updateSurface` and `live` fields. `pageSearch`: search fields
 *   with `source: 'page'`.
 * - `navSearch`, `segments`, `sidebar`, `undoGestures`: the `search`, `segments`,
 *   `sidebar` and `undo` parts of `setChrome`.
 * - `keyboardToolbar`: `setKeyboardToolbar`. `keyCommands`: `setKeyCommands`.
 * - `documentViewer`: `showDocument`, `updateDocument`. `pickers`: `showPicker`.
 */
export const FEATURES = [
  'scanResult',
  'scanOptions',
  'pickFiles',
  'receiveDocuments',
  'mediaCapture',
  'dictate',
  'layout',
  'backInterception',
  'previewFile',
  'tokenResources',
  // 2026-11b
  'menus',
  'titleMenu',
  'alerts',
  'toastActions',
  'liveSurfaces',
  'pageSearch',
  'navSearch',
  'keyboardToolbar',
  'segments',
  'sidebar',
  'documentViewer',
  'undoGestures',
  'pickers',
  'keyCommands',
] as const

export type Feature = (typeof FEATURES)[number]

type Message = Record<string, unknown>

export type BMSNativeApi = {
  isNativeApp?: boolean
  platform?: string
  version?: string
  appVersion?: string
  webAppId?: string
  capabilities?: readonly string[]
  /** The contract features the app implements (see `Feature`). Missing in older apps. */
  features?: readonly string[]
  postMessage: (message: Message) => void
  call: (action: string, payload?: Message) => Promise<unknown>
}

declare global {
  interface Window {
    BMSNative?: BMSNativeApi
    webkit?: {
      messageHandlers?: {
        nativeBridge?: { postMessage: (message: Message) => void }
      }
    }
  }
}

function win(): Window | undefined {
  return typeof window === 'undefined' ? undefined : window
}

/** Is the page running inside the BMS app? */
export function isNativeApp(): boolean {
  const w = win()
  return !!w?.BMSNative || !!w?.webkit?.messageHandlers?.nativeBridge
}

export type NativeInfo = {
  platform: string
  appVersion: string
  webAppId: string
  capabilities: readonly Capability[]
}

/** The app's info about this web app; `null` outside the app. */
export function nativeInfo(): NativeInfo | null {
  const n = win()?.BMSNative
  if (!n) return null
  return {
    platform: n.platform ?? 'ios',
    appVersion: n.appVersion ?? n.version ?? '',
    webAppId: n.webAppId ?? '',
    capabilities: n.capabilities ?? [],
  }
}

/**
 * Has the app granted this capability to this web app? Always `false` outside
 * the app. The app still checks on its own — this only saves unnecessary
 * calls or lets you hide buttons.
 */
export function can(capability: Capability): boolean {
  return nativeInfo()?.capabilities.includes(capability) ?? false
}

/**
 * Is this the answer of an app (or of the package) that cannot do the call: `unavailable`,
 * or `unknownAction` from an app that predates it? Both mean "use your own UI"; the
 * package keeps the original code in the result, so test with this instead of `===`.
 */
export function isUnavailable(result: { ok: boolean; error?: unknown }): boolean {
  return !result.ok && (result.error === 'unavailable' || result.error === 'unknownAction')
}

/**
 * Does the app implement this feature of the contract? `false` outside the app
 * and in apps that predate `window.BMSNative.features`. Functions that depend
 * on a feature check this themselves and answer `unavailable` — use it to hide
 * buttons.
 */
export function hasFeature(name: Feature | (string & {})): boolean {
  const features = win()?.BMSNative?.features
  return Array.isArray(features) && features.includes(name)
}

/** Message without a response. No-op outside the app. */
export function post(action: string, payload: Message = {}): void {
  const w = win()
  const message = { ...payload, action }
  if (w?.BMSNative) w.BMSNative.postMessage(message)
  else w?.webkit?.messageHandlers?.nativeBridge?.postMessage(message)
}

/**
 * Message with a response. Without `BMSNative` (browser or a very old app
 * build) resolves immediately to `{ ok: false, error: 'unavailable' }`.
 */
export async function call<T extends object = object>(
  action: string,
  payload: Message = {}
): Promise<NativeResult<T>> {
  const n = win()?.BMSNative
  if (!n) return { ok: false, error: 'unavailable' }
  try {
    const result = (await n.call(action, payload)) as NativeResult<T> | undefined
    return result ?? { ok: false, error: 'failed' }
  } catch {
    return { ok: false, error: 'unavailable' }
  }
}

/**
 * Like `call`, but falls back to `post` on app builds without `BMSNative`
 * and then optimistically reports `{ ok: true }`.
 */
export async function send(action: string, payload: Message = {}): Promise<NativeResult> {
  if (win()?.BMSNative) return call(action, payload)
  if (!isNativeApp()) return { ok: false, error: 'unavailable' }
  post(action, payload)
  return { ok: true }
}
