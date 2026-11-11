// Back interception: the page decides whether the native back button and the
// left-edge swipe act on the page (close a dialog, step back in a wizard) or on
// the web app. Details: docs/webapp-chrome-guide.md

import { call, hasFeature } from './bridge.js'

/** What triggered the back request: the native back button or the left-edge swipe. */
export type BackSource = 'button' | 'swipe'

/**
 * Return `true` if the page handled it (a dialog was closed, a step went back):
 * the app does nothing more. `false`: today's default (the button closes the web
 * app, the swipe goes back in the web view history).
 */
export type BackHandler = (source: BackSource) => boolean | Promise<boolean>

/** The app waits 800 ms for the answer; a handler that has not settled by then counts as `false`. */
export const BACK_HANDLER_TIMEOUT_MS = 700

const handlers: BackHandler[] = []
let restore: (() => void) | null = null

async function ask(source: BackSource): Promise<boolean> {
  // The most recent handler first; the first one that handles it wins.
  for (const handler of [...handlers].reverse()) {
    try {
      if ((await handler(source)) === true) return true
    } catch {
      // A throwing handler did not handle it.
    }
  }
  return false
}

async function answer(payload: unknown): Promise<void> {
  const source: BackSource =
    (payload as { source?: unknown } | null)?.source === 'swipe' ? 'swipe' : 'button'
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => resolve(false), BACK_HANDLER_TIMEOUT_MS)
  })
  const handled = await Promise.race([ask(source), timeout])
  clearTimeout(timer)
  await call('backResult', { handled })
}

function enable(): void {
  if (restore || typeof window === 'undefined') return
  const target = window as unknown as Record<string, unknown>
  const had = 'onNativeBackRequested' in target
  const previous = target.onNativeBackRequested
  target.onNativeBackRequested = (payload: unknown) => {
    void answer(payload)
  }
  restore = () => {
    if (had) target.onNativeBackRequested = previous
    else delete target.onNativeBackRequested
    restore = null
  }
  void call('setBackInterception', { enabled: true })
}

function disable(): void {
  if (!restore) return
  restore()
  void call('setBackInterception', { enabled: false })
}

/**
 * Intercepts the native back button and the left-edge swipe for as long as the
 * handler is registered (feature `backInterception`). The handler gets the source
 * and answers whether it handled the request, see `BackHandler`. Answer quickly
 * (no network): the app waits 800 ms and the package answers `false` after
 * `BACK_HANDLER_TIMEOUT_MS`.
 *
 * Several handlers can be registered (a dialog on top of a page): the newest is
 * asked first. The returned function removes the handler; the last one to go turns
 * the interception off again. The setting lasts until it is turned off or the
 * page reloads completely: route changes of a single-page app do not reset it, so
 * remove the handler when its screen goes away.
 *
 * A long press on the back button always closes the web app.
 *
 * Browser and apps without the feature: does nothing, returns a no-op. Never throws.
 */
export function onBackRequested(handler: BackHandler): () => void {
  if (!hasFeature('backInterception')) return () => {}
  handlers.push(handler)
  enable()
  let active = true
  return () => {
    if (!active) return
    active = false
    const index = handlers.lastIndexOf(handler)
    if (index >= 0) handlers.splice(index, 1)
    if (handlers.length === 0) disable()
  }
}
