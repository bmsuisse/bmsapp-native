// Callbacks from the app into the page. The app calls global functions such as
// `window.onNativeMenuSelect(id)` — they are assigned once here and dispatched
// to any number of listeners. A custom function that was already set before
// keeps being called.

export type NativeEventMap = {
  /** Item in the native menu (or a Spotlight/Siri result) tapped. */
  menuSelect: string
  /** Action button at the top right tapped. */
  actionButtonTap: string
  /** Item in the custom bottom bar tapped. */
  bottomBarTap: string
  /** Result of `scanBarcode()`. */
  barcodeScanned: string
}

export type NativeEvent = keyof NativeEventMap

const GLOBALS: Record<NativeEvent, string> = {
  menuSelect: 'onNativeMenuSelect',
  actionButtonTap: 'onNativeActionButtonTap',
  bottomBarTap: 'onNativeBottomBarTap',
  barcodeScanned: 'onBarcodeScanned',
}

type Listener<E extends NativeEvent> = (payload: NativeEventMap[E]) => void

// Untyped internally; `on` ensures listeners match their event.
const listeners = new Map<NativeEvent, Set<(payload: never) => void>>()
const installed = new Set<NativeEvent>()

function install<E extends NativeEvent>(event: E): void {
  if (installed.has(event) || typeof window === 'undefined') return
  installed.add(event)
  const target = window as unknown as Record<string, unknown>
  const name = GLOBALS[event]
  const previous = typeof target[name] === 'function' ? (target[name] as Listener<E>) : undefined
  target[name] = (payload: NativeEventMap[E]) => {
    previous?.(payload)
    for (const listener of [...(listeners.get(event) ?? [])]) {
      ;(listener as Listener<E>)(payload)
    }
  }
}

/** Registers a listener. Returns a function that unsubscribes it. */
export function on<E extends NativeEvent>(event: E, listener: Listener<E>): () => void {
  install(event)
  let set = listeners.get(event)
  if (!set) listeners.set(event, (set = new Set()))
  const entry = listener as (payload: never) => void
  set.add(entry)
  return () => {
    set.delete(entry)
  }
}
