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
  | (string & {})

export type NativeResult<T extends object = object> =
  | ({ ok: true } & T)
  | { ok: false; error: NativeError }

/**
 * Capabilities the app can grant to a web app (`WebAppCapability`).
 *
 * - `identity`: the web app gets the Entra token of the app's sign-in: its
 *   backend receives `Authorization: Bearer …`, `fetch`/XHR to its own backend
 *   carry it automatically, and `getAccessToken()` works.
 * - `deviceApps`: needed for `addReminder` and `saveContact`. `navigate` and
 *   `callPhone` only open another app and need no capability.
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
  | (string & {})

type Message = Record<string, unknown>

export type BMSNativeApi = {
  isNativeApp?: boolean
  platform?: string
  version?: string
  appVersion?: string
  webAppId?: string
  capabilities?: readonly string[]
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
