import { call, isNativeApp, post, send, type NativeResult } from './bridge.js'

export type ToastStyle = 'info' | 'success' | 'warning' | 'error'

/** Short native toast. No-op outside the app (a web toast is up to the page). */
export function toast(message: string, style: ToastStyle = 'info', duration?: number): void {
  if (!isNativeApp()) return
  post('toast', { message, style, ...(duration != null && { duration }) })
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
