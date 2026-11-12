// Callbacks from the app into the page. The app calls global functions such as
// `window.onNativeMenuSelect(id)` — they are assigned once here and dispatched
// to any number of listeners. A custom function that was already set before
// keeps being called.

import type { DocumentPageEvent, DocumentTapEvent } from './documents.js'
import type { LayoutInfo } from './layout.js'
import type { MenuExpandEvent } from './menus.js'
import type {
  NativeSurfaceActionEvent,
  SurfaceChangeEvent,
  SurfaceSearchEvent,
} from './surfaces.js'

export type NativeEventMap = {
  /** Item in the native menu (or a Spotlight/Siri result) tapped. */
  menuSelect: string
  /** Action button at the top right tapped. */
  actionButtonTap: string
  /** Item in the custom bottom bar tapped. */
  bottomBarTap: string
  /** Result of `scanBarcode()` (single scan). */
  barcodeScanned: string
  /** Result of a multi scan (`scanBarcodes()`): all codes, in scan order. */
  barcodesScanned: string[]
  /** Result of `scanText()`. */
  textScanned: string
  /**
   * The app waits for the page: a native form was submitted or a content action
   * tapped with `wait`. Answer with `surfaceResult`, or let the `onSubmit` /
   * `onAction` options of `showForm` / `showContent` do it.
   */
  surfaceAction: NativeSurfaceActionEvent
  /**
   * The layout of the web view changed: the keyboard appeared or went away (final
   * values), the device turned, or the window was resized (Split View, Stage
   * Manager). Feature `layout`; see `getLayout`.
   */
  layoutChange: LayoutInfo
  // --- 2026-11b ---
  /** A selection in the pull-down menu of an action button (`actionButtons[].menu`). */
  actionButtonMenuSelect: { buttonId: string; id: string }
  /** A selection in the title menu (`setChrome({ title: { menu } })`). */
  titleMenuSelect: { id: string }
  /** The native search field of the navigation bar (`setChrome({ search })`). */
  search: NativeSearchEvent
  /** The user cancelled the search field. */
  searchCancel: { id: string }
  /** A tap on a segment (`setChrome({ segments })`). */
  segmentSelect: { id: string; item: string }
  /** A tap on a sidebar entry (`setChrome({ sidebar })`, iPad). */
  sidebarSelect: { id: string }
  /** A swipe action of a sidebar entry. */
  sidebarAction: { itemId: string; id: string }
  /** Typing into the search field of the sidebar (debounced 250 ms). */
  sidebarSearch: { query: string }
  /** Shake to undo, the three-finger gestures or the edit menu (`setChrome({ undo })`). */
  undo: { action: 'undo' | 'redo' }
  /** A registered key command (`setKeyCommands`) was pressed. */
  keyCommand: { id: string }
  /** A tap on the keyboard toolbar (`setKeyboardToolbar`). The focus stays. */
  keyboardToolbarTap: { id: string }
  /** The tap on the action of a toast. `toast(…, { action, onAction })` handles it for you. */
  toastAction: { toastId: string; id: string }
  /** The user opened a lazy menu item. `showMenu(…, { loadChildren })` handles it for you. */
  menuExpand: MenuExpandEvent
  /** A `live` field changed. `showForm(…, { onChange })` handles it for you. */
  surfaceChange: SurfaceChangeEvent
  /** Typing into a search field with `source: 'page'`. `onSearch` handles it for you. */
  surfaceSearch: SurfaceSearchEvent
  /** A tap in the native document viewer. */
  documentTap: DocumentTapEvent
  /** The visible page of the native document viewer changed. */
  documentPage: DocumentPageEvent
}

/** What the native search field delivers. */
export type NativeSearchEvent = {
  /** The `id` of `setChrome({ search })`. */
  id: string
  query: string
  /** The selected scope, if the field has scopes. */
  scope?: string | null
  /** `true` for the Search key and for a scanned barcode. */
  submitted: boolean
  /** `typing` (debounced 250 ms), `submit` (Search key) or `barcode`. */
  source: 'typing' | 'submit' | 'barcode'
}

export type NativeEvent = keyof NativeEventMap

const GLOBALS: Record<NativeEvent, string> = {
  menuSelect: 'onNativeMenuSelect',
  actionButtonTap: 'onNativeActionButtonTap',
  bottomBarTap: 'onNativeBottomBarTap',
  barcodeScanned: 'onBarcodeScanned',
  barcodesScanned: 'onBarcodesScanned',
  textScanned: 'onTextScanned',
  surfaceAction: 'onNativeSurfaceAction',
  layoutChange: 'onNativeLayoutChange',
  actionButtonMenuSelect: 'onNativeActionButtonMenuSelect',
  titleMenuSelect: 'onNativeTitleMenuSelect',
  search: 'onNativeSearch',
  searchCancel: 'onNativeSearchCancel',
  segmentSelect: 'onNativeSegmentSelect',
  sidebarSelect: 'onNativeSidebarSelect',
  sidebarAction: 'onNativeSidebarAction',
  sidebarSearch: 'onNativeSidebarSearch',
  undo: 'onNativeUndo',
  keyCommand: 'onNativeKeyCommand',
  keyboardToolbarTap: 'onNativeKeyboardToolbarTap',
  toastAction: 'onNativeToastAction',
  menuExpand: 'onNativeMenuExpand',
  surfaceChange: 'onNativeSurfaceChange',
  surfaceSearch: 'onNativeSurfaceSearch',
  documentTap: 'onNativeDocumentTap',
  documentPage: 'onNativeDocumentPage',
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
