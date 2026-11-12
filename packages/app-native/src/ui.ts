import { call, isNativeApp, post, send, type NativeFailure, type NativeResult } from './bridge.js'
import { isDevelopment, warn } from './dev.js'
import { on } from './events.js'
import { asFailure, badAnswer, callFeature, invalid, isRecord, nonEmptyString } from './internal.js'

export type ToastStyle = 'info' | 'success' | 'warning' | 'error'

/** Limits of a toast with a response. */
export const TOAST_LIMITS = {
  /** `duration` in seconds, from … */
  minSeconds: 1,
  /** … to. */
  maxSeconds: 10,
  /** Default `duration`: 2.5 s, 6 s with an action. */
  defaultSeconds: 2.5,
  defaultActionSeconds: 6,
} as const

export type ToastAction = {
  /** Comes back with the tap. */
  id: string
  /** Shown as delivered. */
  label: string
}

export type ToastOptions = {
  style?: ToastStyle
  /** 1 to 10 seconds; default 2.5, or 6 with an `action`. */
  duration?: number
  /** A button in the toast ("Undo"). */
  action?: ToastAction
  /** Called with the action `id` when the user taps the action. The toast closes then. */
  onAction?: (id: string) => void
}

/** `toastId` identifies the toast in `onNativeToastAction`. */
export type ToastResult = { ok: true; toastId: string } | NativeFailure

// The handler of the toast that is visible. A new toast replaces the old one, so
// only one handler is ever needed.
let toastHandler: { toastId: string; handle: (id: string) => void } | null = null
let listeningForToast = false

function listenForToast(): void {
  if (listeningForToast) return
  listeningForToast = true
  on('toastAction', (event) => {
    if (!toastHandler || !isRecord(event) || event.toastId !== toastHandler.toastId) return
    const { handle } = toastHandler
    toastHandler = null // the toast closes with the tap
    try {
      handle(event.id)
    } catch (error) {
      setTimeout(() => {
        throw error
      })
    }
  })
}

function toastProblem(message: unknown, options: ToastOptions): string | undefined {
  if (typeof message !== 'string') return 'message has to be a string.'
  if (!isRecord(options)) return 'options have to be an object.'
  const { duration, action, style } = options
  if (style !== undefined && !['info', 'success', 'warning', 'error'].includes(style)) {
    return 'style has to be info, success, warning or error.'
  }
  if (
    duration !== undefined &&
    !(
      typeof duration === 'number' &&
      duration >= TOAST_LIMITS.minSeconds &&
      duration <= TOAST_LIMITS.maxSeconds
    )
  ) {
    return `duration has to be ${TOAST_LIMITS.minSeconds} to ${TOAST_LIMITS.maxSeconds} seconds.`
  }
  if (
    action !== undefined &&
    (!isRecord(action) || !nonEmptyString(action.id) || !nonEmptyString(action.label))
  ) {
    return 'action needs an id and a label.'
  }
  if (options.onAction !== undefined && typeof options.onAction !== 'function') {
    return 'onAction has to be a function.'
  }
  return undefined
}

/**
 * Short native toast. No-op outside the app (a web toast is up to the page).
 *
 * `toast(message, style?, duration?)` is fire-and-forget and returns nothing.
 *
 * `toast(message, { style, duration, action, onAction })` (feature `toastActions`)
 * resolves `{ ok: true, toastId }` once the toast is shown. With an `action` the toast
 * has a button; a tap calls `onAction(action.id)` and closes it. The toast sits above
 * the bottom bar and the keyboard, and a new toast replaces the visible one (the old
 * `onAction` is dropped with it). `duration` is 1 to 10 seconds (default 2.5, with an
 * action 6).
 *
 * ```ts
 * await toast('Offer deleted', { action: { id: 'undo', label: 'Undo' }, onAction: () => restore() })
 * ```
 *
 * The second form answers `unavailable` outside the app and in an app without the
 * feature (show your own toast then), `invalid` for a bad option without asking the app.
 */
export function toast(message: string, style?: ToastStyle, duration?: number): void
export function toast(message: string, options: ToastOptions): Promise<ToastResult>
export function toast(
  message: string,
  second?: ToastStyle | ToastOptions,
  duration?: number
): void | Promise<ToastResult> {
  if (typeof second === 'object' && second !== null) return toastWithResponse(message, second)
  if (!isNativeApp()) return
  post('toast', { message, style: second ?? 'info', ...(duration != null && { duration }) })
}

async function toastWithResponse(message: string, options: ToastOptions): Promise<ToastResult> {
  const problem = toastProblem(message, options)
  if (problem) return invalid('toast', problem)
  const { onAction, ...rest } = options
  if (onAction && !rest.action && isDevelopment()) {
    warn('toast', ['onAction is given but there is no action: it will never be called.'])
  }
  const answer = await callFeature('toastActions', 'toast', { message, ...rest })
  if (!answer.ok) return asFailure(answer)
  const { toastId } = answer as { toastId?: unknown }
  if (typeof toastId !== 'string') return badAnswer()
  toastHandler = onAction && rest.action ? { toastId, handle: onAction } : null
  if (toastHandler) listenForToast()
  return { ok: true, toastId }
}

export type HapticStyle =
  | 'light'
  | 'medium'
  | 'heavy'
  | 'soft'
  | 'rigid'
  | 'selection'
  | 'success'
  | 'warning'
  | 'error'

/** Haptic feedback. No-op outside the app. */
export function haptic(style: HapticStyle): void {
  if (!isNativeApp()) return
  post('haptic', { style })
}

export type ShareData = { title?: string; text?: string; url?: string }
export type ShareOutcome = 'shared' | 'copied' | 'cancelled' | 'unavailable'

/**
 * App: native share sheet. Browser: Web Share API, otherwise copies the URL
 * (or text) to the clipboard.
 */
export async function share(data: ShareData): Promise<ShareOutcome> {
  if (isNativeApp()) {
    const res = await send('share', data)
    if (res.ok) return 'shared'
    return res.error === 'cancelled' ? 'cancelled' : 'unavailable'
  }
  if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
    try {
      await navigator.share(data)
      return 'shared'
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return 'cancelled'
    }
  }
  const text = data.url ?? data.text
  if (text && typeof navigator !== 'undefined' && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return 'copied'
    } catch {
      // fall through
    }
  }
  return 'unavailable'
}

/** Number badge on this web app's tile/tab; `0` removes it. */
export function setBadge(count: number): void {
  if (!isNativeApp()) return
  post('setBadge', { count: Math.max(0, Math.floor(count)) })
}

/** Deliberately opens the URL outside the app (Safari); in the browser in a new tab. */
export function openExternal(url: string): void {
  if (isNativeApp()) post('openExternal', { url })
  else if (typeof window !== 'undefined') window.open(url, '_blank', 'noopener')
}

/**
 * Face ID / Touch ID (fallback: device passcode) before a critical action.
 * ONLY a UX confirmation on the device — no proof for the backend; the
 * server-side authorization check still applies. Outside the app `{ ok: true }`,
 * so the web flow continues unchanged.
 */
export async function biometricConfirm(reason: string): Promise<NativeResult> {
  if (typeof window === 'undefined' || !window.BMSNative) return { ok: true }
  return call('biometricConfirm', { reason })
}
